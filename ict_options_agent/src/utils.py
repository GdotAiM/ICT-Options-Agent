"""
Time utilities – multi-window ICT kill zones that work TOGETHER with price concepts.
"""
from datetime import datetime, time
from typing import List, Tuple, Optional, Dict
import pytz
from loguru import logger
import sys
from config.settings import (
    LOG_LEVEL, LOG_DIR,
    KILL_ZONES, PRIMARY_WINDOWS, DEAD_ZONES,
    KILL_ZONE_START_HOUR, KILL_ZONE_END_HOUR,
)


def setup_logging():
    logger.remove()
    logger.add(sys.stderr, level=LOG_LEVEL)
    logger.add(
        LOG_DIR / "agent_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="DEBUG",
    )
    return logger


def now_et() -> datetime:
    return datetime.now(pytz.timezone("US/Eastern"))


def is_weekday(et: Optional[datetime] = None) -> bool:
    return (et or now_et()).weekday() < 5


def _in_window(et: datetime, start_h: int, start_m: int, end_h: int, end_m: int) -> bool:
    """Inclusive start, exclusive end. Handles midnight wrap for Asian range."""
    t = et.time()
    start = time(start_h, start_m)
    end = time(end_h, end_m)
    if start <= end:
        return start <= t < end
    # wraps midnight
    return t >= start or t < end


def get_active_windows(et: Optional[datetime] = None) -> List[str]:
    """Return names of all ICT windows currently active."""
    if et is None:
        et = now_et()
    if not is_weekday(et):
        return []
    active = []
    for name, (sh, sm, eh, em) in KILL_ZONES.items():
        if _in_window(et, sh, sm, eh, em):
            active.append(name)
    return active


def in_dead_zone(et: Optional[datetime] = None) -> bool:
    if et is None:
        et = now_et()
    if not is_weekday(et):
        return True
    for sh, sm, eh, em in DEAD_ZONES:
        if _in_window(et, sh, sm, eh, em):
            return True
    return False


def time_score(et: Optional[datetime] = None) -> float:
    """
    0.0 – 1.0 confluence score.
    Designed to be ADDED to other ICT confluence, not replace it.
    """
    if et is None:
        et = now_et()
    if not is_weekday() or in_dead_zone(et):
        return 0.0

    active = get_active_windows(et)
    if not active:
        # Still inside the legacy broad window? mild score
        if KILL_ZONE_START_HOUR <= et.hour < KILL_ZONE_END_HOUR:
            return 0.30
        return 0.10

    score = 0.0
    # Priority weighting – these stack (overlap is good)
    weights = {
        "silver_bullet": 1.00,
        "ny_open":       0.85,
        "ny_pre_open":   0.70,
        "london_close":  0.65,
        "ny_pm":         0.55,
        "london_open":   0.40,
        "asian_range":   0.20,  # context only
    }
    for w in active:
        score = max(score, weights.get(w, 0.3))

    # Bonus if multiple high-value windows overlap
    primary_hits = sum(1 for w in active if w in PRIMARY_WINDOWS)
    if primary_hits >= 2:
        score = min(1.0, score + 0.10)

    return round(score, 2)


def is_high_probability_time(et: Optional[datetime] = None) -> bool:
    """True when at least one PRIMARY window is active and not in dead zone."""
    if et is None:
        et = now_et()
    if in_dead_zone(et):
        return False
    active = get_active_windows(et)
    return any(w in PRIMARY_WINDOWS for w in active)


# Backward-compatible legacy helper
def in_kill_zone(start_hour: int = None, end_hour: int = None) -> bool:
    """
    Kept for compatibility.
    Now returns True if we are in any primary window OR the legacy broad window.
    """
    et = now_et()
    if not is_weekday():
        return False
    if is_high_probability_time(et):
        return True
    sh = start_hour if start_hour is not None else KILL_ZONE_START_HOUR
    eh = end_hour if end_hour is not None else KILL_ZONE_END_HOUR
    return sh <= et.hour < eh


def time_context(et: Optional[datetime] = None) -> Dict:
    """Rich context dict for logging / signal enrichment."""
    et = et or now_et()
    return {
        "et": et.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "active_windows": get_active_windows(et),
        "time_score": time_score(et),
        "high_probability": is_high_probability_time(et),
        "in_dead_zone": in_dead_zone(et),
    }
