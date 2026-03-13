# Nifty Options Selling Dashboard — Setup Guide

## Architecture Overview

```
Google Sheet (Frontend/UI)
├── Dashboard         — Market overview + trade suggestions
├── Open Positions    — Active trades with live P&L
├── Risk Monitor      — Risk meters + hedging suggestions
├── Trade History     — Archive of past trades
├── Option Chain Data — Raw scraped data
└── Settings & Config — User preferences

Python Backend (FastAPI)
├── data_fetcher      — Scrapes NSE India data
├── strike_suggestion — VIX-based range + delta-balanced strikes
├── greeks_calculator — Black-Scholes Greeks (Delta, Gamma, Theta, Vega)
├── risk_engine       — Composite risk scoring (0-100)
├── hedge_calculator  — Preventive buy trade suggestions
├── trade_manager     — Position tracking + P&L calculation
├── sheets_manager    — Google Sheets API integration
└── app.py            — FastAPI server with auto-refresh scheduler
```

## Prerequisites

- Python 3.10+
- Google Cloud project with Sheets API enabled
- Google service account with Sheets access

## Step 1: Backend Setup

```bash
# Clone and install
cd Market_Study
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Google Sheet ID and credentials path
```

## Step 2: Google Cloud Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project or select existing
3. Enable the **Google Sheets API** and **Google Drive API**
4. Create a **Service Account** under IAM & Admin
5. Download the JSON key file as `credentials.json` in the project root
6. Share your Google Sheet with the service account email (Editor access)

## Step 3: Google Sheet Setup

1. Create a new Google Sheet
2. Copy the Sheet ID from the URL: `https://docs.google.com/spreadsheets/d/SHEET_ID_HERE/edit`
3. Add the Sheet ID to your `.env` file: `NIFTY_GOOGLE_SHEETS_ID=your_id`

## Step 4: Run the Backend

```bash
python run.py
```

The server starts at `http://localhost:8000`. API docs at `http://localhost:8000/docs`.

## Step 5: Google Apps Script Setup

1. Open your Google Sheet
2. Go to **Extensions → Apps Script**
3. Delete the default `Code.gs` content
4. Create the following files and paste content from the `apps_script/` folder:
   - `Code.gs`
   - `DashboardWriter.gs`
   - `UIHelpers.gs`
5. Update `CONFIG.BACKEND_URL` in `Code.gs` to your deployed backend URL
6. Save and reload the Google Sheet
7. Click **Options Dashboard → Initialize Dashboard** from the menu

## Step 6: Deploy Backend (Production)

### Option A: Google Cloud Run
```bash
# Build and push Docker image
gcloud builds submit --tag gcr.io/YOUR_PROJECT/nifty-dashboard
gcloud run deploy nifty-dashboard --image gcr.io/YOUR_PROJECT/nifty-dashboard --platform managed --region asia-south1
```

### Option B: Railway
```bash
# Connect GitHub repo to Railway
# Set environment variables in Railway dashboard
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API info |
| POST | `/api/refresh` | Manual data refresh |
| GET | `/api/market` | Current market snapshot |
| GET | `/api/suggestion` | Strike suggestion |
| POST | `/api/trade/confirm` | Confirm a trade |
| GET | `/api/positions` | All active positions |
| GET | `/api/positions/{id}` | Position details |
| GET | `/api/positions/{id}/risk` | Risk breakdown |
| GET | `/api/positions/{id}/hedge` | Hedge suggestion |
| POST | `/api/positions/{id}/hedge/execute` | Execute hedge |
| POST | `/api/positions/{id}/close` | Close position |
| GET | `/api/history` | Trade history |
| GET | `/api/option-chain` | Raw option chain |
| GET | `/api/settings` | Current settings |
| GET | `/api/health` | Health check |

## Configuration

Edit settings via the **Settings & Config** sheet or environment variables:

| Parameter | Default | Env Variable |
|-----------|---------|-------------|
| Lot Size | 65 | `NIFTY_LOT_SIZE` |
| Strike Offset | 200 | `NIFTY_STRIKE_OFFSET` |
| Max Delta | 0.20 | `NIFTY_MAX_DELTA` |
| Risk-Free Rate | 6.5% | `NIFTY_RISK_FREE_RATE` |
| Refresh Interval | 3 min | `NIFTY_AUTO_REFRESH_INTERVAL` |

## Market Hours

- Trading: 9:15 AM – 3:30 PM IST, Monday to Friday
- Pre-market: 9:00 AM – 9:15 AM IST
- Weekly expiry: Every Tuesday (Monday if Tuesday is a holiday)
- Auto-refresh runs only during market/pre-market hours

## Disclaimer

This dashboard is for educational and personal use only. It is not financial advice.
Always do your own research and consult a financial advisor before trading.
All monetary values are in Indian Rupees (INR).
