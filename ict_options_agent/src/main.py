"""
Entry point - live directional / iron-condor + backtest + MCP verify.
"""
import argparse
import os
import sys
import time
from loguru import logger

# Fix Windows console UTF-8 encoding for argparse help and loguru output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Fix Windows SSL certificate verification
# On Windows, Python's ssl module may not find system CA certificates.
# Set SSL_CERT_FILE to certifi's bundle so HTTPS requests work reliably.
if sys.platform == "win32":
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("CURL_CA_BUNDLE", certifi.where())

from src.utils import setup_logging
from src.backtest import run_backtest
from config import settings

# Ensure SSL is set up (already patched on import of ssl_setup)
from src.ssl_setup import ensure_ssl_working
ensure_ssl_working()


def main():
    parser = argparse.ArgumentParser(description="ICT Options Agent for Alpaca")
    parser.add_argument("--once", action="store_true", help="Single live cycle")
    parser.add_argument("--loop", action="store_true", help="Continuous live")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument(
        "--mode",
        choices=["directional", "condor", "auto"],
        default="directional",
        help="directional=debit spreads, condor=iron condor, auto=choose",
    )
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--autonomous-research", action="store_true", help="Run bounded hypothesis -> backtest -> OOS -> challenge research")
    parser.add_argument("--commit-policy", action="store_true", help="Promote the best policy only if all deterministic/AI gates pass")
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2025-06-30")
    parser.add_argument(
        "--verify-mcp",
        action="store_true",
        help="Probe official alpaca-mcp-server (list tools, no orders)",
    )
    args = parser.parse_args()

    setup_logging()
    logger.info("Starting ICT Options Agent harness")

    if args.verify_mcp:
        from src.mcp_exec import verify_mcp_connectivity
        result = verify_mcp_connectivity()
        if result.get("ok"):
            logger.info(
                f"MCP VERIFY OK — place_option_order available. "
                f"tools={result.get('tools', [])}"
            )
        else:
            logger.error(f"MCP VERIFY FAILED: {result}")
        return

    if args.autonomous_research:
        from src.autonomous_research import run_autonomous_research
        result = run_autonomous_research(args.symbol, args.start, args.end, commit=args.commit_policy)
        logger.info("===== AUTONOMOUS RESEARCH SUMMARY =====")
        logger.info(f"candidate_count={result.get('candidate_count')} selected={bool(result.get('selected'))} committed={result.get('committed_policy')}")
        for r in result.get("results", []):
            logger.info(f"candidate={r['candidate_policy']} | OOS={r['oos'].get('trades')} trades | expR={r['oos'].get('expectancy_r')} | PF={r['oos'].get('profit_factor')} | eligible={r['promotion'].get('eligible')}")
        return

    if args.backtest:
        logger.info(f"Backtest {args.symbol} {args.start} -> {args.end}")
        result = run_backtest(args.symbol, args.start, args.end)
        logger.info("===== BACKTEST SUMMARY =====")
        for k, v in result.items():
            if k != "trade_log":
                logger.info(f"  {k}: {v}")
        return

    if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
        logger.error("Set ALPACA_API_KEY and ALPACA_SECRET_KEY in .env")
        return

    from src.agent import ICTOptionsAgent
    agent = ICTOptionsAgent(mode=args.mode)

    if args.once or not args.loop:
        agent.run_cycle()
        logger.info("Single cycle complete")
        return

    logger.info(f"Loop | interval={args.interval}s | mode={args.mode}")
    while True:
        try:
            agent.run_cycle()
        except Exception as e:
            logger.exception(f"Cycle error: {e}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
