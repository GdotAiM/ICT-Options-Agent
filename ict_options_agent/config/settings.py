import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Alpaca
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = os.getenv("ALPACA_PAPER", "true").lower() == "true"

# Risk
RISK_PCT = float(os.getenv("RISK_PCT", "0.0075"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "4"))
MAX_CONTRACTS_PER_TRADE = 10
# Kill switch: halt all new entries for the rest of the day once account
# equity drawdown from the day's starting equity exceeds this fraction.
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.03"))

# Exit rules (deterministic, applied every manage_positions cycle)
# unrealized_plpc is Alpaca's position-level P&L fraction (e.g. 0.50 = +50%).
ENABLE_EXITS = os.getenv("ENABLE_EXITS", "true").lower() == "true"
# Take profit when unrealized P&L % reaches this (works for both debit & credit).
PROFIT_TARGET_PCT = float(os.getenv("PROFIT_TARGET_PCT", "0.50"))
# Stop when unrealized P&L % falls to or below this (e.g. -0.5 = -50% of entry).
# -1.0 (full loss) was too permissive — it lets losing positions run to expiry.
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "-0.5"))
# Close any option with this many calendar days (or fewer) left to expiration.
MAX_DTE_TO_HOLD = int(os.getenv("MAX_DTE_TO_HOLD", "2"))
# Optional: flatten all option positions when the daily kill switch trips.
# Default changed to true after security audit — a circuit breaker that leaves
# positions open defeats its purpose; a 3% drawdown can swing to -10%+ rapidly.
FLATTEN_ON_KILL_SWITCH = os.getenv("FLATTEN_ON_KILL_SWITCH", "true").lower() == "true"

# Local durable state (positions/orders/kill-switch) — survives restarts.
STATE_DB_PATH = BASE_DIR / "data" / "agent_state.db"

# Universe
UNDERLYINGS = ["SPY", "QQQ"]

# Options
MIN_DTE = int(os.getenv("MIN_DTE", "3"))
MAX_DTE = int(os.getenv("MAX_DTE", "14"))
SPREAD_WIDTH_TARGET = 5.0  # dollars

# Quote quality gates — reject a quote rather than trade on a bad price.
# Spread as a fraction of mid (0.25 = 25%); options routinely quote wider
# than equities, so this is looser than you'd use for a stock.
MAX_QUOTE_SPREAD_PCT = float(os.getenv("MAX_QUOTE_SPREAD_PCT", "0.25"))
MAX_QUOTE_AGE_SECONDS = float(os.getenv("MAX_QUOTE_AGE_SECONDS", "30"))

# ---------- ICT / Timing (multi-window, works WITH other concepts) ----------
# Legacy single window (kept for backward compatibility)
KILL_ZONE_START_HOUR = 7
KILL_ZONE_END_HOUR = 10

# Precise ICT windows (hour, minute, hour, minute) in US/Eastern
KILL_ZONES = {
    "asian_range":     (20, 0, 0, 0),    # 20:00 – 00:00 (context / liquidity only)
    "london_open":     (2, 0, 5, 0),     # 02:00 – 05:00 (Judas / manipulation)
    "ny_pre_open":     (8, 0, 9, 30),    # 08:00 – 09:30
    "ny_open":         (9, 30, 10, 0),   # 09:30 – 10:00 (equity open displacement)
    "silver_bullet":   (10, 0, 11, 0),   # 10:00 – 11:00  ★ highest priority
    "london_close":    (10, 0, 12, 0),   # overlap with Silver Bullet
    "ny_pm":           (14, 0, 15, 0),   # afternoon secondary
}

# Windows that count as "high probability" for new entries
PRIMARY_WINDOWS = ["silver_bullet", "ny_open", "ny_pre_open", "london_close"]

# Soft dead zones – still allow signal but heavily penalize score
DEAD_ZONES = [
    (11, 30, 13, 30),   # lunch
    (15, 15, 16, 0),    # late day
]

# Time confluence behaviour
# False = time is a soft score (works together with sweep/MSS/FVG/PD)
# True  = only allow entries inside PRIMARY_WINDOWS
REQUIRE_PRIMARY_WINDOW = False

# Minimum time_score (0.0–1.0) required when REQUIRE_PRIMARY_WINDOW is False
MIN_TIME_SCORE = 0.35

SWING_LOOKBACK = 5
FVG_MIN_RELATIVE_SIZE = 0.0008

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ---------- Liquidity / contract filters ----------
MIN_OPEN_INTEREST = int(os.getenv("MIN_OPEN_INTEREST", "50"))
MIN_OPTION_VOLUME = int(os.getenv("MIN_OPTION_VOLUME", "0"))  # 0 = disabled

# ---------- Portfolio risk caps ----------
# Max fraction of equity at risk across *all* open option positions combined.
MAX_PORTFOLIO_RISK_PCT = float(os.getenv("MAX_PORTFOLIO_RISK_PCT", "0.04"))
# Soft delta cap (absolute sum of signed deltas of option positions). None/0 = off.
MAX_PORTFOLIO_DELTA = float(os.getenv("MAX_PORTFOLIO_DELTA", "50"))

# ---------- End-of-day flatten ----------
# US/Eastern hour:minute after which open option positions are flattened.
EOD_FLATTEN = os.getenv("EOD_FLATTEN", "false").lower() == "true"
EOD_FLATTEN_HOUR = int(os.getenv("EOD_FLATTEN_HOUR", "15"))
EOD_FLATTEN_MINUTE = int(os.getenv("EOD_FLATTEN_MINUTE", "45"))

# ---------- Audit trail ----------
AUDIT_DIR = BASE_DIR / "logs" / "audit"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# ---------- AI trading agent ----------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
# In competition/demo mode, fail closed if a real LLM is unavailable.
AI_REQUIRED = os.getenv("AI_REQUIRED", "false").lower() == "true"
AI_REASSESS_ENABLED = os.getenv("AI_REASSESS_ENABLED", "true").lower() == "true"
AI_REASSESS_MINUTES = int(os.getenv("AI_REASSESS_MINUTES", "15" ) )

# LLM API key - supports OpenAI-compatible providers (OpenAI, Fireworks, Together, Groq)
LLM_API_KEY = os.getenv("OPENAI_API_KEY", "") or os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")  # Optional: custom endpoint for compatible providers

# Autonomous research loop
RESEARCH_ENABLED = os.getenv("RESEARCH_ENABLED", "true").lower() == "true"
RESEARCH_MEMORY_LIMIT = int(os.getenv("RESEARCH_MEMORY_LIMIT", "12"))
RESEARCH_RESOLVE_ENABLED = os.getenv("RESEARCH_RESOLVE_ENABLED", "true").lower() == "true"
