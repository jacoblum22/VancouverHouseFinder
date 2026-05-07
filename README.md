# Vancouver House Finder (VHF)

Scrapes Vancouver rental listings matching your criteria from multiple sites, deduplicates cross-posts, calculates transit time to UBC, and emails you when listings are newly found or drop out of the filtered snapshot.

## What it does

- Scrapes **Craigslist**, **PadMapper**, **Rentals.ca**, and **Zumper** on every run
- Filters to listings matching: max $6,600/mo, 4+ bedrooms, Vancouver, available before Sept 1 2026
- Deduplicates listings that appear across multiple sites
- Enriches listings with Google Maps transit time to UBC (6133 University Blvd)
- Exports `data/exports/results.html` and `data/exports/results.csv`
- Runs automatically every 12 hours via GitHub Actions
- Sends one aggregated email per run when new or removed listings are detected

## Repo layout

```
src/vhf/           Application code (scrapers, pipeline, notify, export, CLI)
data/exports/      results.html + results.csv — updated each run, committed to repo
data/processed/    transit_cache.json — committed; listings.jsonl — gitignored
data/state/        last_seen.json — tracks known listing IDs for new-listing detection
data/raw/          Raw fetched pages — gitignored (ephemeral)
.github/workflows/ scheduled_scrape.yml — GitHub Actions workflow
```

## Running locally

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/VancouverHouseFinder.git
cd VancouverHouseFinder
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -e .
```

### 2. Set environment variables

```bash
# Required for transit time calculation:
export GOOGLE_MAPS_API_KEY="your_key_here"

# Required for email notifications (see Email Setup below):
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USERNAME="you@gmail.com"
export SMTP_PASSWORD="your_app_password"
export EMAIL_FROM="you@gmail.com"
export EMAIL_TO="you@gmail.com,friend@example.com"
```

On Windows PowerShell:
```powershell
$env:GOOGLE_MAPS_API_KEY = "your_key_here"
```

### 3. Run the scrape pipeline

```bash
vhf
```

This fetches all sites, filters, deduplicates, enriches transit times, and writes exports.

### 4. Run notifications manually

```bash
python -m vhf.notify
```

Compares current listings against `data/state/last_seen.json`. Sends email if new or removed listings are detected. Updates the state file.

`EMAIL_TO` supports multiple recipients separated by comma, semicolon, or newline.

## Email Setup (Gmail recommended)

1. Enable **2-Step Verification** on your Google Account.
2. Go to **Google Account → Security → App Passwords**.
3. Create a new App Password (name it "VHF").
4. Use the 16-character password as `SMTP_PASSWORD`.
5. Set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`.

Any other SMTP provider (Outlook, custom) works the same way — just swap the host/port/credentials.

## GitHub Actions Setup

The workflow at `.github/workflows/scheduled_scrape.yml` runs every 12 hours automatically (at 00:00 and 12:00 UTC, subject to GitHub runner scheduling).

### Required GitHub Secrets

Go to **Repository → Settings → Secrets and variables → Actions → New repository secret** and add each of these:

| Secret name         | Value                                      |
|---------------------|--------------------------------------------|
| `GOOGLE_MAPS_API_KEY` | Your Google Maps API key                 |
| `SMTP_HOST`         | `smtp.gmail.com` (or your provider)        |
| `SMTP_PORT`         | `587`                                      |
| `SMTP_USERNAME`     | Your email address                         |
| `SMTP_PASSWORD`     | Your Gmail App Password (16 chars)         |
| `EMAIL_FROM`        | Same as SMTP_USERNAME                      |
| `EMAIL_TO`          | Where to send alerts (can be same address) |

### First run behaviour

The first automated run seeds `data/state/last_seen.json` with all current listings and does **not** send an email (to avoid a big blast of existing listings). From that point forward, genuinely new or removed listings trigger a notification.

### Manual trigger

You can trigger a run any time from:
**GitHub → Actions tab → Scheduled Scrape → Run workflow**

### Viewing results

After each run the workflow commits updated `data/exports/results.html` and `data/exports/results.csv` back to the repo. Open `data/exports/results.html` directly in a browser.

## Criteria customisation

CLI options:

```bash
vhf --max-rent-cad 5500 --min-bedrooms 3 --available-before 2026-08-01
```

## Dependencies

- Python 3.11+
- `httpx`, `beautifulsoup4`, `lxml` — HTTP + HTML scraping
- `pydantic` — data models
- `curl-cffi` — TLS fingerprinting for Rentals.ca (bypasses Cloudflare)
- `pyjwt` — JWT auth for Rentals.ca
- `rapidfuzz` — fuzzy string matching for address deduplication
- `typer`, `rich` — CLI + terminal output
- `tzdata` — timezone database (required on Windows/Linux CI)
