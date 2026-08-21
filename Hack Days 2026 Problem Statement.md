# Hack Days 2026: The AgentIQ Frontier

**AUGUST 2026**

© 2025 Accordion — CONFIDENTIAL

---

## 1. The Business

### Urban Media

A digital out-of-home (DOOH) advertising company operating **~11K digital screens** across urban transit infrastructure in **three major cities**, deployed on:

- Buses
- Metro rail coaches
- Bus stops
- Metro platforms
- Metro stations

Each screen runs **rotating digital ad slots** that advertisers lease on a **per-slot, per-day basis** — from a single rotation to full-screen exclusivity.

Company scale:

- **500+ advertisers** served
- **50-person sales team**
- **~$200M in annual revenue**

### Current Challenges

**The status quo scenario:** Today, a sales rep gets an inquiry — an advertiser wants a 30-day campaign targeting commuters in the eastern metro corridor, budget ~$50K. The rep opens a spreadsheet, eyeballs available screens, invents a price, and sends a proposal. No one knows if the price is right, if those screens fit the audience, or if three other advertisers are competing for the same inventory that week.

Three named challenges:

1. **Inconsistent & Unguarded Pricing**
   - Same screen quoted at different prices by different reps
   - No floor, no cap, no guardrails

2. **No Demand Optimization**
   - Pricing ignores demand, occupancy, and seasonality
   - Underselling high-value inventory, oversitting low-demand inventory

3. **Blind Inventory Matching**
   - No data-driven way to match advertisers to the right screens based on audience, budget, or goals

---

## 2. The Goal: Sense · Plan · Adapt

**Mission statement:** Build an AI-powered intelligence platform for the sales team that turns a messy campaign brief into:

- The best-fit screens
- The right slots
- Optimal pricing
- A credible projected audience reach
- Plus a clear reasoning for the choices

### SENSE — Understand the Landscape

- **Inventory:** screens, slots, locations, routes
- **Context:** POIs, audience profiles by time of day
- **History:** leads, negotiations, bookings, occupancy

### PLAN — Score, Price & Optimize

- Score screens against campaign briefs (AI + rules)
- Predict footfall, demand, and determine price ranges
- Optimize screen-slot allocation within constraints

### ADAPT — Act, Learn & Adjust

- Agent orchestrates end-to-end flow dynamically
- Adjusts to real-time demand shifts and availability
- Learns from sales rep's notes and feedback

### Solution Flow (5 stages)

1. **Campaign Brief Intake**
2. **Campaign Relevance Scoring**
3. **Demand Forecasting & Pricing**
4. **Optimization & Allocation**
5. **Agentic Recommendation**

---

## 3. Core Functionalities (Deliverables)

Six deliverables. Each produces a concrete output that plugs into the solution flow.

### D1 — Audience Profile Engine

- **Description:** Takes screen locations, POI data, route/ridership data, and screen mount position to produce audience profiles for every screen — *who is near this screen, when, and why*. Leverage AI to infer profiles and apply proximity rules to filter noise.
- **Techniques:** AI Agent, Logical Rules

### D2 — Campaign↔Screen Relevance Scorer

- **Description:** Takes a campaign brief and the audience profiles to produce a ranked list of screens with explainable relevance scores reflecting audience-campaign affinity — *why this screen fits this campaign*.
- **Techniques:** AI Agent, Logical Rules

### D3 — Demand Forecasting & Pricing Model

- **Description:** Uses historical bookings, lead pipeline signals, demand patterns, current availability, expected footfall, and human inputs to determine a **price range (floor / target / cap)** and a **recommended optimal price per screen-slot in real-time**.
- **Techniques:** AI Agent, Logical Rules, Forecasting

### D4 — Impressions Optimizer

- **Description:** Uses relevance scores, pricing, slot availability, and budget constraints to produce the optimal **multi-location, multi-slot package** that maximizes reach / impressions.
- **Techniques:** Optimization Model

### D5 — Agentic Orchestration

- **Description:** Takes a raw campaign brief from the sales rep, orchestrates agents, and delivers a complete recommendation — screens, slots, pricing, projected impressions, and explanatory notes on why these choices were made.
- **Techniques:** Agent Orchestration

### D6 — Unified Platform

- **Description:** An interface for sales reps to interact with, to:
  - Upload relevant campaign documents
  - Provide additional details
  - Give feedback to agents
  - Generate output
- **Techniques:** App development, UI/UX design

---

## 4. Dataset Overview: Five Layers

**Fourteen tables, five layers** — all the data Urban Media has to build audience profiles, relevance scores, and pricing is here.

| # | Layer | Tables | Type of info available |
|---|-------|--------|------------------------|
| 1 | **Geography** | `cities`, `zone_demographics`, `locations` | City-level market tiers, zone demographics (income, age, density), and the physical catalog of bus stops and metro stations. |
| 2 | **Network** | `route_stops`, `vehicles`, `route_schedules`, `ridership_actuals` | Route topology and stop sequences, vehicle-to-route assignments, scheduled trips, and historical actual ridership. |
| 3 | **Inventory** | `screens` | The physical and vehicle-mounted screen catalog, including mount position and screen size. |
| 4 | **Context** | `points_of_interest`, `events` | Points of interest (type, footfall, proximity, side of road) and scheduled events (attendance, impact radius). |
| 5 | **Commercial** | `client_facts`, `dim_slot`, `bookings`, `lost_leads` | Advertiser profiles, time-block/slot definitions, historical booking transactions, and lost pipeline leads. |

---

## 5. A Few Things Worth Thinking Through

> Not requirements — just the corners of the problem that tend to get overlooked as teams build.

| Nuance | The subtlety |
|--------|--------------|
| **Scaling beyond these cities** | Urban Media could expand to other locations and cities in the near future, with very different characteristics and demographies. |
| **Impressions are estimated** | Ads with a higher number of slots per minute have higher chances of being noticed than a quick 10s ad. Your recommendation should account for the **non-linearity in impressions vs boards vs pricing**. |
| **Demand is inferred** | Build demand intensity from past leads, recent events in the areas, etc. |
| **Explainability matters** | A ranked list without reasoning isn't enough. Each recommendation should be able to say **why** — signals, POI fit, price rationale. |
| **Some inventory has no history** | Some screens might have sparse or zero historical data. Think about how your system behaves when signals are absent. |
| **Boards on the same route share an audience** | Two boards on the same route reach the same commuters. Treating them as independent reach is a modeling error worth handling. |
| **A bundle isn't three independent decisions** | A bus + metro + station package should be reasoned about as **one deal** — joint pricing and allocation, not three separate choices. |
| **Not all demand signals age equally** | Older unconverted leads are weaker signals than recent ones. The **lead expiry date** is in the data — consider how you weight it. |
| **All other nuances you can think of…** | …………………………………………………………………………………… |

---

## 6. What Every Team Submits

### 1. Codebase & Environment

- Full project source as a **`.zip`**
- With a **dependency manifest**:
  - Python: `venv` / `requirements.txt`
  - Node.js: lockfile
- Includes a **`README`** with run instructions
- Includes a **`CLAUDE.md`** for AI coding context

### 2. System Design — C4 Model

- **Context**, **Container**, and **Component** diagrams
- Delivered as a design doc, deck, HTML, or chart (PDF or image export)

### 3. Demo Video

- A **5–10 minute** screen recording
- Walking through the app's core features and capabilities in action

---

## 7. How It'll Be Assessed

| # | Criterion | What it measures |
|---|-----------|------------------|
| 1 | **AI & Agentic Architecture** | Soundness of how ML, OR, and agentic orchestration are combined into one coherent system. |
| 2 | **Feature Depth & Purpose Fit** | Breadth and depth of purpose-driven features and capabilities to enhance the outcomes and experience. |
| 3 | **Recommendation Quality & Personalization** | Degree to which outputs are tailored and audience-aware across campaign contexts. |
| 4 | **Explainability & Trust** | Clarity with which the system justifies its pricing and inventory recommendations. |
| 5 | **Performance & Scalability** | Ability to scale with inventory volume, balanced against latency vs. recommendation quality. |
| 6 | **Code Quality & Engineering Rigor** | Structure, readability, modularity, and reproducibility of the codebase. |
| 7 | **Demo Impact & Communication** | Clarity of the walkthrough in conveying the problem solved and value delivered. |

---

## 8. Time Blocks & Rotation Slots

**How one day of screen inventory is structured in `dim_slot` — and how a booking claims it.**

> Each rotation slot isn't a chunk of the 4-hour block — **all 6 play on a fast repeating loop (seconds each) for the entire block.**

### The Six Time Blocks

| `time_block_id` | Time Window | Name |
|-----------------|-------------|------|
| 1 | 00:00–04:00 | Night |
| 2 | 04:00–08:00 | Morning |
| 3 | 08:00–12:00 | Midday |
| 4 | 12:00–16:00 | Afternoon |
| 5 | 16:00–20:00 | Evening |
| 6 | 20:00–24:00 | Night |

### The Six Rotation Slots

- Slots are numbered **Slot 1 … Slot 6** within each time block.
- **Inside one time_block:** Slot 1 → 2 → 3 → 4 → 5 → 6, then **loops back to Slot 1**.
- Slots cycle in **seconds, not hours** — the same 6 ads loop continuously for the full 4-hour block (**hundreds of repeats per block**).

### How Bookings Claim Slots (example from the diagram)

- **Booking A**
  - `slots_booked_per_day = 3`
  - `rotation_type = partial_rotation`
  - Occupies Slot 1 in the Evening block (16:00–20:00), plus Slots 2 and 3 in the Afternoon block (12:00–16:00)
- **Booking B** (a different client)
  - `slots_booked_per_day = 1`
  - `rotation_type = single_rotation`
  - Occupies Slot 1 in the Morning block (04:00–08:00)

### Recurrence

- The same slots recur **every day** across the booking's date range.
- Day 1 (`start_date`) → Day 2 → Day 3 → ⋯ → Day N (`end_date`)

---

## Unleash Your Agents!

© 2025 Accordion — CONFIDENTIAL
