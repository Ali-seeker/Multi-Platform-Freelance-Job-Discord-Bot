"""
auth_manager.py — Automatic visitor-session refresh for Upwork scraping.

Phase 3 module that uses headless Chrome (Selenium) to refresh the
anonymous visitor session (Authorization header + Cookie string) used
by the Upwork GraphQL API scraper.

Two refresh triggers:
  1. REACTIVE (primary)  — triggered immediately on 401/403 response
  2. PROACTIVE (secondary) — safety-net timer based on measured cookie lifetime

No login is performed. This simply visits Upwork's public job search page
as an anonymous visitor, waits for Cloudflare cookies and the Bearer token
to be set, extracts them, and closes the browser.

Usage:
    from auth_manager import AuthManager, SessionExpiredError

    auth_mgr = AuthManager(user_agent="Mozilla/5.0 ...")
    auth_header, cookies = auth_mgr.refresh_session(reason="proactive")
"""

import time
import json
from datetime import datetime

from logger import get_logger
logger = get_logger(__name__)

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# ---------------------------------------------------------------------------
# Custom Exception
# ---------------------------------------------------------------------------

class SessionExpiredError(Exception):
    """
    Raised when a 401 or 403 response is received from Upwork's API,
    signaling that the session (Bearer token or Cloudflare cookies)
    has expired and needs to be refreshed.

    This exception is caught by the polling loop in discord_bot.py
    to trigger a reactive session refresh via AuthManager.
    """
    pass


# ---------------------------------------------------------------------------
# AuthManager
# ---------------------------------------------------------------------------

class AuthManager:
    """
    Manages automatic refresh of Upwork visitor session credentials.

    Uses headless Chrome to visit Upwork's public job search page,
    extract the Authorization Bearer token and full Cookie string,
    then close the browser. No login or credentials are involved —
    this is purely an anonymous visitor session.

    Attributes:
        user_agent: The User-Agent string to use (must match the scraper's
                    User-Agent for Cloudflare consistency).
        session_lifetime: Seconds between proactive refreshes (default: 240s / 4 min).
        session_timestamp: When the last successful refresh occurred.
    """

    # The public Upwork job search page — loads as anonymous visitor
    UPWORK_SEARCH_URL = "https://www.upwork.com/nx/search/jobs/"

    def __init__(self, user_agent: str, session_lifetime: int = 240):
        """
        Initialize the AuthManager.

        Args:
            user_agent: The User-Agent string for headless Chrome.
                        Must match the scraper's User-Agent for Cloudflare
                        consistency.
            session_lifetime: Seconds between proactive refreshes.
                              Default 240 (4 minutes) based on measured
                              Cloudflare cookie expiration.
        """
        self.user_agent = user_agent
        self.session_lifetime = session_lifetime
        self.session_timestamp: datetime | None = None

    def should_refresh(self) -> bool:
        """
        Check if a proactive refresh is due.

        Returns True if:
          - No session has ever been established (first run)
          - The session_lifetime has elapsed since the last refresh

        Returns:
            True if proactive refresh should be triggered.
        """
        if self.session_timestamp is None:
            return True

        elapsed = (datetime.now() - self.session_timestamp).total_seconds()
        return elapsed >= self.session_lifetime

    def refresh_session(self, reason: str = "proactive") -> tuple[str, str] | None:
        """
        Launch headless Chrome, visit Upwork, and extract fresh credentials.

        Retries up to 3 times with 5-second delays on failure.

        Args:
            reason: A descriptive string for logging — either
                    "proactive scheduled refresh" or
                    "reactive refresh triggered by 401/403" (or similar).

        Returns:
            Tuple of (authorization_header, cookie_string) on success,
            or None if all retries failed (bot keeps using stale session).
        """
        max_retries = 3
        retry_delay = 5  # seconds

        for attempt in range(1, max_retries + 1):
            logger.info(f"Session refresh ({reason}) — attempt {attempt}/{max_retries}")

            try:
                auth_header, cookie_string = self._do_refresh()
                self.session_timestamp = datetime.now()
                logger.info(f"Session refresh SUCCESS ({reason})")
                logger.info(f"  Bearer token length: {len(auth_header)} chars")
                logger.info(f"  Cookie length: {len(cookie_string)} chars")
                return auth_header, cookie_string

            except Exception as e:
                logger.error(f"Session refresh FAILED on attempt {attempt}/{max_retries}: {e}")
                if attempt < max_retries:
                    logger.warning(f"  Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)

        logger.critical(f"All {max_retries} session refresh attempts failed ({reason}).")
        logger.critical("  Bot will continue with existing (possibly stale) session.")
        logger.critical("  Will try again on the next scheduled check or 401/403.")
        return None

    def _do_refresh(self) -> tuple[str, str]:
        """
        CDP refresh attempt: connect to running browser, enable CDP network logging,
        navigate to or refresh Upwork to capture request headers and cookies.

        Returns:
            Tuple of (authorization_header, cookie_string).

        Raises:
            Exception: If remote debugging connection fails or extraction fails.
        """
        driver = None
        try:
            driver = self._create_driver()

            # Enable CDP network logging to capture outgoing request headers
            driver.execute_cdp_cmd("Network.enable", {})

            # Navigate to or refresh the public Upwork search page
            logger.info("  Refreshing/Navigating to Upwork search page...")
            driver.get(self.UPWORK_SEARCH_URL)

            # Wait for cookies and network requests to capture
            logger.info("  Waiting for network requests to settle...")
            time.sleep(5)

            # Extract cookies from the browser session
            cookie_string = self._extract_cookies_string(driver)
            if not cookie_string:
                raise RuntimeError("No cookies extracted from browser session")

            # Extract the Authorization Bearer token from network requests
            auth_header = self._extract_auth_token(driver)
            if not auth_header:
                raise RuntimeError(
                    "Could not extract Authorization header from network requests. "
                    "Make sure you have passed Turnstile once on the active tab."
                )

            return auth_header, cookie_string

        except Exception as e:
            # Wrap connection errors cleanly
            raise RuntimeError(f"Chrome CDP connection lost or failed: {e}")
        finally:
            # We do NOT quit the browser since it's the user's remote debugging browser.
            # We just close our local session interface to release the debugger.
            if driver:
                try:
                    driver.quit() # Detaches debugger connection without closing browser
                    logger.info("  Detached from remote browser.")
                except Exception as e:
                    logger.warning(f"  Warning: debugger detach cleanup error: {e}")

    def _create_driver(self) -> webdriver.Chrome:
        """
        Connect to an already running Chrome instance via Remote Debugging.

        Assumes the user launched Chrome with:
        chrome.exe --remote-debugging-port=9222

        Returns:
        Configured Chrome WebDriver instance connected to the running Chrome.
        """
        import socket
        # Fast fail: check if the debugging port is even open before calling Selenium
        try:
            with socket.create_connection(("127.0.0.1", 9222), timeout=1.0):
                pass
        except (socket.timeout, ConnectionRefusedError):
            raise ConnectionError(
                "Chrome is not running on port 9222. Please start Chrome with: "
                "--remote-debugging-port=9222 --user-data-dir=C:\\chrome-dev-profile"
            )

        options = ChromeOptions()
        options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
        # Enable performance logging to capture network requests when connecting via remote debugging
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

        # Use webdriver-manager to auto-download the correct ChromeDriver
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        logger.info("Connected to running Chrome instance via Remote Debugging.")
        return driver

    def _extract_cookies_string(self, driver: webdriver.Chrome) -> str:
        """
        Convert Selenium's cookie list to a semicolon-delimited header string.

        This produces the exact format used in the 'cookie' HTTP header.
        """
        cookies = driver.get_cookies()
        if not cookies:
            return ""

        cookie_parts = [f"{c['name']}={c['value']}" for c in cookies]
        cookie_string = "; ".join(cookie_parts)

        # Log key cookies for debugging
        cookie_names = [c["name"] for c in cookies]
        key_cookies = ["cf_clearance", "__cf_bm", "XSRF-TOKEN", "visitor_id"]
        found = [name for name in key_cookies if name in cookie_names]
        missing = [name for name in key_cookies if name not in cookie_names]
        logger.info(f"  Cookies extracted: {len(cookies)} total")
        if found:
            logger.info(f"  Key cookies present: {', '.join(found)}")
        if missing:
            logger.info(f"  Key cookies MISSING: {', '.join(missing)}")

        return cookie_string

    def _extract_auth_token(self, driver: webdriver.Chrome) -> str:
        """
        Extract the Authorization Bearer token from captured network requests.

        Uses Chrome DevTools Protocol performance logs to find outgoing
        XHR requests to Upwork's API that contain the Authorization header.
        """
        try:
            logs = driver.get_log("performance")
        except Exception as e:
            logger.warning(f"  Warning: could not get performance logs: {e}")
            return ""

        for entry in logs:
            try:
                log_data = json.loads(entry["message"])
                message = log_data.get("message", {})

                # Look for Network.requestWillBeSent events
                if message.get("method") != "Network.requestWillBeSent":
                    continue

                params = message.get("params", {})
                request = params.get("request", {})
                url = request.get("url", "")

                # Only interested in requests to Upwork's API
                if "upwork.com/api" not in url:
                    continue

                headers = request.get("headers", {})

                # Check for the Authorization header (case-insensitive search)
                for header_name, header_value in headers.items():
                    if header_name.lower() == "authorization" and "bearer" in header_value.lower():
                        logger.info(f"  Found Bearer token in request to: {url[:80]}")
                        return header_value

            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        logger.warning("  Warning: No Authorization header found in any captured network request.")
        return ""




# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Run this file directly to test the refresh mechanism:
        python auth_manager.py
    """
    print("=" * 60)
    print("  AuthManager — Standalone Test")
    print("=" * 60)
    print()

    # Use the same User-Agent as the scraper
    test_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    )

    mgr = AuthManager(user_agent=test_ua)

    print(f"should_refresh() = {mgr.should_refresh()}  (should be True on first run)")
    print()

    result = mgr.refresh_session(reason="standalone test")
    if result:
        auth_header, cookie_string = result
        print()
        print("-" * 60)
        print(f"Authorization header length: {len(auth_header)} chars")
        print(f"Cookie string length: {len(cookie_string)} chars")
        print("-" * 60)
        print()
        print(f"should_refresh() = {mgr.should_refresh()}  (should be False right after refresh)")
    else:
        print()
        print("[FAIL] Refresh returned None — check the error logs above.")
