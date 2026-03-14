# Nifty Options Selling Dashboard

A complete, end-to-end **weekly Nifty options selling dashboard** for the Indian stock market (NSE). The system automates strike selection, tracks live P&L, monitors risk in real-time, and suggests hedging trades when a position is threatened.

**Tech stack:** Python (FastAPI) backend + Google Sheets frontend via Google Apps Script.

```
                       ┌──────────────────────────┐
                       │      Google Sheet         │
                       │  (6 tabs — your UI)       │
                       │                           │
                       │  Dashboard                │
                       │  Open Positions           │
                       │  Risk Monitor             │
                       │  Trade History             │
                       │  Option Chain Data         │
                       │  Settings & Config         │
                       └────────────┬───────────────┘
                                    │ Google Apps Script
                                    │ calls backend API
                                    ▼
                       ┌──────────────────────────┐
                       │   FastAPI Backend         │
                       │   (Python, port 8000)     │
                       │                           │
                       │   NSE Scraper             │
                       │   Strike Engine           │
                       │   Risk Engine             │
                       │   Hedge Calculator        │
                       │   Trade Manager           │
                       │   Sheets API Writer       │
                       └────────────┬───────────────┘
                                    │ httpx
                                    ▼
                       ┌──────────────────────────┐
                       │   NSE India APIs          │
                       │   (Option Chain, Indices, │
                       │    India VIX)             │
                       └──────────────────────────┘
```

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Clone & Install](#2-clone--install)
3. [Environment Configuration](#3-environment-configuration)
4. [Google Cloud Setup (Sheets API)](#4-google-cloud-setup-sheets-api)
5. [Create Your Google Sheet](#5-create-your-google-sheet)
6. [Run the Backend Server](#6-run-the-backend-server)
7. [Verify the Backend is Working](#7-verify-the-backend-is-working)
8. [Set Up Google Apps Script (Sheet Frontend)](#8-set-up-google-apps-script-sheet-frontend)
9. [First Run — End-to-End Walkthrough](#9-first-run--end-to-end-walkthrough)
10. [Run Tests](#10-run-tests)
11. [Deploy to Production](#11-deploy-to-production)
12. [API Reference](#12-api-reference)
13. [Configuration Reference](#13-configuration-reference)
14. [Project Structure](#14-project-structure)
15. [How Each Feature Works](#15-how-each-feature-works)
16. [Troubleshooting](#16-troubleshooting)
17. [Disclaimer](#17-disclaimer)

---

## 1. Prerequisites

| Requirement | Version | Why |
|---|---|---|
| **Python** | 3.10 or higher | Backend runtime |
| **pip** | Latest | Python package manager |
| **Google account** | Any | For Google Sheets + Apps Script |
| **Google Cloud project** | Free tier is enough | For Sheets API credentials |
| **Git** | Any | To clone the repo |

Optional for production deployment:
- Docker (for containerized deployment)
- Google Cloud CLI (`gcloud`) or Railway CLI

---

## 2. Clone & Install

```bash
# Clone the repository
git clone <your-repo-url> Market_Study
cd Market_Study

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate        # Linux/Mac
# .venv\Scripts\activate         # Windows

# Install all dependencies
pip install -r requirements.txt
```

**What gets installed:**

| Package | Purpose |
|---|---|
| `fastapi` + `uvicorn` | Web server and API framework |
| `httpx` | Async HTTP client for NSE scraping |
| `gspread` + `google-api-python-client` | Google Sheets API integration |
| `google-auth-oauthlib` | Google service account authentication |
| `numpy` + `scipy` | Black-Scholes Greeks calculations |
| `pandas` | Data handling |
| `apscheduler` | Automatic data refresh scheduler |
| `pydantic` + `pydantic-settings` | Configuration management |
| `pytz` | IST timezone handling |

---

## 3. Environment Configuration

```bash
# Copy the example environment file
cp .env.example .env
```

Edit `.env` with your values:

```bash
# REQUIRED — Your Google Sheet ID (from the sheet URL)
# URL format: https://docs.google.com/spreadsheets/d/THIS_IS_YOUR_SHEET_ID/edit
NIFTY_GOOGLE_SHEETS_ID=your_google_sheet_id_here

# REQUIRED — Path to your Google service account credentials JSON file
NIFTY_GOOGLE_CREDENTIALS_FILE=credentials.json

# OPTIONAL — Override defaults if needed
# NIFTY_LOT_SIZE=65
# NIFTY_STRIKE_OFFSET=200
# NIFTY_AUTO_REFRESH_INTERVAL=3
# NIFTY_RISK_FREE_RATE=0.065
```

> You will fill in the actual values after completing steps 4 and 5 below.

---

## 4. Google Cloud Setup (Sheets API)

This step creates the credentials that let the Python backend write to your Google Sheet.

### Step 4a — Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project dropdown at the top → **New Project**
3. Name it `nifty-dashboard` (or anything you like) → **Create**
4. Select the new project from the dropdown

### Step 4b — Enable APIs

1. Go to **APIs & Services → Library**
2. Search for and enable **both** of these:
   - **Google Sheets API** — click → **Enable**
   - **Google Drive API** — click → **Enable**

### Step 4c — Create a Service Account

1. Go to **APIs & Services → Credentials**
2. Click **+ CREATE CREDENTIALS → Service Account**
3. Name: `nifty-dashboard-bot` → **Create and Continue**
4. Role: **Editor** → **Continue** → **Done**

### Step 4d — Download the Key File

1. Click on the service account you just created
2. Go to the **Keys** tab
3. Click **Add Key → Create New Key → JSON → Create**
4. A `*.json` file downloads automatically
5. **Rename it to `credentials.json`** and place it in the project root:

```bash
mv ~/Downloads/nifty-dashboard-bot-*.json ./credentials.json
```

### Step 4e — Note the Service Account Email

The service account has an email like:
```
nifty-dashboard-bot@nifty-dashboard.iam.gserviceaccount.com
```
You will need this in step 5.

---

## 5. Create Your Google Sheet

### Step 5a — Create a New Sheet

1. Go to [Google Sheets](https://sheets.google.com)
2. Create a **Blank spreadsheet**
3. Name it: `Nifty Options Dashboard`

### Step 5b — Get the Sheet ID

Copy the Sheet ID from the URL:
```
https://docs.google.com/spreadsheets/d/1aBcDeFgHiJkLmNoPqRsTuVwXyZ/edit
                                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                       This is your Sheet ID
```

Paste it into your `.env` file:
```
NIFTY_GOOGLE_SHEETS_ID=1aBcDeFgHiJkLmNoPqRsTuVwXyZ
```

### Step 5c — Share the Sheet with the Service Account

1. In your Google Sheet, click **Share** (top right)
2. Paste the service account email from step 4e
3. Set permission to **Editor**
4. Uncheck "Notify people" → **Share**

> This allows the Python backend to read/write to your sheet.

---

## 6. Run the Backend Server

```bash
# Make sure you're in the project directory with .venv activated
cd Market_Study

# Start the server
python run.py
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     NSE session initialized, cookies acquired.
INFO:     Scheduler started: refresh every 3 minutes
INFO:     Data refreshed: Nifty=23151, VIX=14.2, Suggestion: 23800 CE / 22400 PE
```

The server is now:
- Serving the REST API at `http://localhost:8000`
- Scraping NSE data every 3 minutes during market hours
- Calculating strike suggestions, risk, and hedges automatically

> **During non-market hours** (after 3:30 PM IST or weekends), the initial scrape will still run once, but auto-refresh pauses. You can always trigger a manual refresh.

---

## 7. Verify the Backend is Working

Open another terminal and run these checks:

```bash
# Health check
curl http://localhost:8000/api/health

# Market data
curl http://localhost:8000/api/market

# Strike suggestion
curl http://localhost:8000/api/suggestion

# Interactive API docs (open in browser)
# http://localhost:8000/docs
```

Expected health check response:
```json
{
  "status": "healthy",
  "market_open": false,
  "last_refresh": "2026-03-13 22:15:00",
  "data_stale": false,
  "active_positions": 0
}
```

You can also open `http://localhost:8000/docs` in a browser to see the **interactive Swagger UI** with all 15 endpoints.

---

## 8. Set Up Google Apps Script (Sheet Frontend)

This connects your Google Sheet to the backend with a custom menu, buttons, and live formatting.

### Step 8a — Open Apps Script Editor

1. Open your Google Sheet
2. Go to **Extensions → Apps Script**
3. This opens the Apps Script editor in a new tab

### Step 8b — Create the Script Files

Delete the default `Code.gs` content, then create **3 files**:

**File 1 — `Code.gs`** (main coordinator)
1. Paste the contents of `apps_script/Code.gs` from this repo
2. **IMPORTANT:** Update the `BACKEND_URL` on line 8:

```javascript
const CONFIG = {
  BACKEND_URL: "http://your-server-ip:8000",  // ← Change this!
  // ...
};
```

- For local development: `http://localhost:8000` (only works if Google can reach your machine)
- For production: Your deployed server URL (e.g., `https://nifty-dashboard-xxxxx.run.app`)

> **Note:** Google Apps Script cannot reach `localhost` directly. For local development, use [ngrok](https://ngrok.com/) or a similar tunnel, or skip the Apps Script part and use the API directly until you deploy.

**File 2 — `DashboardWriter.gs`**
1. Click **+** next to Files → **Script**
2. Name it `DashboardWriter`
3. Paste the contents of `apps_script/DashboardWriter.gs`

**File 3 — `UIHelpers.gs`**
1. Click **+** next to Files → **Script**
2. Name it `UIHelpers`
3. Paste the contents of `apps_script/UIHelpers.gs`

### Step 8c — Update the Manifest

1. In the Apps Script editor, click the gear icon (**Project Settings**)
2. Check **Show "appsscript.json" manifest file in editor**
3. Click `appsscript.json` in the sidebar
4. Replace its contents with `apps_script/appsscript.json` from this repo

### Step 8d — Save and Authorize

1. Click the floppy disk icon (or Ctrl+S) to save all files
2. Go back to your Google Sheet and **reload the page**
3. After a few seconds, you should see a new menu: **Options Dashboard**
4. Click **Options Dashboard → Initialize Dashboard**
5. Google will ask for authorization — click through to allow:
   - "See, edit, create, and delete your spreadsheets"
   - "Connect to an external service"

### Step 8e — Verify the Menu Works

After authorization, you should see 6 sheet tabs created:
- Dashboard
- Open Positions
- Risk Monitor
- Trade History
- Option Chain Data
- Settings & Config

---

## 9. First Run — End-to-End Walkthrough

Here's the complete workflow from start to trade:

### 9a. Refresh Data

Click **Options Dashboard → Refresh Data** (or it refreshes automatically during market hours).

The Dashboard sheet will populate with:
- Market overview: Nifty spot, India VIX, change percentages
- Sectoral indices: Bank Nifty, Nifty IT, Pharma, FMCG, Metal, Auto
- Global markets: Dow, S&P 500, NASDAQ, FTSE, Nikkei, Hang Seng

### 9b. Review the Strike Suggestion

The Dashboard shows a trade suggestion box:

```
TRADE SUGGESTION
Expiry: 17-Mar-2026    Days Left: 4    Expected Move: ±466
Nifty CMP: 23,151      India VIX: 14.2  Range: [22,685 — 23,617]

SELL  23800 CE   LTP: ₹32.50   IV: 18.3   Delta: 0.0800   Theta: -31.00
SELL  22400 PE   LTP: ₹28.75   IV: 19.1   Delta: -0.0700  Theta: -29.00
```

### 9c. Confirm the Trade

1. Click **Options Dashboard → Confirm Trade**
2. A sidebar opens with a form:
   - **CE Lots:** 10 (= 650 qty at 65 per lot)
   - **CE Premium:** Enter the actual fill price (e.g., 32.50)
   - **PE Lots:** 10
   - **PE Premium:** Enter the actual fill price (e.g., 28.75)
3. Click **CONFIRM TRADE**
4. The position is saved and appears in **Open Positions**

**Or via API:**
```bash
curl -X POST http://localhost:8000/api/trade/confirm \
  -H "Content-Type: application/json" \
  -d '{"ce_lots": 10, "ce_premium": 32.50, "pe_lots": 10, "pe_premium": 28.75}'
```

### 9d. Monitor Live P&L

The **Open Positions** sheet shows real-time data:

| Position ID | CE Strike | CE P&L | PE Strike | PE P&L | Total P&L | Risk | Status |
|---|---|---|---|---|---|---|---|
| POS_20260313_1015 | 23800 CE | +₹12,350 | 22400 PE | +₹8,125 | +₹20,475 | 18/100 | ACTIVE |

P&L updates every 3 minutes during market hours. Green = profit, red = loss.

### 9e. Watch the Risk Meters

The Dashboard shows SPARKLINE bar charts for each side:

```
CE SIDE  [####----------------]  18/100  SAFE
PE SIDE  [####----------------]  22/100  SAFE
```

If market moves against you, the bars fill up:
```
CE SIDE  [####----------------]  18/100  SAFE
PE SIDE  [################----]  78/100  DANGER
```

### 9f. Act on Hedge Alerts

When risk exceeds 60/100 on either side, a hedge alert appears:

```
HEDGE ALERT — PE SIDE UNDER THREAT
Risk Score: 78/100

SUGGESTED HEDGE:
BUY 24500 PE x 4 lots (260 qty) @ ₹200.00    Cost: ₹52,000

SCENARIO ANALYSIS:
Market Reverses    Nifty @ 24850    Net P&L: +₹20,000
Market Hits 23800  Nifty @ 23800    Net P&L: ≈Break-even
Beyond Protection  Nifty @ 23600    Net P&L: -₹15,000 (partial)
```

Click **Options Dashboard → Confirm Trade** or call the hedge API to execute.

### 9g. Expiry Day

On Tuesday (expiry day), when options expire worthless:
- The position auto-archives to **Trade History**
- P&L finalizes: total premium collected minus any hedge costs

---

## 10. Run Tests

```bash
# Run all 11 unit tests
python tests/test_core.py
```

Expected output:
```
  PASS: test_expected_move_calculation
  PASS: test_round_to_100
  PASS: test_ensure_ends_in_00
  PASS: test_greeks_calculator_call
  PASS: test_greeks_calculator_put
  PASS: test_greeks_far_otm
  PASS: test_risk_scoring
  PASS: test_weekly_expiry
  PASS: test_strike_suggestion_structure
  PASS: test_position_creation
  PASS: test_hedge_calculation_no_threat

11 passed, 0 failed out of 11 tests
```

**What the tests cover:**

| Test | What it validates |
|---|---|
| `test_expected_move_calculation` | VIX formula: Nifty 24200, VIX 14.5, 5 days → ~494 points |
| `test_round_to_100` | CEILING/FLOOR rounding to nearest 100 |
| `test_ensure_ends_in_00` | Strikes never end in "50" |
| `test_greeks_calculator_call` | ATM call delta ≈ 0.50, gamma > 0, theta < 0 |
| `test_greeks_calculator_put` | ATM put delta ≈ -0.50 |
| `test_greeks_far_otm` | Far OTM delta < 0.15 |
| `test_risk_scoring` | Delta/IV/Premium thresholds → correct severity levels |
| `test_weekly_expiry` | Next expiry is a Tuesday (or Monday if holiday) |
| `test_strike_suggestion_structure` | StrikeSuggestion dataclass defaults |
| `test_position_creation` | Lots × lot_size = correct qty, premium math |
| `test_hedge_calculation_no_threat` | No hedge when risk is low (score < 60) |

---

## 11. Deploy to Production

### Option A: Docker (any cloud provider)

```bash
# Build the Docker image
docker build -t nifty-dashboard .

# Run locally with Docker
docker run -p 8000:8000 \
  -e NIFTY_GOOGLE_SHEETS_ID=your_sheet_id \
  -v $(pwd)/credentials.json:/app/credentials.json \
  nifty-dashboard
```

### Option B: Google Cloud Run

```bash
# Authenticate with Google Cloud
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# Build and push
gcloud builds submit --tag gcr.io/YOUR_PROJECT/nifty-dashboard

# Deploy (asia-south1 = Mumbai region, closest to NSE)
gcloud run deploy nifty-dashboard \
  --image gcr.io/YOUR_PROJECT/nifty-dashboard \
  --platform managed \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars "NIFTY_GOOGLE_SHEETS_ID=your_sheet_id"
```

After deployment, update `BACKEND_URL` in `Code.gs`:
```javascript
BACKEND_URL: "https://nifty-dashboard-xxxxx-el.a.run.app",
```

### Option C: Railway

1. Push your repo to GitHub
2. Go to [Railway](https://railway.app/) → **New Project → Deploy from GitHub**
3. Select the repo
4. Add environment variables in the Railway dashboard:
   - `NIFTY_GOOGLE_SHEETS_ID`
   - Upload `credentials.json` as a secret file
5. Railway auto-detects the Dockerfile and deploys
6. Copy the provided URL → update `BACKEND_URL` in `Code.gs`

---

## 12. API Reference

Base URL: `http://localhost:8000` (or your deployed URL)

### Core Endpoints

| Method | Endpoint | Description | Request Body |
|---|---|---|---|
| `GET` | `/` | Server info + status | — |
| `GET` | `/api/health` | Health check | — |
| `POST` | `/api/refresh` | Trigger manual data refresh | — |
| `GET` | `/api/market` | Full market snapshot | — |
| `GET` | `/api/suggestion` | Current strike suggestion | — |
| `GET` | `/api/option-chain` | Raw option chain data | — |
| `GET` | `/api/settings` | Current configuration | — |

### Trade Endpoints

| Method | Endpoint | Description | Request Body |
|---|---|---|---|
| `POST` | `/api/trade/confirm` | Create a position | `{"ce_lots": 10, "ce_premium": 32.5, "pe_lots": 10, "pe_premium": 28.75}` |
| `GET` | `/api/positions` | All active positions | — |
| `GET` | `/api/positions/{id}` | Single position detail | — |
| `POST` | `/api/positions/{id}/close` | Close/archive position | — |
| `GET` | `/api/history` | All closed/expired trades | — |

### Risk & Hedge Endpoints

| Method | Endpoint | Description | Request Body |
|---|---|---|---|
| `GET` | `/api/positions/{id}/risk` | Risk breakdown (CE + PE) | — |
| `GET` | `/api/positions/{id}/hedge` | Hedge suggestion if needed | — |
| `POST` | `/api/positions/{id}/hedge/execute` | Execute the hedge | — |

### Example API Calls

```bash
# Get market data
curl http://localhost:8000/api/market | python -m json.tool

# Get strike suggestion
curl http://localhost:8000/api/suggestion | python -m json.tool

# Confirm a trade
curl -X POST http://localhost:8000/api/trade/confirm \
  -H "Content-Type: application/json" \
  -d '{"ce_lots": 10, "ce_premium": 32.50, "pe_lots": 10, "pe_premium": 28.75}'

# Check positions
curl http://localhost:8000/api/positions | python -m json.tool

# Check if hedge is needed
curl http://localhost:8000/api/positions/POS_20260313_1015/hedge | python -m json.tool

# Execute hedge
curl -X POST http://localhost:8000/api/positions/POS_20260313_1015/hedge/execute

# Close a position
curl -X POST http://localhost:8000/api/positions/POS_20260313_1015/close
```

---

## 13. Configuration Reference

All settings live in `config/settings.py` and can be overridden via environment variables (prefixed with `NIFTY_`) or the `.env` file.

### Trading Parameters

| Parameter | Default | Env Variable | Description |
|---|---|---|---|
| Lot Size | `65` | `NIFTY_LOT_SIZE` | Nifty lot size (changed from 75 → 65, Jan 2026) |
| Strike Offset | `200` | `NIFTY_STRIKE_OFFSET` | Points beyond VIX range for initial strikes |
| Max Delta | `0.20` | `NIFTY_MAX_DELTA` | Maximum delta for suggested strikes |
| Min Premium (DTE >= 7) | `₹12` | `NIFTY_MIN_PREMIUM_GTE7` | Minimum acceptable premium |
| Max Premium (DTE >= 7) | `₹60` | `NIFTY_MAX_PREMIUM_GTE7` | Maximum acceptable premium |
| Risk-Free Rate | `6.5%` | `NIFTY_RISK_FREE_RATE` | For Black-Scholes (India 91-day T-bill) |

### Risk Engine Settings

| Parameter | Default | Description |
|---|---|---|
| Warning Threshold | `30` | Risk score for yellow warning |
| Danger Threshold | `60` | Risk score for red + hedge suggestion |
| Critical Threshold | `80` | Risk score for urgent action |

### Risk Weights (must sum to 1.0)

| Factor | Weight | What it measures |
|---|---|---|
| Delta Drift | `0.30` | How much delta has moved from entry |
| IV Surge | `0.20` | % increase in implied volatility |
| Premium Blowup | `0.20` | Current premium vs entry premium multiple |
| Spot Proximity | `0.25` | How close Nifty is to the sold strike |
| Theta Decay | `0.05` | Actual decay vs expected decay |

### Risk Indicator Thresholds

| Indicator | Warning | Danger | Critical |
|---|---|---|---|
| Delta (abs) | > 0.15 | > 0.25 | > 0.35 |
| IV Change | > +20% | > +40% | > +60% |
| Premium Multiple | > 2x | > 3x | > 5x |
| Spot Proximity | > 60% consumed | > 80% consumed | < 50 pts from strike |

### Auto-Refresh Schedule

| Period | Frequency |
|---|---|
| Market hours (9:15 AM - 3:30 PM IST) | Every 3 minutes |
| Pre-market (9:00 - 9:15 AM IST) | Every 3 minutes |
| After hours / weekends / holidays | No auto-refresh (manual only) |

---

## 14. Project Structure

```
Market_Study/
│
├── run.py                              # Entry point: starts FastAPI server
├── requirements.txt                    # Python dependencies
├── Dockerfile                          # Docker container definition
├── .env.example                        # Environment variable template
├── .gitignore                          # Git ignore rules
│
├── config/
│   ├── __init__.py
│   └── settings.py                     # All configurable parameters (Pydantic)
│
├── backend/
│   ├── __init__.py
│   ├── app.py                          # FastAPI app + scheduler + 15 endpoints
│   └── modules/
│       ├── __init__.py
│       ├── data_fetcher.py             # NSE India scraper (option chain + indices)
│       ├── greeks_calculator.py        # Black-Scholes: Delta, Gamma, Theta, Vega
│       ├── market_utils.py             # Expiry calc, market hours, rounding
│       ├── strike_suggestion.py        # VIX range → delta-balanced strike selection
│       ├── risk_engine.py              # Composite risk scoring (0-100)
│       ├── hedge_calculator.py         # Protective buy suggestions + scenarios
│       ├── trade_manager.py            # Position CRUD + live P&L tracking
│       └── sheets_manager.py           # Google Sheets API integration
│
├── apps_script/
│   ├── appsscript.json                 # Apps Script manifest (IST timezone, scopes)
│   ├── Code.gs                         # Main: custom menu, triggers, trade flow
│   ├── DashboardWriter.gs              # Writes market data + suggestions to sheet
│   └── UIHelpers.gs                    # HTML sidebar templates + sheet formatting
│
├── tests/
│   ├── __init__.py
│   └── test_core.py                    # 11 unit tests for all core modules
│
└── docs/
    └── SETUP.md                        # Condensed setup reference
```

### Module Dependency Graph

```
app.py
 ├── data_fetcher.py          Scrapes NSE → MarketSnapshot
 ├── strike_suggestion.py     MarketSnapshot → StrikeSuggestion
 │    ├── market_utils.py     VIX formula, expiry dates, rounding
 │    └── greeks_calculator.py Black-Scholes Greeks
 ├── trade_manager.py         StrikeSuggestion → Position → P&L
 │    ├── risk_engine.py      Position → RiskBreakdown (0-100)
 │    └── hedge_calculator.py RiskBreakdown → HedgeSuggestion
 └── sheets_manager.py        All of the above → Google Sheet cells
```

---

## 15. How Each Feature Works

### Feature 1: Strike Suggestion Engine

The engine runs a 5-step pipeline every time data is refreshed:

**Step 1 — VIX-Based Expected Range**
```
expected_move = Nifty_CMP × (India_VIX / sqrt(252 / days_to_expiry)) / 100
Upper Range   = Nifty_CMP + expected_move
Lower Range   = Nifty_CMP - expected_move
```

**Step 2 — Initial Strike Selection**
```
CE strike = CEILING(Upper_Range, 100) + 200    (further OTM on call side)
PE strike = FLOOR(Lower_Range, 100) - 200      (further OTM on put side)
```
All strikes **must end in "00"** — never "50".

**Step 3 — Delta Balancing**
- The side with lower IV becomes the "anchor"
- The opposite side scans strikes until it finds one with matching |delta|
- Both sides must have |delta| < 0.20

**Step 4 — Premium Validation** (only if days to expiry >= 7)
- Each strike's premium must be between ₹12 and ₹60
- If outside range: shifts the strike closer/further from spot

**Step 5 — Output**
- Final CE and PE strikes with LTP, IV, Delta, Theta, Gamma

### Feature 2: Risk Monitor

Five risk indicators are scored on a 0-100 scale and weighted:

| Indicator | Weight | What triggers it |
|---|---|---|
| **Delta Drift** | 30% | Your sold option's delta has increased (market moving toward strike) |
| **IV Surge** | 20% | Implied volatility has risen since entry (options getting expensive) |
| **Premium Blowup** | 20% | Current premium is 2x/3x/5x what you sold it for |
| **Spot Proximity** | 25% | Nifty is getting close to your sold strike |
| **Theta Decay** | 5% | Premium is not decaying as fast as theta predicted |

**Risk levels:**
- 0-30: SAFE (green)
- 31-60: WARNING (yellow/orange)
- 61-80: DANGER (red) — hedge suggestion triggers
- 81-100: CRITICAL (dark red) — hedge immediately

### Feature 3: Hedge Calculator

When risk > 60 on either side:

1. Identifies the **threatened side** (higher risk score)
2. Finds the nearest **support/resistance level** beyond the sold strike
3. Calculates **max loss** if market reaches that level
4. Selects an **ATM option** to buy as hedge
5. Calculates **lots needed** for break-even protection
6. Runs **3 scenario analyses** (best case, worst case, beyond protection)

---

## 16. Troubleshooting

### Backend won't start

```
ModuleNotFoundError: No module named 'fastapi'
```
**Fix:** Activate your virtual environment and install dependencies:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### NSE returns 403 Forbidden

```
WARNING:backend.modules.data_fetcher:NSE homepage returned 403
ERROR:backend.modules.data_fetcher:Failed to fetch option chain data
```

NSE India aggressively blocks non-browser requests. The scraper uses a two-step session flow (homepage → option-chain page → API) with realistic Chrome headers, but 403s can still happen.

**Fixes to try (in order):**
1. **Wait and retry** — NSE rate-limits aggressively. The scraper auto-retries with exponential backoff. Give it 2-3 refresh cycles (6-9 minutes).
2. **Check market hours** — NSE APIs work most reliably during trading hours (9:15 AM - 3:30 PM IST, Mon-Fri). Outside hours, the APIs may be less responsive.
3. **Check your IP** — NSE may block cloud/VPN/datacenter IPs. Running from a residential ISP connection (like your home WiFi) usually works.
4. **Try from a browser first** — Open `https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY` in Chrome. If this works in Chrome but not in the app, it's a header/cookie issue.
5. **Restart the server** — This creates a fresh HTTP session: `Ctrl+C` then `python run.py`.
6. **Check firewall/antivirus** — Some corporate firewalls or antivirus software block outbound HTTPS to NSE.

### Google Sheets "Permission denied"

```
gspread.exceptions.APIError: 403 PERMISSION_DENIED
```
**Fix:**
1. Ensure you shared the Google Sheet with the service account email (step 5c)
2. Ensure Google Sheets API and Drive API are both enabled (step 4b)
3. Check that `credentials.json` is in the project root

### Apps Script "Cannot connect to backend"

```
Connection Error: Cannot connect to backend
```
**Fix:** Google Apps Script runs on Google servers — it cannot reach `localhost`.
- Use [ngrok](https://ngrok.com/) for local dev: `ngrok http 8000` → use the ngrok URL
- Or deploy the backend to Cloud Run / Railway first

### "No suggestion available"

**Fix:** This happens when:
- Market data hasn't been fetched yet — click Refresh Data
- Nifty spot or VIX is 0 (data fetch failed)
- It's outside market hours and no cached data exists

### Tests fail with import errors

**Fix:** Run tests from the project root:
```bash
cd Market_Study
python tests/test_core.py
```

---

## 17. Disclaimer

This dashboard is for **educational and personal use only**. It is **not financial advice**.

- Options trading involves significant risk of loss
- Past performance does not guarantee future results
- Always do your own research (DYOR) before placing trades
- Consult a SEBI-registered investment advisor for personalized advice
- The developers are not responsible for any trading losses

All monetary values are in **Indian Rupees (INR)**. Market data is sourced from NSE India public APIs.

---

**Built for the Indian options trading community.**
