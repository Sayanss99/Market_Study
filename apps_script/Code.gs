/**
 * Nifty Options Selling Dashboard — Google Apps Script Frontend
 * Main entry point: custom menus, triggers, and coordination.
 */

// ── Configuration ──
const CONFIG = {
  BACKEND_URL: "http://localhost:8000",  // Change to deployed URL
  REFRESH_INTERVAL_MINUTES: 3,
  LOT_SIZE: 65,
  SHEET_NAMES: {
    DASHBOARD: "Dashboard",
    OPEN_POSITIONS: "Open Positions",
    RISK_MONITOR: "Risk Monitor",
    TRADE_HISTORY: "Trade History",
    OPTION_CHAIN: "Option Chain Data",
    SETTINGS: "Settings & Config",
  },
};

// ── Custom Menu ──

function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu("Options Dashboard")
    .addItem("Refresh Data", "refreshData")
    .addSeparator()
    .addItem("Generate Strike Suggestion", "showSuggestion")
    .addItem("Confirm Trade", "showTradeConfirmDialog")
    .addSeparator()
    .addItem("View Open Positions", "goToOpenPositions")
    .addItem("View Risk Monitor", "goToRiskMonitor")
    .addItem("View Trade History", "goToTradeHistory")
    .addSeparator()
    .addItem("Setup Auto-Refresh", "setupAutoRefresh")
    .addItem("Stop Auto-Refresh", "stopAutoRefresh")
    .addSeparator()
    .addItem("Initialize Dashboard", "initializeDashboard")
    .addItem("Help", "showHelp")
    .addToUi();
}

// ── Navigation ──

function goToOpenPositions() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(CONFIG.SHEET_NAMES.OPEN_POSITIONS);
  if (sheet) {
    ss.setActiveSheet(sheet);
  }
}

function goToRiskMonitor() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(CONFIG.SHEET_NAMES.RISK_MONITOR);
  if (sheet) {
    ss.setActiveSheet(sheet);
  }
}

function goToTradeHistory() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(CONFIG.SHEET_NAMES.TRADE_HISTORY);
  if (sheet) {
    ss.setActiveSheet(sheet);
  }
}

// ── Data Refresh ──

function refreshData() {
  try {
    const response = UrlFetchApp.fetch(CONFIG.BACKEND_URL + "/api/refresh", {
      method: "post",
      muteHttpExceptions: true,
    });

    const data = JSON.parse(response.getContentText());

    if (data.status === "ok") {
      // Fetch and update all sheets
      updateDashboardFromAPI();
      updatePositionsFromAPI();

      SpreadsheetApp.getActiveSpreadsheet().toast(
        `Nifty: ${data.nifty_spot} | VIX: ${data.india_vix}`,
        "Data Refreshed",
        5
      );
    } else {
      SpreadsheetApp.getActiveSpreadsheet().toast(
        "Refresh failed. Check backend connection.",
        "Error",
        5
      );
    }
  } catch (e) {
    SpreadsheetApp.getActiveSpreadsheet().toast(
      "Cannot connect to backend: " + e.message,
      "Connection Error",
      10
    );
    Logger.log("Refresh error: " + e.message);
  }
}

function updateDashboardFromAPI() {
  try {
    // Fetch market data
    const marketResp = UrlFetchApp.fetch(CONFIG.BACKEND_URL + "/api/market", {
      muteHttpExceptions: true,
    });
    const market = JSON.parse(marketResp.getContentText());

    // Fetch suggestion
    let suggestion = null;
    try {
      const sugResp = UrlFetchApp.fetch(CONFIG.BACKEND_URL + "/api/suggestion", {
        muteHttpExceptions: true,
      });
      if (sugResp.getResponseCode() === 200) {
        suggestion = JSON.parse(sugResp.getContentText());
      }
    } catch (e) {
      Logger.log("No suggestion available: " + e.message);
    }

    writeDashboard(market, suggestion);
  } catch (e) {
    Logger.log("Error updating dashboard: " + e.message);
  }
}

function updatePositionsFromAPI() {
  try {
    const resp = UrlFetchApp.fetch(CONFIG.BACKEND_URL + "/api/positions", {
      muteHttpExceptions: true,
    });
    const data = JSON.parse(resp.getContentText());
    writeOpenPositions(data.positions || []);
  } catch (e) {
    Logger.log("Error updating positions: " + e.message);
  }
}

// ── Suggestion & Trade ──

function showSuggestion() {
  refreshData();

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.setActiveSheet(ss.getSheetByName(CONFIG.SHEET_NAMES.DASHBOARD));
  ss.toast("Strike suggestion updated on Dashboard.", "Suggestion Ready", 5);
}

function showTradeConfirmDialog() {
  const html = HtmlService.createHtmlOutput(getTradeConfirmHTML())
    .setWidth(450)
    .setHeight(500)
    .setTitle("Confirm Trade");
  SpreadsheetApp.getUi().showSidebar(html);
}

function confirmTrade(ceLotsStr, cePremiumStr, peLotsStr, pePremiumStr) {
  try {
    const payload = {
      ce_lots: parseInt(ceLotsStr),
      ce_premium: parseFloat(cePremiumStr),
      pe_lots: parseInt(peLotsStr),
      pe_premium: parseFloat(pePremiumStr),
    };

    const response = UrlFetchApp.fetch(CONFIG.BACKEND_URL + "/api/trade/confirm", {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify(payload),
      muteHttpExceptions: true,
    });

    const data = JSON.parse(response.getContentText());

    if (data.status === "ok") {
      SpreadsheetApp.getActiveSpreadsheet().toast(
        data.message,
        "Trade Confirmed",
        10
      );
      updatePositionsFromAPI();
      return "Trade confirmed: " + data.message;
    } else {
      return "Error: " + (data.detail || "Unknown error");
    }
  } catch (e) {
    return "Error: " + e.message;
  }
}

function executeHedge(positionId) {
  try {
    const response = UrlFetchApp.fetch(
      CONFIG.BACKEND_URL + "/api/positions/" + positionId + "/hedge/execute",
      {
        method: "post",
        muteHttpExceptions: true,
      }
    );

    const data = JSON.parse(response.getContentText());
    if (data.status === "ok") {
      SpreadsheetApp.getActiveSpreadsheet().toast(
        "Hedge executed successfully.",
        "Hedge Confirmed",
        10
      );
      refreshData();
      return "OK";
    }
    return "Error: " + (data.detail || data.message || "Unknown");
  } catch (e) {
    return "Error: " + e.message;
  }
}

// ── Auto-Refresh Triggers ──

function setupAutoRefresh() {
  // Remove existing triggers
  stopAutoRefresh();

  ScriptApp.newTrigger("scheduledRefresh")
    .timeBased()
    .everyMinutes(CONFIG.REFRESH_INTERVAL_MINUTES)
    .create();

  SpreadsheetApp.getActiveSpreadsheet().toast(
    `Auto-refresh set for every ${CONFIG.REFRESH_INTERVAL_MINUTES} minutes during market hours.`,
    "Auto-Refresh Enabled",
    5
  );
}

function stopAutoRefresh() {
  const triggers = ScriptApp.getProjectTriggers();
  for (const trigger of triggers) {
    if (trigger.getHandlerFunction() === "scheduledRefresh") {
      ScriptApp.deleteTrigger(trigger);
    }
  }
  SpreadsheetApp.getActiveSpreadsheet().toast(
    "Auto-refresh stopped.",
    "Auto-Refresh Disabled",
    5
  );
}

function scheduledRefresh() {
  // Only refresh during market hours (9:00 AM - 3:45 PM IST)
  const now = new Date();
  const istOffset = 5.5 * 60; // IST = UTC + 5:30
  const utcMinutes = now.getUTCHours() * 60 + now.getUTCMinutes();
  const istMinutes = utcMinutes + istOffset;
  const istHour = Math.floor(istMinutes / 60) % 24;
  const istMin = istMinutes % 60;

  const day = now.getUTCDay();
  // Skip weekends
  if (day === 0 || day === 6) return;

  // Market hours: 9:00 - 15:45
  const totalMinutes = istHour * 60 + istMin;
  if (totalMinutes >= 540 && totalMinutes <= 945) { // 9:00 to 15:45
    refreshData();
  }
}

// ── Help ──

function showHelp() {
  const html = HtmlService.createHtmlOutput(getHelpHTML())
    .setWidth(500)
    .setHeight(600)
    .setTitle("Dashboard Help");
  SpreadsheetApp.getUi().showSidebar(html);
}

// ── Initialize ──

function initializeDashboard() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // Create all sheets if they don't exist
  for (const [key, name] of Object.entries(CONFIG.SHEET_NAMES)) {
    let sheet = ss.getSheetByName(name);
    if (!sheet) {
      sheet = ss.insertSheet(name);
      Logger.log("Created sheet: " + name);
    }
  }

  // Format Dashboard sheet
  formatDashboardSheet();

  // Setup settings sheet
  setupSettingsSheet();

  // Initial data refresh
  refreshData();

  ss.toast("Dashboard initialized successfully!", "Setup Complete", 10);
}
