"""Positions & Orders — Live Alpaca Data"""
import json
from pathlib import Path
from datetime import datetime
import streamlit as st
import pandas as pd
from config import settings

# Import SSL setup first (must be before any HTTP libraries)
from src.ssl_setup import ensure_ssl_working
ensure_ssl_working()

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

st.set_page_config(page_title="Positions", page_icon="💼", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"] { font-family: 'JetBrains Mono', monospace; background: #08090C; color: #E2E8F0; }
#MainMenu {visibility:hidden;} footer {visibility:hidden;}
.card { background:#161B22; border:1px solid #30363D; border-radius:10px; padding:1.25rem; margin-bottom:1.5rem; }
.card-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem; padding-bottom:0.75rem; border-bottom:1px solid #21262D; }
.card-title { font-size:0.85rem; font-weight:600; color:#8B949E; text-transform:uppercase; letter-spacing:0.08em; }
.view-all { font-size:0.75rem; color:#58A6FF; cursor:pointer; }
.stDataFrame { border-radius:8px; } .stDataFrame table { background:#161B22; }
.stDataFrame td, .stDataFrame th { border-color:#21262D !important; color:#E2E8F0 !important; font-size:0.78rem !important; padding:0.6rem 0.75rem !important; }
.stDataFrame th { background:#0D1117 !important; color:#8B949E !important; text-transform:uppercase; letter-spacing:0.08em; font-size:0.68rem !important; }
.pnl-pos { color:#3FB950; } .pnl-neg { color:#FF4444; }
.refresh-btn { background:#21262D !important; border:1px solid #30363D !important; color:#E2E8F0 !important; font-family:JetBrains Mono,monospace !important; font-size:0.75rem !important; padding:0.4rem 1rem !important; border-radius:6px !important; cursor:pointer; }
.refresh-btn:hover { background:#30363D !important; border-color:#8B949E !important; }
</style>
""", unsafe_allow_html=True)

# ── Fetch Live Data ────────────────────────────────────────────────────────────
@st.cache_data(ttl=30)
def fetch_positions():
    try:
        client = TradingClient(settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY, paper=settings.ALPACA_PAPER)
        positions = client.get_all_positions()
        rows = []
        for p in positions:
            symbol = getattr(p, 'symbol', '')
            qty = float(getattr(p, 'qty', 0))
            avg_entry = float(getattr(p, 'avg_entry_price', 0))
            current_price = float(getattr(p, 'current_price', 0))
            market_value = float(getattr(p, 'market_value', 0))
            unrealized_pl = float(getattr(p, 'unrealized_pl', 0))
            unrealized_plpc = float(getattr(p, 'unrealized_plpc', 0))
            try:
                sym_short = f"{symbol[:3]} {symbol[3:11]} ${float(symbol[11:])/1000:.0f}"
            except:
                sym_short = symbol
            rows.append({
                "Asset": sym_short,
                "Qty": f"{qty:+.0f}" if qty != int(qty) else str(int(qty)),
                "Side": "LONG" if qty > 0 else "SHORT",
                "Avg Entry": f"${avg_entry:,.2f}",
                "Current": f"${current_price:,.2f}",
                "Mkt Value": f"${market_value:,.2f}",
                "Unrealized P&L": f"${unrealized_pl:,.2f}",
                "Unrealized %": f"{unrealized_plpc*100:+.2f}%",
            })
        return rows
    except Exception as e:
        st.error(f"Failed to fetch positions: {e}")
        return []

@st.cache_data(ttl=30)
def fetch_orders(limit=50):
    try:
        client = TradingClient(settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY, paper=settings.ALPACA_PAPER)
        # Use 'all' status to get all orders including filled ones
        req = GetOrdersRequest(status='all', limit=limit)
        orders = client.get_orders(req)
        rows = []
        for o in orders[:limit]:
            status = str(getattr(o, 'status', '')).split('.')[-1] if getattr(o, 'status', None) else ''
            submitted = getattr(o, 'submitted_at', '')
            filled_at = getattr(o, 'filled_at', '')

            # Handle multi-leg orders
            legs = getattr(o, 'legs', []) or []
            if legs:
                # Multi-leg order - create one row per leg
                for leg in legs:
                    symbol = getattr(leg, 'symbol', '')
                    side = str(getattr(leg, 'side', '')).split('.')[-1].title()
                    qty = float(getattr(leg, 'qty', 0))
                    filled_qty = float(getattr(leg, 'filled_qty', 0))
                    avg_fill = float(getattr(leg, 'filled_avg_price', 0))
                    try:
                        sym_short = f"{symbol[:3]} {symbol[3:11]} ${float(symbol[11:])/1000:.0f}"
                    except:
                        sym_short = symbol
                    rows.append({
                        "Asset": sym_short,
                        "Type": str(getattr(leg, 'order_type', '')).split('.')[-1],
                        "Side": side,
                        "Qty": f"{qty:.2f}",
                        "Filled": f"{filled_qty:.2f}",
                        "Fill Price": f"${avg_fill:,.2f}",
                        "Status": status,
                        "Time": str(submitted)[:19] if submitted else "",
                    })
            else:
                # Single-leg order
                symbol = getattr(o, 'symbol', '')
                side = str(getattr(o, 'side', '')).split('.')[-1].title()
                qty = float(getattr(o, 'qty', 0))
                filled_qty = float(getattr(o, 'filled_qty', 0))
                avg_fill = float(getattr(o, 'filled_avg_price', 0))
                try:
                    sym_short = f"{symbol[:3]} {symbol[3:11]} ${float(symbol[11:])/1000:.0f}"
                except:
                    sym_short = symbol
                rows.append({
                    "Asset": sym_short,
                    "Type": str(getattr(o, 'order_type', '')).split('.')[-1],
                    "Side": side,
                    "Qty": f"{qty:.2f}",
                    "Filled": f"{filled_qty:.2f}",
                    "Fill Price": f"${avg_fill:,.2f}",
                    "Status": status,
                    "Time": str(submitted)[:19] if submitted else "",
                })
        return rows
    except Exception as e:
        st.error(f"Failed to fetch orders: {e}")
        import traceback
        st.error(traceback.format_exc())
        return []

# ── Refresh Button ─────────────────────────────────────────────────────────────
col1, col2 = st.columns([5,1])
with col1:
    st.markdown("### LIVE POSITIONS & ORDERS")
with col2:
    if st.button("🔄 Refresh", key="refresh_btn", help="Fetch latest data from Alpaca"):
        fetch_positions.clear()
        fetch_orders.clear()
        st.rerun()

# ── Positions Table ────────────────────────────────────────────────────────────
positions = fetch_positions()
if positions:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="card-header"><span class="card-title">Open Positions</span></div>', unsafe_allow_html=True)
    df_pos = pd.DataFrame(positions)
    # Color code P&L columns
    st.dataframe(df_pos, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)
else:
    st.caption("No open positions")

# ── Orders Table ───────────────────────────────────────────────────────────────
orders = fetch_orders(limit=50)
if orders:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="card-header"><span class="card-title">Recent Filled Orders</span><span class="view-all">View All</span></div>', unsafe_allow_html=True)
    df_ORD = pd.DataFrame(orders)
    st.dataframe(df_ORD, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # Pagination hint
    st.caption(f"Showing last {len(orders)} of {len(orders)} filled orders")
else:
    st.caption("No recent orders found")

# ── Equity Summary ─────────────────────────────────────────────────────────────
try:
    client = TradingClient(settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY, paper=settings.ALPACA_PAPER)
    acct = client.get_account()
    equity = float(getattr(acct, 'equity', 0))
    day_start = float(getattr(acct, 'day_trade_equity', equity))
    pnl = equity - day_start
    pnl_pct = (pnl / day_start * 100) if day_start > 0 else 0

    st.markdown(f"""
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin-top:1.5rem">
        <div class="card" style="margin-bottom:0">
            <div class="card-title">Total Equity</div>
            <div style="font-size:1.5rem;font-weight:700;color:#F6F8FA">${equity:,.2f}</div>
        </div>
        <div class="card" style="margin-bottom:0">
            <div class="card-title">Day P&L</div>
            <div style="font-size:1.5rem;font-weight:700;color:{'#3FB950' if pnl>=0 else '#FF4444'}">${pnl:+,.2f} ({pnl_pct:+.2f}%)</div>
        </div>
        <div class="card" style="margin-bottom:0">
            <div class="card-title">Buying Power</div>
            <div style="font-size:1.5rem;font-weight:700;color:#F6F8FA">${float(getattr(acct, 'buying_power', 0)):,.2f}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
except Exception as e:
    st.caption(f"Could not fetch account data: {e}")
