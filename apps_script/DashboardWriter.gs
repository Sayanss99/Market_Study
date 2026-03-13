/**
 * Dashboard Sheet Writer
 * Handles writing market data, suggestions, positions, and risk to the Dashboard sheet.
 */

function writeDashboard(market, suggestion) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(CONFIG.SHEET_NAMES.DASHBOARD);
  if (!sheet) {
    sheet = ss.insertSheet(CONFIG.SHEET_NAMES.DASHBOARD);
  }

  // Clear existing content (preserve formatting)
  sheet.getRange("A1:T100").clearContent();

  let row = 1;

  // ── Title Bar ──
  sheet.getRange(row, 1).setValue("NIFTY OPTIONS SELLING DASHBOARD");
  sheet.getRange(row, 1).setFontSize(16).setFontWeight("bold");
  sheet.getRange(row, 8).setValue("Last Updated: " + (market.timestamp || "N/A"));
  sheet.getRange(row, 12).setValue(market.market_open ? "MARKET OPEN" : "MARKET CLOSED");
  sheet.getRange(row, 12).setBackground(market.market_open ? "#00c853" : "#ff1744")
    .setFontColor("white").setFontWeight("bold");

  // ── Market Overview ──
  row = 3;
  sheet.getRange(row, 1).setValue("MARKET OVERVIEW").setFontSize(12).setFontWeight("bold")
    .setBackground("#1a237e").setFontColor("white");
  sheet.getRange(row, 1, 1, 12).setBackground("#1a237e");

  row = 4;
  const niftyColor = market.nifty_change_pct >= 0 ? "#00c853" : "#ff1744";
  const vixColor = market.india_vix_change_pct >= 0 ? "#ff1744" : "#00c853"; // VIX up = bad

  sheet.getRange(row, 1).setValue("Nifty 50");
  sheet.getRange(row, 2).setValue(market.nifty_spot).setNumberFormat("#,##0.00");
  sheet.getRange(row, 3).setValue(formatPct(market.nifty_change_pct)).setFontColor(niftyColor);

  sheet.getRange(row, 4).setValue("India VIX");
  sheet.getRange(row, 5).setValue(market.india_vix).setNumberFormat("0.00");
  sheet.getRange(row, 6).setValue(formatPct(market.india_vix_change_pct)).setFontColor(vixColor);

  sheet.getRange(row, 7).setValue("Next Expiry");
  sheet.getRange(row, 8).setValue(market.next_expiry || "N/A");

  sheet.getRange(row, 9).setValue("Days to Expiry");
  sheet.getRange(row, 10).setValue(market.days_to_expiry || "N/A");

  // ── Sectoral Indices ──
  row = 6;
  sheet.getRange(row, 1).setValue("SECTORAL INDICES").setFontSize(10).setFontWeight("bold")
    .setBackground("#283593").setFontColor("white");
  sheet.getRange(row, 1, 1, 12).setBackground("#283593");

  row = 7;
  const sectorals = ["NIFTY BANK", "NIFTY IT", "NIFTY PHARMA", "NIFTY FMCG", "NIFTY METAL", "NIFTY AUTO"];
  let col = 1;
  for (const name of sectorals) {
    const idx = (market.indices || {})[name] || {};
    sheet.getRange(row, col).setValue(name).setFontSize(8).setFontWeight("bold");
    sheet.getRange(row, col + 1).setValue(idx.last || "N/A").setNumberFormat("#,##0.00");
    const color = (idx.change_pct || 0) >= 0 ? "#00c853" : "#ff1744";
    sheet.getRange(row, col + 2).setValue(formatPct(idx.change_pct)).setFontColor(color);
    col += 3;
    if (col > 10) {
      col = 1;
      row++;
    }
  }

  // ── Global Markets ──
  row += 1;
  sheet.getRange(row, 1).setValue("GLOBAL MARKETS").setFontSize(10).setFontWeight("bold")
    .setBackground("#283593").setFontColor("white");
  sheet.getRange(row, 1, 1, 12).setBackground("#283593");

  row++;
  const globals = ["DOW JONES", "S&P 500", "NASDAQ", "FTSE 100", "NIKKEI 225", "HANG SENG"];
  col = 1;
  for (const name of globals) {
    const idx = (market.indices || {})[name] || {};
    sheet.getRange(row, col).setValue(name).setFontSize(8).setFontWeight("bold");
    sheet.getRange(row, col + 1).setValue(idx.last || "N/A");
    const color = (idx.change_pct || 0) >= 0 ? "#00c853" : "#ff1744";
    sheet.getRange(row, col + 2).setValue(formatPct(idx.change_pct)).setFontColor(color);
    col += 3;
    if (col > 10) {
      col = 1;
      row++;
    }
  }

  // ── Strike Suggestion ──
  row += 2;
  sheet.getRange(row, 1).setValue("TRADE SUGGESTION").setFontSize(12).setFontWeight("bold")
    .setBackground("#004d40").setFontColor("white");
  sheet.getRange(row, 1, 1, 12).setBackground("#004d40");

  if (suggestion && suggestion.ce_strike > 0) {
    row++;
    sheet.getRange(row, 1).setValue("Expiry: " + suggestion.expiry_date);
    sheet.getRange(row, 4).setValue("Days Left: " + suggestion.days_to_expiry);
    sheet.getRange(row, 7).setValue("Expected Move: ±" + suggestion.expected_move);

    row++;
    sheet.getRange(row, 1).setValue("Nifty CMP: " + formatNum(suggestion.nifty_cmp));
    sheet.getRange(row, 4).setValue("India VIX: " + suggestion.india_vix.toFixed(1));
    sheet.getRange(row, 7).setValue(
      "Range: [" + formatNum(suggestion.lower_range) + " — " + formatNum(suggestion.upper_range) + "]"
    );

    row++;
    // CE Side
    sheet.getRange(row, 1).setValue("SELL").setFontWeight("bold").setFontColor("#ff1744");
    sheet.getRange(row, 2).setValue(suggestion.ce_strike + " CE").setFontWeight("bold");
    sheet.getRange(row, 3).setValue("LTP: ₹" + suggestion.ce_ltp.toFixed(2));
    sheet.getRange(row, 4).setValue("IV: " + suggestion.ce_iv.toFixed(1));
    sheet.getRange(row, 5).setValue("Delta: " + suggestion.ce_delta.toFixed(4));
    sheet.getRange(row, 6).setValue("Theta: " + suggestion.ce_theta.toFixed(2));

    // PE Side
    sheet.getRange(row, 7).setValue("SELL").setFontWeight("bold").setFontColor("#ff1744");
    sheet.getRange(row, 8).setValue(suggestion.pe_strike + " PE").setFontWeight("bold");
    sheet.getRange(row, 9).setValue("LTP: ₹" + suggestion.pe_ltp.toFixed(2));
    sheet.getRange(row, 10).setValue("IV: " + suggestion.pe_iv.toFixed(1));
    sheet.getRange(row, 11).setValue("Delta: " + suggestion.pe_delta.toFixed(4));
    sheet.getRange(row, 12).setValue("Theta: " + suggestion.pe_theta.toFixed(2));

    row++;
    // Confirm Trade button (checkbox)
    sheet.getRange(row, 1).setValue("CONFIRM TRADE →")
      .setFontWeight("bold").setFontColor("#00c853");
    sheet.getRange(row, 3).insertCheckboxes();

    // Validation notes
    if (suggestion.validation_notes && suggestion.validation_notes.length > 0) {
      row++;
      sheet.getRange(row, 1).setValue("Validation Notes:").setFontSize(8).setFontColor("#666");
      for (const note of suggestion.validation_notes) {
        row++;
        sheet.getRange(row, 1).setValue("  • " + note).setFontSize(8).setFontColor("#888");
      }
    }
  } else {
    row++;
    sheet.getRange(row, 1).setValue("No suggestion available. Refresh data or check market hours.");
  }

  // ── Open Positions Summary ──
  row += 2;
  writePositionsSummarySection(sheet, row);
}

function writePositionsSummarySection(sheet, startRow) {
  let row = startRow;

  sheet.getRange(row, 1).setValue("OPEN POSITIONS & P&L").setFontSize(12).setFontWeight("bold")
    .setBackground("#b71c1c").setFontColor("white");
  sheet.getRange(row, 1, 1, 12).setBackground("#b71c1c");

  try {
    const resp = UrlFetchApp.fetch(CONFIG.BACKEND_URL + "/api/positions", {
      muteHttpExceptions: true,
    });
    const data = JSON.parse(resp.getContentText());
    const positions = data.positions || [];

    if (positions.length === 0) {
      row++;
      sheet.getRange(row, 1).setValue("No open positions. Confirm a trade to get started.");
      return row;
    }

    // Headers
    row++;
    const headers = ["ID", "CE Strike", "CE P&L", "PE Strike", "PE P&L", "Total P&L", "Net P&L", "Risk", "Status"];
    for (let i = 0; i < headers.length; i++) {
      sheet.getRange(row, i + 1).setValue(headers[i]).setFontWeight("bold")
        .setBackground("#e0e0e0");
    }

    // Data rows
    for (const pos of positions) {
      row++;
      sheet.getRange(row, 1).setValue(pos.position_id);
      sheet.getRange(row, 2).setValue(pos.ce_strike + " CE");
      sheet.getRange(row, 3).setValue(formatINR(pos.ce_pnl))
        .setFontColor(pos.ce_pnl >= 0 ? "#00c853" : "#ff1744");
      sheet.getRange(row, 4).setValue(pos.pe_strike + " PE");
      sheet.getRange(row, 5).setValue(formatINR(pos.pe_pnl))
        .setFontColor(pos.pe_pnl >= 0 ? "#00c853" : "#ff1744");
      sheet.getRange(row, 6).setValue(formatINR(pos.total_pnl))
        .setFontColor(pos.total_pnl >= 0 ? "#00c853" : "#ff1744")
        .setFontWeight("bold");
      sheet.getRange(row, 7).setValue(formatINR(pos.net_pnl))
        .setFontColor(pos.net_pnl >= 0 ? "#00c853" : "#ff1744")
        .setFontWeight("bold");

      const riskScore = pos.overall_risk || 0;
      const riskColor = riskScore >= 80 ? "#b71c1c" : riskScore >= 60 ? "#ff1744" :
                        riskScore >= 30 ? "#ff9800" : "#00c853";
      sheet.getRange(row, 8).setValue(riskScore.toFixed(0) + "/100")
        .setFontColor(riskColor).setFontWeight("bold");
      sheet.getRange(row, 9).setValue(pos.status);
    }

    // Risk meter section
    row += 2;
    writeRiskMeterSection(sheet, row, positions);

  } catch (e) {
    row++;
    sheet.getRange(row, 1).setValue("Error loading positions: " + e.message);
  }

  return row;
}

function writeRiskMeterSection(sheet, startRow, positions) {
  let row = startRow;

  sheet.getRange(row, 1).setValue("RISK METERS").setFontSize(12).setFontWeight("bold")
    .setBackground("#e65100").setFontColor("white");
  sheet.getRange(row, 1, 1, 12).setBackground("#e65100");

  for (const pos of positions) {
    row++;
    const ceRisk = pos.ce_risk || 0;
    const peRisk = pos.pe_risk || 0;

    // CE Risk Bar (using SPARKLINE)
    sheet.getRange(row, 1).setValue("CE SIDE").setFontWeight("bold");
    sheet.getRange(row, 2).setFormula(
      '=SPARKLINE({' + ceRisk + ',100-' + ceRisk + '},{\"charttype\",\"bar\";\"color1\",\"' +
      getRiskColor(ceRisk) + '\";\"color2\",\"#e0e0e0\"})'
    );
    sheet.getRange(row, 4).setValue(ceRisk.toFixed(0) + "/100")
      .setFontColor(getRiskColor(ceRisk));
    sheet.getRange(row, 5).setValue(getRiskLabel(ceRisk));

    // PE Risk Bar
    sheet.getRange(row, 7).setValue("PE SIDE").setFontWeight("bold");
    sheet.getRange(row, 8).setFormula(
      '=SPARKLINE({' + peRisk + ',100-' + peRisk + '},{\"charttype\",\"bar\";\"color1\",\"' +
      getRiskColor(peRisk) + '\";\"color2\",\"#e0e0e0\"})'
    );
    sheet.getRange(row, 10).setValue(peRisk.toFixed(0) + "/100")
      .setFontColor(getRiskColor(peRisk));
    sheet.getRange(row, 11).setValue(getRiskLabel(peRisk));

    // Check if hedge needed
    if (ceRisk >= 60 || peRisk >= 60) {
      row += 2;
      writeHedgeAlert(sheet, row, pos.position_id);
    }
  }
}

function writeHedgeAlert(sheet, startRow, positionId) {
  let row = startRow;

  try {
    const resp = UrlFetchApp.fetch(
      CONFIG.BACKEND_URL + "/api/positions/" + positionId + "/hedge",
      { muteHttpExceptions: true }
    );
    const hedge = JSON.parse(resp.getContentText());

    if (!hedge.is_needed) return row;

    sheet.getRange(row, 1).setValue("HEDGE ALERT — " + hedge.threatened_side + " SIDE UNDER THREAT")
      .setFontSize(11).setFontWeight("bold").setBackground("#d50000").setFontColor("white");
    sheet.getRange(row, 1, 1, 12).setBackground("#d50000");

    row++;
    sheet.getRange(row, 1).setValue("Risk Score: " + hedge.risk_score.toFixed(0) + "/100");

    row++;
    sheet.getRange(row, 1).setValue("SUGGESTED HEDGE:").setFontWeight("bold");
    row++;
    sheet.getRange(row, 1).setValue(
      "BUY " + hedge.hedge_strike + " " + hedge.threatened_side +
      " × " + hedge.hedge_lots + " lots (" + hedge.hedge_qty + " qty) @ ₹" +
      hedge.hedge_premium.toFixed(2)
    ).setFontWeight("bold").setFontColor("#1565c0");
    sheet.getRange(row, 7).setValue("Cost: " + formatINR(hedge.hedge_cost));
    sheet.getRange(row, 10).setValue("Protection: " + formatNum(hedge.protection_level));

    // Scenarios
    row++;
    sheet.getRange(row, 1).setValue("SCENARIO ANALYSIS:").setFontWeight("bold");
    if (hedge.scenarios) {
      for (const s of hedge.scenarios) {
        row++;
        sheet.getRange(row, 1).setValue(s.name);
        sheet.getRange(row, 5).setValue("Nifty @ " + formatNum(s.nifty_level));
        sheet.getRange(row, 8).setValue("Net P&L: " + formatINR(s.net_pnl))
          .setFontColor(s.net_pnl >= 0 ? "#00c853" : "#ff1744");
        sheet.getRange(row, 11).setValue(s.description);
      }
    }

    row++;
    sheet.getRange(row, 1).setValue("EXECUTE HEDGE →").setFontWeight("bold").setFontColor("#1565c0");
    sheet.getRange(row, 3).insertCheckboxes();

  } catch (e) {
    Logger.log("Error fetching hedge: " + e.message);
  }

  return row;
}

// ── Utility Functions ──

function formatPct(val) {
  if (val === undefined || val === null) return "N/A";
  const sign = val >= 0 ? "+" : "";
  return sign + parseFloat(val).toFixed(2) + "%";
}

function formatNum(val) {
  if (val === undefined || val === null) return "N/A";
  return parseFloat(val).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function formatINR(val) {
  if (val === undefined || val === null) return "₹0";
  const prefix = val >= 0 ? "₹" : "-₹";
  return prefix + Math.abs(val).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function getRiskColor(score) {
  if (score >= 80) return "#b71c1c";
  if (score >= 60) return "#ff1744";
  if (score >= 30) return "#ff9800";
  return "#00c853";
}

function getRiskLabel(score) {
  if (score >= 80) return "CRITICAL";
  if (score >= 60) return "DANGER";
  if (score >= 30) return "WARNING";
  return "SAFE";
}
