## Vancouver House Finder — Project Plan

### Goal
Build a tool that **collects Vancouver rental listings meeting your criteria**, **deduplicates cross-posts**, and **displays results in an organized way**.

### Current criteria (initial filter)
- **Location**: Vancouver, BC
- **Max rent**: **<$6,600**
- **Availability**: **available before Sept 1**
- **Bedrooms**: **4+**

### Constraints / reality check (important)
- Many rental sites disallow scraping or aggressively block bots; some provide official feeds/APIs, others require careful rate-limiting and/or manual export.
- Captchas, dynamic rendering, and frequent HTML changes are common. Plan for breakage and maintenance.
- Deduping will never be perfect; aim for “very good” and allow manual overrides.

---

## MVP (Minimum Viable Product)

### MVP outcomes (what “done” means)
- You can run one command that:
  - pulls listings from a small set of sources,
  - filters to your criteria,
  - **deduplicates** likely cross-posts,
  - saves results locally,
  - shows a clean view (table) of what’s currently found.

### MVP scope (keep it small and reliable)
- **Sources**: start with **1–2** sites that are relatively stable and accessible.
- **Run mode**: manual run (no scheduler yet).
- **Display**: local, simple (CLI table or a lightweight local webpage).
- **Storage**: local database/file (enables “what’s new since last run?” later).

### MVP architecture (suggested)
- **Ingestion (per site)**:
  - A “fetch listings” step (download page(s) or use an API if available).
  - A “parse listings” step (extract title, price, address/area, bedrooms, availability, URL, images if desired).
- **Normalization**:
  - Convert each raw listing into a common schema (same field names/types across sites).
- **Filtering**:
  - Apply your criteria (max price, bedrooms, availability cutoff, in-Vancouver).
- **Deduplication**:
  - Generate a stable “fingerprint” for each listing and cluster likely duplicates.
  - Prefer exact matches first; fall back to fuzzy matches.
- **Persistence**:
  - Store normalized listings + dedupe cluster id + first_seen/last_seen timestamps.
- **Presentation**:
  - Show a sorted table: price, beds, neighborhood/address (if available), availability, source, link.

### Data model (MVP schema sketch)
Each listing record should include:
- **id**: internal unique id
- **source**: site name
- **source_listing_id**: if available (stable id from the site)
- **url**
- **title**
- **price**: number (CAD/month) + raw text
- **bedrooms**: number (support “4+” as 4 with a flag if needed)
- **bathrooms**: optional
- **sqft**: optional
- **availability_date**: optional normalized date + raw text
- **address_text**: raw address string (often partial)
- **neighborhood**: optional
- **lat/lng**: optional (future, for mapping)
- **description**: optional (useful for dedupe)
- **images**: optional list
- **first_seen_at**, **last_seen_at**

### Deduplication strategy (MVP)
Start simple, then refine:
- **Tier 1 (exact)**:
  - Same `source_listing_id` within a source.
  - Same canonicalized URL (strip tracking params).
- **Tier 2 (near-exact)**:
  - Same (price + bedrooms + normalized address/neighborhood).
- **Tier 3 (fuzzy)**:
  - Similar title/description + similar location text + similar price (within a small tolerance).

Practical fingerprint idea:
- `fingerprint = hash(normalized_address_or_neighborhood + bedrooms + normalized_price_bucket)`
- Keep the raw candidates and allow manual “merge/unmerge” later if needed.

### MVP display ideas (pick one later)
- **CLI**:
  - Print a table and optionally write `results.csv`.
- **Local web UI**:
  - Small local server showing a searchable/sortable table.

---

## Extensions (after MVP)

### 1) Automatic checks every ~30 minutes
- Add a scheduler:
  - OS-level (Task Scheduler / cron) running the command every 30 minutes, OR
  - In-app scheduler loop (more moving parts, but self-contained).
- Ensure robust rate limiting and caching per source.

### 2) Notifications on new matches
Once persistence exists, “new” is easy:
- Detect **new listings** or **price drops** since last run.
- Notify via:
  - Email (SMTP or email API)
  - SMS (e.g. Twilio)
  - Push/Discord/Slack webhook
  - Desktop notification

### 3) Map of Vancouver with pins
Prerequisite: obtain `lat/lng` per listing.
- **Geocoding options**:
  - Use a geocoding API on address text (may be partial → lower accuracy).
  - Use neighborhood centroids when full address unavailable.
- **Map UI**:
  - Interactive map with pins + a sidebar list.
  - Cluster pins, filter by price/beds/availability.

### 4) Transit time to UBC (ranking/filtering)
Goal: “How long to UBC by transit at typical commute time?”
- Use a transit routing API:
  - Compute travel time to UBC from listing coordinates.
  - Cache results (don’t re-query unchanged listings).
  - Add a “commute_time_to_ubc” field and allow sorting/filtering.
Potential enhancements:
- Peak vs off-peak time bands
- Reliability metrics (variance, transfers)

### 5) Better matching + quality scoring
- “Listing quality score” based on:
  - completeness (beds/baths/address present),
  - recency,
  - price per bedroom,
  - proximity/transit time to UBC,
  - keywords you care about (e.g. “pet friendly”, “parking”).

### 6) Better dedupe + entity resolution
- Use embedding similarity on titles/descriptions (optional).
- Human-in-the-loop merges:
  - UI to approve suggested duplicates.

### 7) Deployment / always-on
- Run as a small service:
  - Local machine + Task Scheduler
  - VPS + systemd + monitoring
- Add observability:
  - logs per source,
  - scrape success/failure counts,
  - alerts when a scraper breaks.

---

## Risks & mitigations
- **Site blocks / ToS**: prefer official APIs/feeds when possible; throttle requests; cache; avoid unnecessary crawling.
- **Parser breakage**: keep per-site scrapers isolated; add lightweight tests with saved HTML fixtures.
- **Bad/partial addresses**: store raw text; geocode best-effort; fall back to neighborhood-level pins.
- **Duplicate handling errors**: keep clusters transparent; allow manual overrides.

---

## Suggested next step (when you’re ready to implement)
Decide:
- Which **1–2 target sites** to start with for the MVP.
- Whether you prefer **CLI-first** or **local web UI** for the initial display.

