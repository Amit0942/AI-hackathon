"""Deterministic ingestion of the supplied campaign briefs (`Campaigns/*.docx`).

This is the *structural* half of brief intake: it recovers the document's own
label/value header, its numbered sections and its RFP requirement list without an
LLM in the loop. It is dependency-free — a `.docx` is a zip holding
`word/document.xml`, so the text is extracted with the standard library alone.

Two layers, kept separate on purpose:

* :func:`parse_brief` — lossless structure. Every paragraph ends up either in a
  header field, a section, or ``unparsed``, so nothing is silently dropped.
* :func:`derive_fields` — regex-backed normalisation of the values a brief always
  states (budget, duration, age band, ...). These become the *gold parse* fixtures
  that the Phase 4 LLM extractor is tested against, which is why they must come
  from the documents rather than from an LLM.

Everything the regexes cannot bind — named venue types, walking-radius limits,
weekend weighting, creative-format restrictions — is preserved verbatim in
``requirements`` and ``sections`` and surfaced as an *unresolved requirement*
rather than dropped. That list is the Phase 4/5 capability checklist.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from .paths import ProjectPaths

#: Header labels the briefs use as standalone paragraphs followed by their value.
HEADER_LABELS: tuple[str, ...] = (
    "Company Name",
    "Industry Vertical",
    "Campaign Objective",
    "Target Audience",
    "Campaign Budget",
    "Campaign Duration",
)

_TITLE_RE = re.compile(r"^CLIENT BRIEF\s+(?P<number>\d+)\s*[:\-–—]\s*(?P<title>.+)$", re.I)
_SECTION_RE = re.compile(r"^(?P<number>\d{1,2})\.\s+(?P<title>.{2,80})$")
_LIST_ITEM_RE = re.compile(r"^(?P<number>\d{1,2})\.\s+(?P<text>.+)$")
# The whitespace after the colon is required: without it "Reference Mockup B — 16:9
# Metro Platform" is misread as a label/value pair.
_LABELLED_RE = re.compile(r"^(?P<label>[A-Z][A-Za-z0-9 /&'\-–—]{2,60}):\s+(?P<text>.+)$")
_MONEY_RE = re.compile(r"(?:USD|US\$|\$|INR|EUR|£|€)\s*([\d,]+(?:\.\d+)?)\s*(k|m|thousand|million)?", re.I)
_DURATION_RE = re.compile(r"(\d{1,4})\s*(?:calendar\s*)?days?", re.I)
_AGES_RE = re.compile(r"ages?\s*(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})", re.I)
_SLOTS_RE = re.compile(r"(\d{1,2})\s*(?:rotating\s*)?slots?", re.I)
_SECONDS_RE = re.compile(r"(\d{1,3})\s*seconds?\s*per\s*minute", re.I)
_XML_TAG_RE = re.compile(r"<[^>]+>")
_PARA_END_RE = re.compile(r"</w:p>")
_BREAK_RE = re.compile(r"<w:(?:br|tab)\b[^>]*/?>")

#: Section titles whose body carries hard constraints rather than narrative.
CONSTRAINT_LABEL_HINTS: tuple[str, ...] = ("exclusion", "exclude", "must not", "restrict", "only")


# --------------------------------------------------------------------- extraction
def extract_docx_paragraphs(path: Path | str) -> tuple[str, ...]:
    """Return the document's paragraphs in **document order**, tags stripped.

    Reads ``word/document.xml`` straight out of the zip rather than using
    ``python-docx``. That is deliberate, not a shortcut: these briefs put their
    header label/value pairs in a Word *table*, and ``python-docx`` exposes
    ``document.paragraphs`` and ``document.tables`` as two separate sequences, so
    the header pairs arrive *after* the body and the label/value adjacency that
    :func:`parse_brief` relies on is destroyed. Splitting on ``</w:p>`` keeps every
    paragraph — table cells included — in the order a reader sees them.
    """
    with zipfile.ZipFile(Path(path)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    xml = _BREAK_RE.sub(" ", xml)
    xml = _PARA_END_RE.sub("\n", xml)
    blocks = unescape(_XML_TAG_RE.sub("", xml)).split("\n")

    return tuple(
        cleaned for cleaned in (re.sub(r"\s+", " ", block).strip() for block in blocks) if cleaned
    )


# ------------------------------------------------------------------------ parsing
@dataclass(frozen=True)
class BriefSection:
    number: int
    title: str
    paragraphs: tuple[str, ...]
    #: "Label: value" lines inside the section — where the briefs hide their
    #: location requirements and exclusion criteria.
    labelled: Mapping[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return " ".join(self.paragraphs)


@dataclass(frozen=True)
class CampaignBriefDocument:
    """Structured, lossless view of one supplied brief document."""

    source_file: str
    brief_number: int | None
    title: str
    header: Mapping[str, str]
    sections: tuple[BriefSection, ...]
    requirements: tuple[str, ...]
    unparsed: tuple[str, ...]
    paragraph_count: int

    def section(self, keyword: str) -> BriefSection | None:
        keyword = keyword.lower()
        for section in self.sections:
            if keyword in section.title.lower():
                return section
        return None

    @property
    def raw_text(self) -> str:
        parts = [self.title, *(f"{k}: {v}" for k, v in self.header.items())]
        parts += [f"{s.number}. {s.title}\n{s.text}" for s in self.sections]
        return "\n\n".join(parts)

    @property
    def all_labelled(self) -> Mapping[str, str]:
        merged: dict[str, str] = {}
        for section in self.sections:
            merged.update(section.labelled)
        return merged


def parse_brief(paragraphs: Sequence[str], *, source_file: str) -> CampaignBriefDocument:
    """Recover title, header pairs, numbered sections and the RFP list."""
    brief_number: int | None = None
    title = ""
    header: dict[str, str] = {}
    sections: list[BriefSection] = []
    unparsed: list[str] = []

    current: dict[str, Any] | None = None
    expected_section = 1
    index = 0
    total = len(paragraphs)

    while index < total:
        line = paragraphs[index]

        title_match = _TITLE_RE.match(line)
        if title_match and not title:
            brief_number = int(title_match.group("number"))
            title = title_match.group("title").strip()
            index += 1
            continue

        # A header label sits alone on its line; its value is the next paragraph.
        if current is None and line in HEADER_LABELS and index + 1 < total:
            header[line] = paragraphs[index + 1]
            index += 2
            continue

        # Section headings are short, unpunctuated and numbered in sequence;
        # RFP list items are long sentences that end in a period.
        section_match = _SECTION_RE.match(line)
        is_heading = (
            section_match is not None
            and int(section_match.group("number")) == expected_section
            and len(line) <= 80
            and not line.rstrip().endswith(".")
        )
        if is_heading:
            assert section_match is not None
            if current is not None:
                sections.append(_finalise_section(current))
            current = {
                "number": int(section_match.group("number")),
                "title": section_match.group("title").strip(),
                "paragraphs": [],
            }
            expected_section += 1
            index += 1
            continue

        if current is not None:
            current["paragraphs"].append(line)
        elif title or header:
            unparsed.append(line)
        else:
            # Cover-page lines before the first brief title.
            unparsed.append(line)
        index += 1

    if current is not None:
        sections.append(_finalise_section(current))

    requirements = _extract_requirements(sections)
    return CampaignBriefDocument(
        source_file=source_file,
        brief_number=brief_number,
        title=title,
        header=header,
        sections=tuple(sections),
        requirements=requirements,
        unparsed=tuple(unparsed),
        paragraph_count=total,
    )


def _finalise_section(raw: Mapping[str, Any]) -> BriefSection:
    labelled: dict[str, str] = {}
    for paragraph in raw["paragraphs"]:
        match = _LABELLED_RE.match(paragraph)
        if match:
            labelled[match.group("label").strip()] = match.group("text").strip()
    return BriefSection(
        number=raw["number"],
        title=raw["title"],
        paragraphs=tuple(raw["paragraphs"]),
        labelled=labelled,
    )


def _extract_requirements(sections: Sequence[BriefSection]) -> tuple[str, ...]:
    """The numbered deliverables the brief demands of the sales response.

    Title matching alone is not enough: the location section is also called
    "... Location **Requirements**", so we score candidates and keep the one that
    actually contains a numbered list.
    """
    best: tuple[int, int, tuple[str, ...]] = (0, 0, ())
    for section in sections:
        title = section.title.lower()
        if not any(word in title for word in ("rfp", "requirement", "deliverable", "response")):
            continue
        items = tuple(
            match.group("text").strip()
            for paragraph in section.paragraphs
            if (match := _LIST_ITEM_RE.match(paragraph))
        )
        if not items:
            continue
        score = (2 if "rfp" in title else 1, len(items), items)
        if score[:2] > best[:2]:
            best = score
    return best[2]


# ------------------------------------------------------------------ normalisation
def _parse_money(text: str) -> float | None:
    match = _MONEY_RE.search(text or "")
    if not match:
        return None
    amount = float(match.group(1).replace(",", ""))
    suffix = (match.group(2) or "").lower()
    if suffix in {"k", "thousand"}:
        amount *= 1_000
    elif suffix in {"m", "million"}:
        amount *= 1_000_000
    return amount


def _first_int(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text or "")
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class DerivedBriefFields:
    """Normalised values, each traceable to the paragraph it came from.

    This is the seed of the Phase 4 ``CampaignBrief`` domain type. It carries only
    what the documents literally state; resolution to zones, screen types and POI
    types happens later (Step 4.2) against the Phase 1 data dictionary.
    """

    source_file: str
    brief_number: int | None
    campaign_title: str
    company: str = ""
    industry_vertical: str = ""
    objective: str = ""
    target_audience: str = ""
    budget_text: str = ""
    budget_amount: float | None = None
    duration_text: str = ""
    duration_days: int | None = None
    age_min: int | None = None
    age_max: int | None = None
    slots_requested: int | None = None
    seconds_per_minute: int | None = None
    exclusions: tuple[str, ...] = ()
    location_requirements: tuple[str, ...] = ()
    rfp_requirements: tuple[str, ...] = ()
    #: Statements that carry a constraint we cannot yet bind to a data entity.
    unresolved_requirements: tuple[str, ...] = ()

    def as_row(self) -> Mapping[str, Any]:
        return {
            "brief": self.brief_number,
            "source_file": self.source_file,
            "campaign": self.campaign_title,
            "company": self.company,
            "industry_vertical": self.industry_vertical,
            "objective": self.objective,
            "target_audience": self.target_audience,
            "budget_amount": self.budget_amount,
            "duration_days": self.duration_days,
            "age_min": self.age_min,
            "age_max": self.age_max,
            "slots_requested": self.slots_requested,
            "seconds_per_minute": self.seconds_per_minute,
            "n_location_requirements": len(self.location_requirements),
            "n_exclusions": len(self.exclusions),
            "n_rfp_requirements": len(self.rfp_requirements),
            "n_unresolved": len(self.unresolved_requirements),
        }


def derive_fields(document: CampaignBriefDocument) -> DerivedBriefFields:
    header = document.header
    labelled = document.all_labelled
    audience_text = header.get("Target Audience", "")
    persona = document.section("audience")
    audience_context = " ".join(
        filter(None, [audience_text, persona.text if persona else ""])
    )

    ages = _AGES_RE.search(audience_context)
    slot_section = document.section("slot") or document.section("visual")
    slot_text = slot_section.text if slot_section else ""

    exclusions = tuple(
        text
        for label, text in labelled.items()
        if any(hint in label.lower() for hint in CONSTRAINT_LABEL_HINTS)
    )
    location_section = document.section("screen selection") or document.section("location")
    location_requirements = tuple(
        f"{label}: {text}"
        for label, text in (location_section.labelled.items() if location_section else ())
        if not any(hint in label.lower() for hint in CONSTRAINT_LABEL_HINTS)
    )

    return DerivedBriefFields(
        source_file=document.source_file,
        brief_number=document.brief_number,
        campaign_title=document.title,
        company=header.get("Company Name", ""),
        industry_vertical=header.get("Industry Vertical", ""),
        objective=header.get("Campaign Objective", ""),
        target_audience=audience_text,
        budget_text=header.get("Campaign Budget", ""),
        budget_amount=_parse_money(header.get("Campaign Budget", "")),
        duration_text=header.get("Campaign Duration", ""),
        duration_days=_first_int(_DURATION_RE, header.get("Campaign Duration", "")),
        age_min=int(ages.group(1)) if ages else None,
        age_max=int(ages.group(2)) if ages else None,
        slots_requested=_first_int(_SLOTS_RE, slot_text),
        seconds_per_minute=_first_int(_SECONDS_RE, slot_text),
        exclusions=exclusions,
        location_requirements=location_requirements,
        rfp_requirements=tuple(document.requirements),
        unresolved_requirements=_unresolved(document),
    )


#: Phrases that name a capability the raw data does not directly provide. Each hit
#: becomes a required capability for Phases 3–7, not a demo-time surprise.
CAPABILITY_PROBES: Mapping[str, str] = {
    "walking": "walking-radius / distance constraint — needs the POI proximity rule (Step 1.6)",
    "radius": "explicit radius constraint — needs the POI proximity rule (Step 1.6)",
    "weekend": "weekend vs weekday weighting — needs day-type split in the daypart curve",
    "weekday": "weekday weighting — needs day-type split in the daypart curve",
    "dwell": "dwell-time reasoning — needs interior/exterior and location-type exposure model",
    "16:9": "creative aspect-ratio restriction — needs a screen format attribute",
    "aspect": "creative aspect-ratio restriction — needs a screen format attribute",
    "digital screens only": "format restriction to digital inventory — needs a screen format attribute",
    "qr": "QR / response-mechanic tracking — affects objective fit, not inventory",
    "frequency": "effective-frequency requirement — needs the reach/frequency split (Step 3.5)",
    "premium": "premium-tier positioning — maps to market_tier and price band",
    "exclude": "hard exclusion — must be enforced in the Phase 5 eligibility filter",
}


def _unresolved(document: CampaignBriefDocument) -> tuple[str, ...]:
    text_blocks = [section.text for section in document.sections]
    haystack = " ".join(text_blocks).lower()
    return tuple(
        dict.fromkeys(
            description for probe, description in CAPABILITY_PROBES.items() if probe in haystack
        )
    )


# --------------------------------------------------------------------- collection
def load_briefs(directory: Path | str | None = None) -> tuple[CampaignBriefDocument, ...]:
    """Parse every `.docx` in the campaigns directory, in file-name order."""
    directory = Path(directory) if directory is not None else ProjectPaths().campaigns
    documents = []
    for path in sorted(directory.glob("*.docx")):
        if path.name.startswith("~$"):  # Word lock file
            continue
        documents.append(parse_brief(extract_docx_paragraphs(path), source_file=path.name))
    return tuple(documents)


def briefs_frame(documents: Iterable[CampaignBriefDocument]) -> pd.DataFrame:
    return pd.DataFrame([derive_fields(document).as_row() for document in documents])


def requirements_frame(documents: Iterable[CampaignBriefDocument]) -> pd.DataFrame:
    """One row per stated RFP deliverable — the Phase 8 acceptance checklist."""
    rows = []
    for document in documents:
        for position, requirement in enumerate(document.requirements, start=1):
            rows.append(
                {
                    "brief": document.brief_number,
                    "source_file": document.source_file,
                    "campaign": document.title,
                    "requirement_no": position,
                    "requirement": requirement,
                }
            )
    return pd.DataFrame(rows)


def coverage_frame(documents: Iterable[CampaignBriefDocument]) -> pd.DataFrame:
    """Which header fields each brief actually states — the evidence for Step 1.8."""
    rows = []
    for document in documents:
        row: dict[str, Any] = {
            "brief": document.brief_number,
            "source_file": document.source_file,
            "sections": len(document.sections),
            "unparsed_paragraphs": len(document.unparsed),
        }
        row.update({label: label in document.header for label in HEADER_LABELS})
        rows.append(row)
    return pd.DataFrame(rows)
