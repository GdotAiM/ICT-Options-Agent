"""Account — Positions, Orders & P&L"""
import json
from pathlib import Path
from collections import defaultdict
import calendar
from datetime import datetime
import pytz
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from config import settings

st.set_page_config(page_title="Account", page_icon="💼", layout="wide")

# CSS styling
st.markdown("""
<style>
html, body, [class*="css"] { font-family: 'JetBrains Mono', monospace; background: #08090C; color: #E2E8F0; }
#MainMenu {visibility:hidden;} footer {visibility:hidden;}
.stDataFrame { border-radius:8px; } .stDataFrame table { background:#161B22; }
.stDataFrame td, .stDataFrame th { border-color:#21262D !important; color:#E2E8F0 !important; font-size:0.78rem !important; padding:0.6rem 0.75rem !important; }
.stDataFrame th { background:#0D1117 !important; color:#8B949E !important; text-transform:uppercase; letter-spacing:0.08em; font-size:0.68rem !important; }
.account-header { display:flex; gap:2rem; padding:1rem 0; border-bottom:1px solid #21262D; margin-bottom:1.5rem; }
.account-stat { } .account-stat .label { font-size:0.65rem; color:#8B949E; text-transform:uppercase; letter-spacing:0.08em; }
.account-stat .value { font-size:1.4rem; font-weight:700; color:#F6F8FA; }
h2, h3, h4 { font-size:0.85rem !important; font-weight:600 !important; color:#8B949E !important; text-transform:uppercase !important; letter-spacing:0.1em !important; margin-top:1.5rem !important; padding-bottom:0.5rem !important; border-bottom:1px solid #21262D !important; }
</style>
""", unsafe_allow_html=True)

# Load data
def load_cycles():
    audit_dir = Path(settings.AUDIT_DIR)
    files = sorted(audit_dir.glob("cycle_*.json"), reverse=True) if audit_dir.exists() else []
    cycles = []
    for f in files[:50]:
        try: cycles.append(json.loads(f.read_text()))
        except: pass
    return cycles

cycles = load_cycles()
latest = cycles[0] if cycles else {}

# Account header
equity = latest.get("equity", 0)
day_start = latest.get("day_starting_equity", equity)
pnl = equity - day_start
positions = latest.get("positions_snapshot") or latest.get("positions", [])

st.markdown(f"""
<div class="account-header">
    <div class="account-stat"><div class="label">Total Equity</div><div class="value">${equity:,.2f}</div></div>
    <div class="account-stat"><div class="label">Day P&L</div><div class="value" style="color:{'#3FB950' if pnl>=0 else '#FF4444'}">${pnl:+,.2f}</div></div>
    <div class="account-stat"><div class="label">Positions</div><div class="value">{len(positions)}</div></div>
    <div class="account-stat"><div class="label">Options Level</div><div class="value">{latest.get('options_level', '?')}</div></div>
    <div class="account-stat"><div class="label">Status</div><div class="value" style="color:{'#FF4444' if latest.get('halted') else '#3FB950'}">{'HALTED' if latest.get('halted') else 'ACTIVE'}</div></div>
</div>
""", unsafe_allow_html=True)

# Equity Chart (TOP SECTION)
st.markdown("### EQUITY CURVE")
if len(cycles) > 1:
    equity_times = []
    equity_values = []
    for c in cycles[:100]:
        ts = c.get("ts_utc", "")
        eq = c.get("equity", 0)
        if ts and eq:
            equity_times.append(ts)
            equity_values.append(eq)

    if equity_times:
        equity_times = equity_times[::-1]
        equity_values = equity_values[::-1]

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=equity_times, y=equity_values, mode='lines+markers', name='Equity',
                                 line=dict(color='#58A6FF', width=2), marker=dict(size=4)))
        fig.add_trace(go.Scatter(x=equity_times, y=equity_values, mode='none', fill='tozeroy',
                                 fillcolor='rgba(88, 166, 255, 0.1)', showlegend=False))

        start_eq = equity_values[0]
        fig.add_hline(y=start_eq, line_dash="dash", line_color="#8B949E",
                     annotation_text=f"Start: ${start_eq:,.2f}", annotation_position="right")

        fig.update_layout(height=300, paper_bgcolor='#0D1117', plot_bgcolor='#161B22',
                         font=dict(family="JetBrains Mono, monospace", color="#E2E8F0", size=11),
                         xaxis=dict(gridcolor='#21262D', tickformat='%m/%d %H:%M'),
                         yaxis=dict(gridcolor='#21262D', tickprefix='$', tickformat=',.0f'),
                         margin=dict(l=60, r=40, t=30, b=40), showlegend=False)

        st.plotly_chart(fig, use_container_width=True)

        final_eq = equity_values[-1]
        change = final_eq - start_eq
        high = max(equity_values)
        low = min(equity_values)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f'<div style="background:#161B22;border:1px solid #30363D;border-radius:8px;padding:0.75rem;text-align:center"><div style="font-size:0.65rem;color:#8B949E;text-transform:uppercase">Current</div><div style="font-size:1.25rem;font-weight:700;color:#F6F8FA">${final_eq:,.2f}</div></div>', unsafe_allow_html=True)
        with col2:
            pnl_color = "#3FB950" if change>=0 else "#FF4444"
            st.markdown(f'<div style="background:#161B22;border:1px solid #30363D;border-radius:8px;padding:0.75rem;text-align:center"><div style="font-size:0.65rem;color:#8B949E;text-transform:uppercase">Change</div><div style="font-size:1.25rem;font-weight:700;color:{pnl_color}">${change:+,.2f}</div></div>', unsafe_allow_html=True)
        with col3:
            st.markdown(f'<div style="background:#161B22;border:1px solid #30363D;border-radius:8px;padding:0.75rem;text-align:center"><div style="font-size:0.65rem;color:#8B949E;text-transform:uppercase">High</div><div style="font-size:1.25rem;font-weight:700;color:#F6F8FA">${high:,.2f}</div></div>', unsafe_allow_html=True)
        with col4:
            st.markdown(f'<div style="background:#161B22;border:1px solid #30363D;border-radius:8px;padding:0.75rem;text-align:center"><div style="font-size:0.65rem;color:#8B949E;text-transform:uppercase">Low</div><div style="font-size:1.25rem;font-weight:700;color:#F6F8FA">${low:,.2f}</div></div>', unsafe_allow_html=True)

st.markdown("---")

# TRADING CALENDAR (AFTER EQUITY CHART)
st.markdown("### TRADING CALENDAR")

# Calculate daily P&L
daily_pnl = defaultdict(float)
daily_trades = defaultdict(int)

for c in cycles:
    ts_str = c.get("ts_utc", "")
    if not ts_str:
        continue
    # Parse UTC timestamp
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        # Convert to ET for consistent date matching
        dt_et = dt.astimezone(pytz.timezone('US/Eastern'))
        ts = dt_et.strftime('%Y-%m-%d')
    except:
        ts = ts_str[:10]
    eq = c.get("equity", 0)
    ds = c.get("day_starting_equity", eq)
    pnl_val = eq - ds
    trades = len([s for s in c.get("signals", []) if s.get("ai_decision", {}).get("decision") == "TRADE"])
    daily_pnl[ts] += pnl_val
    daily_trades[ts] += trades

if daily_pnl:
    # Use ET timezone for consistency with market data
    et = pytz.timezone('US/Eastern')
    now = datetime.now(et)
    year = now.year
    month = now.month
    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]

    html_calendar = f'''
    <div style="background:#161B22;border:1px solid #30363D;border-radius:10px;padding:1rem">
        <div style="text-align:center;margin-bottom:1rem">
            <span style="font-size:1.1rem;font-weight:600;color:#F6F8FA">{month_name} {year}</span>
        </div>
        <table style="width:100%;border-collapse:collapse;font-family:'JetBrains Mono',monospace">
            <thead>
                <tr style="color:#8B949E;font-size:0.75rem;text-transform:uppercase">
                    <th style="padding:0.5rem;text-align:center">Sun</th>
                    <th style="padding:0.5rem;text-align:center">Mon</th>
                    <th style="padding:0.5rem;text-align:center">Tue</th>
                    <th style="padding:0.5rem;text-align:center">Wed</th>
                    <th style="padding:0.5rem;text-align:center">Thu</th>
                    <th style="padding:0.5rem;text-align:center">Fri</th>
                    <th style="padding:0.5rem;text-align:center">Sat</th>
                </tr>
            </thead>
            <tbody>
    '''

    for week in cal:
        html_calendar += "<tr>"
        for day in week:
            date_str = f"{year}-{month:02d}-{day:02d}" if day != 0 else ""
            if day == 0:
                html_calendar += '<td style="padding:0.75rem;text-align:center;color:#484F58"></td>'
            else:
                pnl = daily_pnl.get(date_str, 0)
                trades = daily_trades.get(date_str, 0)
                if pnl > 0:
                    bg = "rgba(63,185,80,0.2)"; tc = "#3FB950"; brd = "1px solid rgba(63,185,80,0.4)"
                elif pnl < 0:
                    bg = "rgba(255,68,68,0.2)"; tc = "#FF4444"; brd = "1px solid rgba(255,68,68,0.4)"
                else:
                    bg = "#0D1117"; tc = "#8B949E"; brd = "1px solid #21262D"

                cell = f'<div style="font-size:0.9rem;font-weight:700;color:{tc}">${pnl:+,.2f}</div><div style="font-size:0.6rem;color:#8B949E">{trades} trade{"" if trades==1 else "s"}</div>' if pnl != 0 else f'<div style="font-size:0.85rem;color:#484F58">{day}</div>'
                html_calendar += f'<td style="padding:0.75rem;text-align:center;background:{bg};border:{brd};border-radius:6px">{cell}</td>'
        html_calendar += "</tr>"

    total_pnl = sum(daily_pnl.values())
    winning = sum(1 for p in daily_pnl.values() if p > 0)
    losing = sum(1 for p in daily_pnl.values() if p < 0)

    html_calendar += f'''
            </tbody>
        </table>
        <div style="display:flex;gap:2rem;margin-top:1rem;font-size:0.75rem">
            <div><span style="color:#8B949E">Total P&L: </span><span style="color:#FF4444;font-weight:700">${total_pnl:+,.2f}</span></div>
            <div><span style="color:#8B949E">Winning Days: </span><span style="color:#3FB950;font-weight:700">{winning}</span></div>
            <div><span style="color:#8B949E">Losing Days: </span><span style="color:#FF4444;font-weight:700">{losing}</span></div>
        </div>
    </div>
    '''
    st.markdown(html_calendar, unsafe_allow_html=True)
else:
    st.caption("No trading data available for calendar view")

st.markdown("---")

# POSITIONS TABLE
st.markdown("### POSITIONS")
if positions:
    rows = []
    for p in positions:
        sym = p.get("symbol", "")
        try:
            sym_short = f"{sym[:3]} {sym[3:11]} ${float(sym[11:])/1000:.0f}"
        except:
            sym_short = sym
        rows.append({
            "Symbol": sym_short,
            "Qty": p.get("qty", ""),
            "Side": p.get("side", "").replace("PositionSide.", ""),
            "Market Value": f"${float(p.get('market_value',0)):,.0f}",
            "Unrealized %": f"{float(p.get('unrealized_plpc',0))*100:+.1f}%",
        })
    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
else:
    st.caption("No open positions")

st.markdown("---")

# ORDER HISTORY
st.markdown("### ORDER HISTORY")
all_orders = []
for c in cycles:
    for o in c.get("orders", []):
        all_orders.append({
            "Time": c.get("ts_utc","")[:19],
            "Symbol": o.get("symbol",""),
            "Strategy": o.get("strategy",""),
            "Qty": o.get("qty",""),
            "Result": str(o.get("result",""))[:60],
        })
if all_orders:
    df_orders = pd.DataFrame(all_orders[-20:][::-1])
    st.dataframe(df_orders, width='stretch', hide_index=True)
else:
    st.caption("No orders placed yet")

st.markdown("---")

# PERFORMANCE
st.markdown("### PERFORMANCE")
pnl_rows = []
for c in cycles[:20]:
    eq = c.get("equity", 0)
    ds = c.get("day_starting_equity", eq)
    pnl_pct = ((eq - ds) / ds * 100) if ds > 0 else 0
    trades = len([s for s in c.get("signals",[]) if s.get("ai_decision",{}).get("decision")=="TRADE"])
    pnl_rows.append({"Time": c.get("ts_utc","")[:16], "Equity": f"${eq:,.2f}", "Day P&L%": f"{pnl_pct:+.2f}%", "Trades": trades})
if pnl_rows:
    st.dataframe(pd.DataFrame(pnl_rows[::-1]), width='stretch', hide_index=True)
