/**
 * UI Helpers — HTML templates for sidebars, dialogs, formatting functions.
 */

function getTradeConfirmHTML() {
  return `
<!DOCTYPE html>
<html>
<head>
  <base target="_top">
  <style>
    body { font-family: 'Google Sans', Arial, sans-serif; padding: 16px; background: #fafafa; }
    h2 { color: #1a237e; margin-bottom: 8px; }
    .section { background: white; border-radius: 8px; padding: 16px; margin: 12px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.12); }
    .section h3 { color: #004d40; margin: 0 0 12px 0; font-size: 14px; }
    label { display: block; font-size: 12px; color: #666; margin-top: 8px; }
    input { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; margin-top: 4px; font-size: 14px; box-sizing: border-box; }
    input:focus { border-color: #1a237e; outline: none; }
    .info { font-size: 11px; color: #888; margin-top: 2px; }
    .btn { width: 100%; padding: 12px; border: none; border-radius: 6px; font-size: 14px; font-weight: bold; cursor: pointer; margin-top: 16px; }
    .btn-confirm { background: #00c853; color: white; }
    .btn-confirm:hover { background: #00a844; }
    .btn-cancel { background: #e0e0e0; color: #333; margin-top: 8px; }
    .result { margin-top: 12px; padding: 12px; border-radius: 4px; display: none; }
    .result.success { background: #e8f5e9; color: #2e7d32; display: block; }
    .result.error { background: #ffebee; color: #c62828; display: block; }
    .lot-info { font-size: 11px; color: #1565c0; }
  </style>
</head>
<body>
  <h2>Confirm Trade</h2>

  <div class="section">
    <h3>CALL (CE) Side — SELL</h3>
    <label>Number of Lots</label>
    <input type="number" id="ceLots" value="10" min="1" max="100" onchange="updateQty('ce')">
    <div class="lot-info">Qty: <span id="ceQty">650</span> (1 lot = 65 qty)</div>
    <label>Premium Received (per qty) ₹</label>
    <input type="number" id="cePremium" step="0.05" placeholder="e.g., 32.50">
  </div>

  <div class="section">
    <h3>PUT (PE) Side — SELL</h3>
    <label>Number of Lots</label>
    <input type="number" id="peLots" value="10" min="1" max="100" onchange="updateQty('pe')">
    <div class="lot-info">Qty: <span id="peQty">650</span> (1 lot = 65 qty)</div>
    <label>Premium Received (per qty) ₹</label>
    <input type="number" id="pePremium" step="0.05" placeholder="e.g., 28.75">
  </div>

  <button class="btn btn-confirm" onclick="submitTrade()">CONFIRM TRADE</button>
  <button class="btn btn-cancel" onclick="google.script.host.close()">Cancel</button>

  <div id="result" class="result"></div>

  <script>
    const LOT_SIZE = 65;

    function updateQty(side) {
      const lots = parseInt(document.getElementById(side + 'Lots').value) || 0;
      document.getElementById(side + 'Qty').textContent = lots * LOT_SIZE;
    }

    function submitTrade() {
      const ceLots = document.getElementById('ceLots').value;
      const cePremium = document.getElementById('cePremium').value;
      const peLots = document.getElementById('peLots').value;
      const pePremium = document.getElementById('pePremium').value;

      if (!cePremium || !pePremium) {
        showResult('Please enter premiums for both sides.', 'error');
        return;
      }

      google.script.run
        .withSuccessHandler(function(msg) {
          if (msg.startsWith('Error')) {
            showResult(msg, 'error');
          } else {
            showResult(msg, 'success');
            setTimeout(function() { google.script.host.close(); }, 3000);
          }
        })
        .withFailureHandler(function(err) {
          showResult('Failed: ' + err.message, 'error');
        })
        .confirmTrade(ceLots, cePremium, peLots, pePremium);
    }

    function showResult(msg, type) {
      const el = document.getElementById('result');
      el.textContent = msg;
      el.className = 'result ' + type;
    }
  </script>
</body>
</html>`;
}

function getHelpHTML() {
  return `
<!DOCTYPE html>
<html>
<head>
  <base target="_top">
  <style>
    body { font-family: 'Google Sans', Arial, sans-serif; padding: 16px; line-height: 1.6; }
    h2 { color: #1a237e; }
    h3 { color: #004d40; margin-top: 20px; }
    .feature { background: #f5f5f5; border-radius: 8px; padding: 12px; margin: 8px 0; }
    code { background: #e8eaf6; padding: 2px 6px; border-radius: 3px; font-size: 12px; }
    .warning { background: #fff3e0; border-left: 4px solid #ff9800; padding: 8px 12px; margin: 8px 0; }
    ul { padding-left: 20px; }
  </style>
</head>
<body>
  <h2>Nifty Options Dashboard Help</h2>

  <h3>Getting Started</h3>
  <div class="feature">
    <ol>
      <li>Click <b>Options Dashboard → Initialize Dashboard</b> to set up all sheets</li>
      <li>Click <b>Refresh Data</b> to fetch latest market data from NSE</li>
      <li>Review the <b>Trade Suggestion</b> on the Dashboard</li>
      <li>Click <b>Confirm Trade</b> to book a position</li>
      <li>Enable <b>Auto-Refresh</b> for live tracking during market hours</li>
    </ol>
  </div>

  <h3>Feature 1: Strike Suggestion</h3>
  <div class="feature">
    <ul>
      <li>Calculates VIX-based expected range for Nifty</li>
      <li>Suggests CE and PE strikes 150-200 points outside the range</li>
      <li>All strikes end in "00" (never "50")</li>
      <li>Validates delta balance between both sides</li>
      <li>Checks premium range (₹12-60) if DTE ≥ 7 days</li>
    </ul>
  </div>

  <h3>Feature 2: Live P&L + Risk Monitor</h3>
  <div class="feature">
    <ul>
      <li>Real-time P&L tracking (green = profit, red = loss)</li>
      <li>Risk score 0-100 for each side based on:</li>
      <li>Delta drift, IV surge, premium blowup, spot proximity, theta decay</li>
      <li>Visual risk meters with SPARKLINE charts</li>
      <li><b>Green (0-30)</b>: Safe | <b>Yellow (31-60)</b>: Warning | <b>Red (61-80)</b>: Danger | <b>Dark Red (81-100)</b>: Critical</li>
    </ul>
  </div>

  <h3>Feature 3: Hedge Suggestions</h3>
  <div class="feature">
    <ul>
      <li>Auto-triggers when risk score > 60</li>
      <li>Suggests buying ATM options to hedge the threatened side</li>
      <li>Calculates required lots for break-even protection</li>
      <li>Shows best-case and worst-case scenario analysis</li>
    </ul>
  </div>

  <h3>Keyboard Shortcuts</h3>
  <div class="feature">
    <ul>
      <li>Use the <b>Options Dashboard</b> menu for all actions</li>
      <li><b>Auto-Refresh</b>: Fetches data every 3 minutes during market hours</li>
    </ul>
  </div>

  <div class="warning">
    <b>Disclaimer:</b> This dashboard is for educational/personal use only.
    It is not financial advice. Always do your own research before trading.
    All values are in Indian Rupees (INR).
  </div>

  <h3>Technical Details</h3>
  <div class="feature">
    <ul>
      <li>Data source: NSE India API</li>
      <li>Greeks: Black-Scholes model (risk-free rate: 6.5%)</li>
      <li>Lot size: 65 (configurable in Settings)</li>
      <li>Market hours: 9:15 AM – 3:30 PM IST, Mon-Fri</li>
      <li>Weekly expiry: Every Tuesday</li>
    </ul>
  </div>
</body>
</html>`;
}

// ── Sheet Formatting Functions ──

function formatDashboardSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(CONFIG.SHEET_NAMES.DASHBOARD);
  if (!sheet) return;

  // Set column widths
  sheet.setColumnWidth(1, 150);
  for (let i = 2; i <= 12; i++) {
    sheet.setColumnWidth(i, 120);
  }

  // Set default font
  sheet.getRange("A1:T100").setFontFamily("Google Sans");

  // Freeze row 1 (title)
  sheet.setFrozenRows(1);
}

function writeOpenPositions(positions) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(CONFIG.SHEET_NAMES.OPEN_POSITIONS);
  if (!sheet) {
    sheet = ss.insertSheet(CONFIG.SHEET_NAMES.OPEN_POSITIONS);
  }

  sheet.clear();

  // Headers
  const headers = [
    "Position ID", "Trade Date", "Expiry", "Status", "Entry Spot",
    "CE Strike", "CE Premium", "CE Lots", "CE Current LTP", "CE P&L",
    "PE Strike", "PE Premium", "PE Lots", "PE Current LTP", "PE P&L",
    "Total Premium", "Total P&L", "Hedge Cost", "Net P&L", "Risk Score",
    "Last Updated"
  ];

  sheet.getRange(1, 1, 1, headers.length).setValues([headers])
    .setFontWeight("bold").setBackground("#1a237e").setFontColor("white");

  let row = 2;
  for (const pos of positions) {
    const data = [
      pos.position_id, pos.trade_date, pos.expiry_date, pos.status,
      pos.entry_spot || "",
      pos.ce_strike, pos.ce_premium, pos.ce_lots, pos.ce_current_ltp || 0,
      pos.ce_pnl || 0,
      pos.pe_strike, pos.pe_premium, pos.pe_lots, pos.pe_current_ltp || 0,
      pos.pe_pnl || 0,
      pos.total_premium || 0, pos.total_pnl || 0,
      pos.hedge_cost || 0, pos.net_pnl || 0,
      (pos.overall_risk || 0).toFixed(0) + "/100",
      pos.last_updated || "",
    ];
    sheet.getRange(row, 1, 1, data.length).setValues([data]);

    // Color P&L cells
    const pnlCols = [10, 15, 17, 19]; // CE P&L, PE P&L, Total P&L, Net P&L columns
    for (const c of pnlCols) {
      const val = sheet.getRange(row, c).getValue();
      sheet.getRange(row, c).setFontColor(val >= 0 ? "#00c853" : "#ff1744")
        .setNumberFormat("₹#,##0");
    }

    row++;
  }

  // Auto-resize
  if (positions.length > 0) {
    sheet.autoResizeColumns(1, headers.length);
  }
}

function setupSettingsSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(CONFIG.SHEET_NAMES.SETTINGS);
  if (!sheet) {
    sheet = ss.insertSheet(CONFIG.SHEET_NAMES.SETTINGS);
  }

  sheet.clear();

  const data = [
    ["Parameter", "Value", "Description"],
    ["Lot Size", 65, "Nifty lot size (changed from 75 to 65 effective Jan 2026)"],
    ["Strike Offset", 200, "Points away from VIX range to suggest strikes"],
    ["Max Delta", 0.20, "Maximum acceptable delta for suggested strikes"],
    ["Min Premium (DTE>=7)", 12, "Minimum premium when days to expiry >= 7"],
    ["Max Premium (DTE>=7)", 60, "Maximum premium when days to expiry >= 7"],
    ["Risk Warning Threshold", 30, "Risk score to trigger yellow warning"],
    ["Risk Danger Threshold", 60, "Risk score to trigger red/hedge suggestion"],
    ["Risk Critical Threshold", 80, "Risk score for critical alert"],
    ["Auto-Refresh Interval (min)", 3, "Minutes between data refreshes"],
    ["Risk-Free Rate (%)", 6.5, "For Black-Scholes calculations"],
    ["Support/Resistance Levels", "22000, 22500, 23000, 23500, 24000, 24500, 25000, 25500, 26000",
     "Key levels for hedge calculations (comma-separated)"],
    ["", "", ""],
    ["Market Hours", "9:15 AM - 3:30 PM IST", "Monday to Friday (excluding holidays)"],
    ["Weekly Expiry", "Every Tuesday", "Shifted to Monday if Tuesday is a holiday"],
    ["Strike Intervals", "50 points", "Only '00' ending strikes are suggested for selling"],
    ["", "", ""],
    ["DISCLAIMER", "For educational/personal use only. Not financial advice.", ""],
  ];

  sheet.getRange(1, 1, data.length, 3).setValues(data);

  // Format header
  sheet.getRange(1, 1, 1, 3).setFontWeight("bold").setBackground("#1a237e").setFontColor("white");

  // Protect formula cells but allow value column edits
  sheet.setColumnWidth(1, 200);
  sheet.setColumnWidth(2, 250);
  sheet.setColumnWidth(3, 400);

  // Protect parameter names and descriptions (columns A and C)
  const protection = sheet.getRange("A1:A18").protect();
  protection.setDescription("Parameter names — do not edit");
  protection.setWarningOnly(true);
}
