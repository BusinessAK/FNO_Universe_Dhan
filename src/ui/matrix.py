"""
Vanguard Institutional Terminal - Institutional Inventory Matrix UI Component
"""
import streamlit as st
import pandas as pd
from datetime import datetime
import os
from src.services.database_service import DatabaseService
from src.ui.cards import render_html, format_score, get_ifs_hsl, fmt_gex

def render_inventory_matrix(all_symbols: list, session_history: dict, latest_date: str, trading_dates: list):
    """
    Compiles and renders the flagship Custom HTML Grid Matrix in Section A.
    """
    # Inject isolated premium stylesheets for Section A
    render_html("""
    <style>
    /* Premium custom scrollbar styling inside matrix table */
    .matrix-wrapper::-webkit-scrollbar {
        width: 6px;
        height: 6px;
    }
    .matrix-wrapper::-webkit-scrollbar-track {
        background: rgba(9, 9, 27, 0.4);
        border-radius: 4px;
    }
    .matrix-wrapper::-webkit-scrollbar-thumb {
        background: rgba(167, 139, 250, 0.18);
        border-radius: 4px;
        border: 1px solid rgba(167, 139, 250, 0.1);
    }
    .matrix-wrapper::-webkit-scrollbar-thumb:hover {
        background: rgba(167, 139, 250, 0.4);
    }
    
    /* Sleek Pulsing Indicators */
    .pulse-dot-bull {
        width: 7px;
        height: 7px;
        background-color: #00ff66;
        border-radius: 50%;
        display: inline-block;
        margin-left: 8px;
        vertical-align: middle;
        box-shadow: 0 0 6px #00ff66;
        animation: pulse-glow-bull 1.5s infinite alternate;
    }
    .pulse-dot-bear {
        width: 7px;
        height: 7px;
        background-color: #ff3333;
        border-radius: 50%;
        display: inline-block;
        margin-left: 8px;
        vertical-align: middle;
        box-shadow: 0 0 6px #ff3333;
        animation: pulse-glow-bear 1.5s infinite alternate;
    }
    .pulse-dot-gold {
        width: 7px;
        height: 7px;
        background-color: #fbbf24;
        border-radius: 50%;
        display: inline-block;
        margin-left: 8px;
        vertical-align: middle;
        box-shadow: 0 0 6px #fbbf24;
        animation: pulse-glow-gold 1.5s infinite alternate;
    }
    .pulse-dot-rot {
        width: 7px;
        height: 7px;
        background-color: #7888aa;
        border-radius: 50%;
        display: inline-block;
        margin-left: 8px;
        vertical-align: middle;
        opacity: 0.65;
    }
    
    @keyframes pulse-glow-bull {
        0% { transform: scale(0.9); opacity: 0.55; box-shadow: 0 0 2px #00ff66; }
        100% { transform: scale(1.15); opacity: 1; box-shadow: 0 0 10px #00ff66; }
    }
    @keyframes pulse-glow-bear {
        0% { transform: scale(0.9); opacity: 0.55; box-shadow: 0 0 2px #ff3333; }
        100% { transform: scale(1.15); opacity: 1; box-shadow: 0 0 10px #ff3333; }
    }
    @keyframes pulse-glow-gold {
        0% { transform: scale(0.9); opacity: 0.55; box-shadow: 0 0 2px #fbbf24; }
        100% { transform: scale(1.15); opacity: 1; box-shadow: 0 0 10px #fbbf24; }
    }
    
    /* Glassmorphism Table Wrapper overrides */
    .matrix-wrapper {
        max-height: 580px;
        overflow: auto;
        border: 1px solid rgba(167, 139, 250, 0.15) !important;
        border-radius: 8px;
        background: linear-gradient(135deg, rgba(8, 8, 22, 0.95), rgba(12, 12, 34, 0.95)) !important;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.5) !important;
        backdrop-filter: blur(8px) !important;
        -webkit-backdrop-filter: blur(8px) !important;
    }
    
    /* Fine-tune table spacing and visual border overrides */
    .matrix-table {
        border-collapse: separate !important;
        border-spacing: 0px !important;
        background: transparent !important;
        border: none !important;
    }
    .matrix-table th {
        background-color: #050514 !important;
        border-bottom: 2px solid rgba(20, 20, 53, 0.6) !important;
        font-weight: 700 !important;
        color: #5d6d8f !important;
        font-size: 9.5px !important;
        transition: background-color 0.2s, color 0.2s !important;
    }
    .matrix-table th:hover {
        background-color: #141435 !important;
        color: #a78bfa !important;
    }
    .matrix-table td {
        border-bottom: 1px solid rgba(20, 20, 53, 0.3) !important;
    }
    .matrix-table td:first-child {
        background-color: #050512 !important;
        border-right: 2px solid rgba(20, 20, 53, 0.7) !important;
    }
    .matrix-table th:first-child {
        background-color: #050514 !important;
        border-right: 2px solid rgba(20, 20, 53, 0.7) !important;
    }
    </style>
    """)

    # Search and filtration for the matrix
    m_col1, m_col2, m_col3 = st.columns([4, 3, 3])
    with m_col1:
        search_query = st.text_input("🔍 Filter Symbols", "", placeholder="Enter symbol name...").upper().strip()
    with m_col2:
        sort_by = st.selectbox(
            "Sort Inventory Grid By",
            ["Vanguard Priority Score (Recommended)", "Vanguard Conviction Score (IFS)", "Bullish Persistence Count", "Bearish Persistence Count", "Alphabetical"],
            index=0
        )
    with m_col3:
        max_symbols = st.slider("Display Limit (Rows)", 10, 50, 15, 5)
        
    db_service = DatabaseService()
    matrix_rows = []
    use_db = True
    
    try:
        df = db_service.get_matrix_data(search_query)
        if not df.empty:
            # Group by symbol & date lookup
            lookup = {}
            for _, r in df.iterrows():
                sym = r["symbol"]
                dt = r["date"]
                if sym not in lookup:
                    lookup[sym] = {}
                lookup[sym][dt] = r.to_dict()
                
            db_symbols = df["symbol"].unique()
            for sym in db_symbols:
                sym_history = lookup.get(sym, {})
                latest_sym_metrics = sym_history.get(latest_date, {})
                if not latest_sym_metrics:
                    continue
                    
                # Convert type mapping
                ifs_score = latest_sym_metrics.get("ifs_score", 0.0)
                bull_p = int(latest_sym_metrics.get("bullish_persistence", 0)) if not pd.isna(latest_sym_metrics.get("bullish_persistence")) else 0
                bear_p = int(latest_sym_metrics.get("bearish_persistence", 0)) if not pd.isna(latest_sym_metrics.get("bearish_persistence")) else 0
                priority_score = latest_sym_metrics.get("priority_score", 0.0)
                
                matrix_rows.append({
                    "SYMBOL": sym,
                    "IFS_LATEST": ifs_score,
                    "BULL_PERSIST": bull_p,
                    "BEAR_PERSIST": bear_p,
                    "PRIORITY_SCORE": priority_score,
                    "metrics": sym_history
                })
        else:
            use_db = False
    except Exception as e:
        st.error(f"DuckDB Query failed: {e}. Falling back to JSON loading.")
        use_db = False
            
    if not use_db:
        # Fallback JSON loader
        for sym in all_symbols:
            sym_history = session_history.get(sym, {})
            latest_sym_metrics = sym_history.get(latest_date, {})
            if not latest_sym_metrics:
                continue
                
            # Get persistence and current IFS
            ifs_score = latest_sym_metrics.get("ifs_score", 0.0)
            bull_p = latest_sym_metrics.get("bullish_persistence", 0)
            bear_p = latest_sym_metrics.get("bearish_persistence", 0)
            priority_score = latest_sym_metrics.get("priority_score", 0.0)
            
            # Check query match
            if search_query and search_query not in sym:
                continue
                
            matrix_rows.append({
                "SYMBOL": sym,
                "IFS_LATEST": ifs_score,
                "BULL_PERSIST": bull_p,
                "BEAR_PERSIST": bear_p,
                "PRIORITY_SCORE": priority_score,
                "metrics": sym_history
            })
            
    # Sort matrix rows
    if sort_by == "Vanguard Priority Score (Recommended)":
        matrix_rows = sorted(matrix_rows, key=lambda x: x["PRIORITY_SCORE"], reverse=True)
    elif sort_by == "Vanguard Conviction Score (IFS)":
        matrix_rows = sorted(matrix_rows, key=lambda x: abs(x["IFS_LATEST"]), reverse=True)
    elif sort_by == "Bullish Persistence Count":
        matrix_rows = sorted(matrix_rows, key=lambda x: x["BULL_PERSIST"], reverse=True)
    elif sort_by == "Bearish Persistence Count":
        matrix_rows = sorted(matrix_rows, key=lambda x: x["BEAR_PERSIST"], reverse=True)
    else: # Alphabetical
        matrix_rows = sorted(matrix_rows, key=lambda x: x["SYMBOL"])
        
    # Slice rows
    sliced_rows = matrix_rows[:max_symbols]
    
    if not sliced_rows:
        st.warning("No symbols match your filters.")
    else:
        # Generate the Custom HTML Grid Matrix
        dates_headers_html = "".join([f"<th>{datetime.strptime(d, '%Y-%m-%d').strftime('%d %b')}</th>" for d in trading_dates])
        
        table_rows_html = ""
        for row in sliced_rows:
            sym = row["SYMBOL"]
            ifs_lat = row["IFS_LATEST"]
            bull_p = row["BULL_PERSIST"]
            bear_p = row["BEAR_PERSIST"]
            
            # Determine symbol cell glow and persistence badge
            sym_cell_class = ""
            badge_html = ""
            latest_m_temp = row["metrics"].get(latest_date, {})
            regime_transition = latest_m_temp.get("regime_transition", False)
            
            # Dynamic Pulse dot next to symbol
            if regime_transition:
                sym_cell_class = "regime-transition-gold"
                badge_html = f'<span class="persistence-badge" style="background:#4d3c00;color:#fbbf24;border:1px solid #78350f;">⭐ Transition</span>'
                pulse_dot_html = '<span class="pulse-dot-gold" title="Active Regime Shift Crossover Transition"></span>'
            elif bull_p >= 5:
                sym_cell_class = "persist-glow-bull-5"
                badge_html = f'<span class="persistence-badge" style="background:#064e3b;color:#00ff66;border:1px solid #047857;">🔥 Conviction {bull_p}d</span>'
                pulse_dot_html = f'<span class="pulse-dot-bull" title="Bullish flow conviction active: {bull_p}d"></span>'
            elif bull_p >= 3:
                sym_cell_class = "persist-glow-bull-3"
                badge_html = f'<span class="persistence-badge" style="background:#064e3b;color:#10b981;">🔥 Bull {bull_p}d</span>'
                pulse_dot_html = f'<span class="pulse-dot-bull" title="Bullish flow active: {bull_p}d"></span>'
            elif bear_p >= 5:
                sym_cell_class = "persist-glow-bear-5"
                badge_html = f'<span class="persistence-badge" style="background:#4c0519;color:#ff3333;border:1px solid #9f1239;">❄️ Conviction {bear_p}d</span>'
                pulse_dot_html = f'<span class="pulse-dot-bear" title="Bearish flow conviction active: {bear_p}d"></span>'
            elif bear_p >= 3:
                sym_cell_class = "persist-glow-bear-3"
                badge_html = f'<span class="persistence-badge" style="background:#4c0519;color:#f43f5e;">❄️ Bear {bear_p}d</span>'
                pulse_dot_html = f'<span class="pulse-dot-bear" title="Bearish flow active: {bear_p}d"></span>'
            else:
                badge_html = '<span class="persistence-badge" style="background:#141435;color:#7888aa;">⇅ Rotation</span>'
                pulse_dot_html = '<span class="pulse-dot-rot" title="Steady market rotation"></span>'
                
            # Compile individual date cells for this symbol
            date_cells_html = ""
            for d in trading_dates:
                d_metrics = row["metrics"].get(d, {})
                if not d_metrics:
                    date_cells_html += "<td>-</td>"
                    continue
                    
                val = d_metrics.get("ifs_score", 0.0)
                net_inv = d_metrics.get("net_inv_shift", 0.0)
                spot_cl = d_metrics.get("spot_close", 0.0)
                gex = d_metrics.get("gex", 0.0)
                pcr = d_metrics.get("pcr", 0.0)
                c_wall = d_metrics.get("call_wall", 0.0)
                p_wall = d_metrics.get("put_wall", 0.0)
                
                spot_chg = d_metrics.get("spot_change_pct", 0.0)
                chg_ce = d_metrics.get("delta_ce_oi", 0.0)
                chg_pe = d_metrics.get("delta_pe_oi", 0.0)
                delta_oi = chg_ce + chg_pe
                
                # Determine buildup type
                if spot_chg > 0.02 and delta_oi > 0:
                    buildup_tag = "LB"
                    buildup_color = "#00ff66"  # Bright Emerald
                elif spot_chg < -0.02 and delta_oi > 0:
                    buildup_tag = "SB"
                    buildup_color = "#ff3333"  # Bright Crimson
                elif spot_chg < -0.02 and delta_oi < 0:
                    buildup_tag = "LU"
                    buildup_color = "#fb923c"  # Amber Orange
                elif spot_chg > 0.02 and delta_oi < 0:
                    buildup_tag = "SC"
                    buildup_color = "#2dd4bf"  # Ice Teal
                else:
                    buildup_tag = "ROT"
                    buildup_color = "#7888aa"  # Slate Grey
                
                # Volume calculations for bottom micro-bar
                delta_vol = float(d_metrics.get("delta_volume", 0.0))
                tot_vol = float(d_metrics.get("total_volume", 0.0))
                vol_ratio = min(100.0, max(0.0, abs(delta_vol) / (tot_vol + 1.0) * 100.0))
                bar_color = "#10b981" if delta_vol >= 0 else "#ef4444"
                
                # Determine directional arrow
                arrow = "⇅"
                if net_inv > 50000:
                    arrow = "↑"
                elif net_inv < -50000:
                    arrow = "↓"
                    
                # Format cell background
                bg_color, text_color = get_ifs_hsl(val)
                
                # Create descriptive hover tooltip
                tooltip_txt = (
                    f"Symbol: {sym} | Date: {d}\\n"
                    f"IFS score: {val:+.1f}\\n"
                    f"Spot price: ₹{spot_cl:,.2f} ({spot_chg:+.2f}%)\\n"
                    f"Options OI Shift: {delta_oi/100000:+.1f} Lakh contracts ({buildup_tag})\\n"
                    f"Net OI Shift: {net_inv/100000:+.1f} Lakh shares\\n"
                    f"Delta Vol: {delta_vol/100000:+.1f} Lakh contracts\\n"
                    f"Dealer GEX: {fmt_gex(gex)}\\n"
                    f"PCR: {pcr:.2f}\\n"
                    f"Call Wall: {c_wall:.0f} | Put Wall: {p_wall:.0f}"
                )
                
                cell_style = f"background-color: {bg_color}; color: {text_color}; cursor: help; padding: 2px;"
                date_cells_html += (
                    f'<td class="matrix-cell" style="{cell_style}" title="{tooltip_txt}">'
                    f'<div style="position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 44px; min-width: 48px; padding: 2px;">'
                    f'  <div style="position: absolute; top: 1px; left: 2px; font-size: 8px; color: {text_color}; opacity: 0.8; font-weight: 700;">{arrow}</div>'
                    f'  <div style="font-size: 11px; font-weight: 800; margin-top: 4px; line-height: 1.1;">{val:+.0f}</div>'
                    f'  <div style="font-size: 7.5px; font-weight: 700; color: {buildup_color}; opacity: 0.95; margin-top: 1px; font-family: \'Inter Tight\', sans-serif;">{buildup_tag}</div>'
                    f'  <div style="width: 100%; height: 3px; background-color: rgba(255,255,255,0.08); border-radius: 1px; margin-top: 4px; overflow: hidden;">'
                    f'    <div style="width: {vol_ratio}%; height: 100%; background-color: {bar_color};"></div>'
                    f'  </div>'
                    f'</div>'
                    f'</td>'
                )
                
            # Render Row
            table_rows_html += f"""
            <tr>
              <td class="{sym_cell_class}" style="padding: 10px 12px; background-color: #050512 !important;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 2px; min-width: 100px;">
                  <span style="font-size: 13px; font-weight: 800; color: #ffffff; letter-spacing: 0.5px;">{sym}</span>
                  {pulse_dot_html}
                </div>
                <div style="font-size: 9px; color:#4a5a8a; margin-bottom: 3px; font-family: 'JetBrains Mono', monospace;">Latest: ₹{row['metrics'][latest_date]['spot_close']:,.2f}</div>
                <div style="font-size: 9px; color:#a78bfa; font-weight:700; background: rgba(167, 139, 250, 0.08); border: 1px solid rgba(167, 139, 250, 0.18); border-radius: 3px; padding: 1.5px 5px; display: inline-block; font-family: 'JetBrains Mono', monospace;">Pty: {row['PRIORITY_SCORE']:.1f}</div>
              </td>
              <td><span style="font-family:'JetBrains Mono'; font-weight:bold; font-size:12px; color:{'#10b981' if ifs_lat >= 0 else '#ef4444'}">{ifs_lat:+.1f}</span></td>
              <td>{badge_html}</td>
              {date_cells_html}
            </tr>
            """
            
        render_html(f"""
        <div class="matrix-wrapper">
          <table class="matrix-table">
            <thead>
              <tr>
                <th>SYMBOL</th>
                <th>LATEST IFS</th>
                <th>INVENTORY CYCLE</th>
                {dates_headers_html}
              </tr>
            </thead>
            <tbody>
              {table_rows_html}
            </tbody>
          </table>
        </div>
        
        <script>
        (function() {
            function getCellValueForSort(cell, colIndex) {
                if (colIndex === 0) {
                    const tickerSpan = cell.querySelector("span[style*='font-weight: 800']");
                    return tickerSpan ? tickerSpan.innerText.trim() : cell.innerText.trim();
                } else if (colIndex === 1) {
                    return parseFloat(cell.innerText.trim()) || 0;
                } else if (colIndex === 2) {
                    const badge = cell.querySelector(".persistence-badge");
                    if (badge) {
                        const txt = badge.innerText.trim();
                        if (txt.includes("Transition")) return 1000;
                        const match = txt.match(/\\d+/);
                        let val = match ? parseInt(match[0]) : 0;
                        if (txt.includes("Bear")) val = -val;
                        return val;
                    }
                    return 0;
                } else {
                    const valDiv = cell.querySelector("div > div:nth-child(2)");
                    if (valDiv) {
                        const num = parseFloat(valDiv.innerText);
                        return isNaN(num) ? 0 : num;
                    }
                    return 0;
                }
            }

            function sortMatrixTable(colIndex) {
                const table = document.querySelector(".matrix-table");
                if (!table) return;
                const tbody = table.querySelector("tbody");
                const rows = Array.from(tbody.querySelectorAll("tr"));
                
                let isAsc = table.dataset.sortedCol === String(colIndex) && table.dataset.sortedAsc === "true";
                let nextAsc = !isAsc;
                table.dataset.sortedCol = colIndex;
                table.dataset.sortedAsc = nextAsc ? "true" : "false";
                
                rows.sort((a, b) => {
                    const aCell = a.cells[colIndex];
                    const bCell = b.cells[colIndex];
                    if (!aCell || !bCell) return 0;
                    
                    const aVal = getCellValueForSort(aCell, colIndex);
                    const bVal = getCellValueForSort(bCell, colIndex);
                    
                    if (typeof aVal === "number" && typeof bVal === "number") {
                        return nextAsc ? aVal - bVal : bVal - aVal;
                    } else {
                        return nextAsc ? String(aVal).localeCompare(String(bVal)) : String(bVal).localeCompare(String(aVal));
                    }
                });
                
                rows.forEach(row => tbody.appendChild(row));
                
                const headers = table.querySelectorAll("th");
                headers.forEach((h, idx) => {
                    let text = h.innerText.replace(" ▲", "").replace(" ▼", "");
                    if (idx === colIndex) {
                        h.innerText = text + (nextAsc ? " ▲" : " ▼");
                    } else {
                        h.innerText = text;
                    }
                });
            }

            function initSort() {
                const table = document.querySelector(".matrix-table");
                if (!table) {
                    setTimeout(initSort, 100);
                    return;
                }
                
                if (table.dataset.sortInitialized === "true") return;
                table.dataset.sortInitialized = "true";
                
                const headers = table.querySelectorAll("th");
                headers.forEach((header, index) => {
                    header.style.cursor = "pointer";
                    header.title = "Click to sort by this column";
                    header.addEventListener("click", () => {
                        sortMatrixTable(index);
                    });
                });
            }
            
            setTimeout(initSort, 100);
        })();
        </script>
        
        <div class="matrix-legend-container" style="display: flex; flex-direction: column; background: rgba(9, 9, 27, 0.4); border: 1px solid #141435; border-radius: 6px; padding: 10px 15px; margin-top: 10px; font-family: 'Inter', sans-serif; gap: 8px;">
          <div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 10px; border-bottom: 1px solid rgba(20,20,53,0.15); padding-bottom: 8px;">
            <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 15px;">
              <span style="font-size: 10px; font-weight: 700; color: #4a5a8a; letter-spacing: 0.5px; text-transform: uppercase;">Grid Flow:</span>
              <div style="display: flex; align-items: center; gap: 6px; font-size: 10px; color: #7888aa;">
                <span style="display: inline-block; width: 10px; height: 10px; background: rgba(16, 185, 129, 0.7); border-radius: 2px;"></span>
                <span>Green Cell = Bullish Flow (Put Writing / Call Covering)</span>
              </div>
              <div style="display: flex; align-items: center; gap: 6px; font-size: 10px; color: #7888aa;">
                <span style="display: inline-block; width: 10px; height: 10px; background: rgba(239, 68, 68, 0.7); border-radius: 2px;"></span>
                <span>Red Cell = Bearish Flow (Call Writing / Put Unwinding)</span>
              </div>
            </div>
            <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 15px;">
              <div style="display: flex; align-items: center; gap: 4px; font-size: 10px; color: #7888aa;">
                <span style="font-family: 'JetBrains Mono'; font-weight: bold; color: #e2e8f0;">↑ / ↓</span>
                <span>OI Shift Direction</span>
              </div>
              <div style="display: flex; align-items: center; gap: 6px; font-size: 10px; color: #7888aa;">
                <div style="display: inline-flex; flex-direction: column; width: 12px; height: 4px; background: rgba(255,255,255,0.08); border-radius: 1px; overflow: hidden; vertical-align: middle;">
                  <div style="width: 100%; height: 100%; background: #ef4444;"></div>
                </div>
                <span>Bottom Bar = Session Volume Delta (Green: Active, Red: Contracting)</span>
              </div>
            </div>
          </div>
          <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 15px; font-size: 10px; color: #7888aa;">
            <span style="font-size: 10px; font-weight: 700; color: #4a5a8a; letter-spacing: 0.5px; text-transform: uppercase;">F&O Buildup:</span>
            <span>🟢 <b style="color:#00ff66;">LB</b> = Long Buildup</span>
            <span>🔴 <b style="color:#ff3333;">SB</b> = Short Buildup</span>
            <span>🟠 <b style="color:#fb923c;">LU</b> = Long Unwinding</span>
            <span>🔵 <b style="color:#2dd4bf;">SC</b> = Short Covering</span>
            <span>⇅ <b style="color:#7888aa;">ROT</b> = Rotation</span>
          </div>
        </div>
        """)
        
        # Navigation guide
        st.caption("💡 Tip: Hover over any matrix cell to view exact closing Spot, GEX, Walls, and PCR metrics. Use the Active Symbol dropdown in the sidebar to perform single-stock deep dives.")
