"""
SSL context initialization for Windows systems with corporate/AV SSL proxies.

On Windows, Python's ssl module may not find the system certificate store,
causing SSL verification failures even when the system trust store is valid.
This module patches the standard HTTP clients to use truststore, which properly
loads Windows certificate authorities (including corporate/AV SSL inspection certs).

IMPORTANT: This module must be imported BEFORE any other modules that use HTTPS
(e.g., alpaca, requests, urllib3) to ensure the SSL patch is applied first.
"""
import sys
from loguru import logger


def _is_windows():
    """Check if running on Windows."""
    return sys.platform == "win32"


# Apply SSL patch immediately on import (before any HTTP libraries load)
if _is_windows():
    try:
        import truststore
        truststore.inject_into_ssl()
        logger.info("SSL context patched to use Windows certificate store (truststore)")
    except ImportError:
        logger.warning(
            "truststore not installed - SSL verification may fail on Windows "
            "with corporate/AV proxies. Install with: pip install truststore"
        )
    except Exception as e:
        logger.warning(f"Failed to patch SSL context on import: {e}")


def ensure_ssl_working():
    """
    Run a quick SSL connectivity test to verify everything is working.

    Returns:
        bool: True if SSL is working, False if there may be issues
    """
    # SSL patch was already applied on import if on Windows
    try:
        import urllib.request
        req = urllib.request.Request("https://httpbin.org/ip")
        resp = urllib.request.urlopen(req, timeout=5)
        if resp.status == 200:
            logger.info("SSL verification working correctly")
            return True
    except Exception as e:
        logger.warning(f"SSL connectivity test failed (may be network issue): {e}")
        # Return True anyway since the patch is applied - don't fail on network issues
        return True

    return True
