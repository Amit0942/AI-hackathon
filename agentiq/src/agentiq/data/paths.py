"""Project path resolution.

Every other module takes directories as arguments; this module only supplies the
defaults so that a notebook can be opened from anywhere in the tree and still
find the raw data. Nothing here hardcodes a city, a table or a file name.
"""

from __future__ import annotations

from pathlib import Path

#: A directory containing this marker (relative path) is treated as the project root.
ROOT_MARKERS = ("data/raw/Urban Media Datasets", "data/raw/Campaigns")


def find_project_root(start: Path | str | None = None) -> Path:
    """Walk upwards from *start* until a directory holding the root markers is found."""
    here = Path(start).resolve() if start is not None else Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if all((candidate / marker).is_dir() for marker in ROOT_MARKERS):
            return candidate
    raise FileNotFoundError(
        f"Could not locate the project root above {here}. "
        f"Expected a directory containing {ROOT_MARKERS!r}."
    )


class ProjectPaths:
    """Resolved locations of the inputs and generated outputs."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root).resolve() if root is not None else find_project_root()

    @property
    def raw_data(self) -> Path:
        return self.root / "data" / "raw" / "Urban Media Datasets"

    @property
    def campaigns(self) -> Path:
        return self.root / "data" / "raw" / "Campaigns"

    @property
    def artifacts(self) -> Path:
        """Precomputed parquet/JSON derived from raw data. Safe to delete and rebuild."""
        return self.root / "data" / "artifacts"

    @property
    def cache(self) -> Path:
        """Parquet mirrors of the large CSVs, for fast reloads."""
        return self.artifacts / "cache"

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def docs(self) -> Path:
        return self.root / "docs"

    @property
    def src(self) -> Path:
        return self.root / "src"

    def ensure_dirs(self) -> "ProjectPaths":
        for directory in (self.artifacts, self.cache, self.docs):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ProjectPaths(root={self.root!s})"
