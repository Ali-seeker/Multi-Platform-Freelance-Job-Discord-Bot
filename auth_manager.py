"""
auth_manager.py — Automatic visitor-session refresh for Upwork scraping.

Uses headless Selenium automation to extract fresh anonymous visitor session
credentials (Authorization header + Cookie string) to bypass Cloudflare.
"""

import time
import json
from datetime import datetime

from logger import get_logger
logger = get_logger(__name__)

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys

# ---------------------------------------------------------------------------
# Custom Exception
# ---------------------------------------------------------------------------

class SessionExpiredError(Exception):
    """
    Raised when a 401 or 403 response is received from Upwork's API,
    signaling that the session (Bearer token or Cloudflare cookies)
    has expired and needs to be refreshed.
    """
    pass

# ---------------------------------------------------------------------------
# Stealth Configuration
# ---------------------------------------------------------------------------

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
    Promise.resolve({state: Notification.permission}) :
    origQuery(parameters)
);
"""

UA_STRING = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

def _build_options(user_agent: str):
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument(f"--user-agent={user_agent}")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--enable-gpu")
    opts.add_argument("--use-gl=swiftshader")
    opts.add_argument("--disable-features=IsolateOrigins,site-per-process")
    opts.add_argument("--disable-web-security")
    opts.add_argument("--disable-features=BlockInsecurePrivateNetworkRequests")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=en-US")
    opts.add_argument("--accept-lang=en-US,en;q=0.9")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--disable-extensions")
    return opts

def _wait_for_cloudflare(driver, timeout=180):
    deadline = time.time() + timeout
    clicked = False
    while time.time() < deadline:
        # Use relative XPath to detect Cloudflare challenge presence instead of relying on page title
        cf_indicators = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'challenges.cloudflare.com') or contains(@title, 'challenge')] | //div[@id='challenge-stage' or contains(@class, 'cf-turnstile')]")
        
        if not cf_indicators:
            # If no Cloudflare indicators are found and body exists, we assume it's bypassed/safe
            if driver.find_elements(By.XPATH, "//body"):
                return True

        try:
            iframes = driver.find_elements(By.XPATH, "//iframe[contains(@src, 'challenges.cloudflare.com') or contains(@title, 'challenge')]")
            for iframe in iframes:
                driver.switch_to.frame(iframe)
                try:
                    # Locate click targets inside the iframe using XPath (including robust text-based XPath)
                    targets = driver.find_elements(By.XPATH, "//label[.//span[normalize-space()='Verify you are human']] | //label[contains(@class, 'ctp-checkbox-label')] | //input[@type='checkbox'] | //*[contains(@class, 'cb-lb')] | //*[@id='challenge-stage'] | //*[contains(@class, 'mark')] | //body")
                    for el in targets:
                        if el.is_displayed():
                            ActionChains(driver).move_to_element(el).click().perform()
                            logger.info("🛡️ Bypassed Cloudflare verification")
                            clicked = True
                            break
                    if clicked:
                        break
                except Exception:
                    pass
                finally:
                    driver.switch_to.default_content()
        except Exception:
            pass
        if not clicked:
            try:
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.SPACE)
            except Exception:
                pass
        time.sleep(4)
    return False

# ---------------------------------------------------------------------------
# AuthManager
# ---------------------------------------------------------------------------

class AuthManager:
    """
    Manages automatic refresh of Upwork visitor session credentials using a
    headless Selenium browser.
    """

    def __init__(self, user_agent: str = UA_STRING, session_lifetime: int = 39600):
        # 39600 seconds = 11 hours
        self.user_agent = user_agent
        self.session_lifetime = session_lifetime
        self.session_timestamp: datetime | None = None

    def should_refresh(self) -> bool:
        """Check if a proactive refresh is due."""
        if self.session_timestamp is None:
            return True

        elapsed = (datetime.now() - self.session_timestamp).total_seconds()
        return elapsed >= self.session_lifetime

    def refresh_session(self, reason: str = "proactive") -> tuple[str, str] | None:
        """
        Refresh orchestrator.
        """
        logger.info(f"🔄 Session refresh triggered ({reason})")

        for attempt in range(1, 4):
            driver = None
            try:
                logger.info(f"🌐 [Attempt {attempt}/3] Headless browser launched, fetching credentials...")

                options = _build_options(self.user_agent)
                driver = webdriver.Chrome(options=options)

                driver.execute_cdp_cmd("Network.setUserAgentOverride", {
                    "userAgent": self.user_agent,
                    "platform": "Win32",
                    "acceptLanguage": "en-US,en;q=0.9"
                })

                driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": STEALTH_JS})
                driver.set_window_size(1920, 1080)
                
                # Removing the verbose navigating and loaded logs:
                # logger.info("Navigating to Upwork homepage...")
                driver.get("https://www.upwork.com")

                if not _wait_for_cloudflare(driver, timeout=180):
                    logger.warning(f"⚠️ Cloudflare failed (Attempt {attempt}). Retrying...")
                    driver.quit()
                    time.sleep(15)
                    continue

                # logger.info(f"Homepage loaded. URL: {driver.current_url}, Title: {driver.title}")
                # logger.info("Waiting for homepage JS to settle...")
                time.sleep(10)

                raw_cookies = driver.get_cookies()
                new_cookies = {c['name']: c['value'] for c in raw_cookies}

                new_oauth_token = None
                token_source = "none"

                if new_cookies.get('visitor_gql_token'):
                    new_oauth_token = new_cookies['visitor_gql_token']
                    token_source = "visitor_gql_token cookie"

                if not new_oauth_token:
                    ls_token = driver.execute_script(
                        "return localStorage.getItem('oauth2_global_js_token') "
                        "|| localStorage.getItem('oauth2_access_token');"
                    )
                    if ls_token:
                        new_oauth_token = ls_token
                        token_source = "localStorage"

                if not new_oauth_token and new_cookies.get('oauth2_global_js_token'):
                    new_oauth_token = new_cookies['oauth2_global_js_token']
                    token_source = "oauth2_global_js_token cookie"

                if not new_oauth_token:
                    logger.warning("No OAuth token found. Retrying...")
                    driver.quit()
                    time.sleep(15)
                    continue

                logger.info(f"🔑 Auth token extracted (Source: {token_source})")

                cookie_string = "; ".join(f"{c['name']}={c['value']}" for c in raw_cookies)
                auth_header = f"Bearer {new_oauth_token}"
                
                self.session_timestamp = datetime.now()
                logger.info("✅ Credentials refreshed successfully")
                
                driver.quit()
                return auth_header, cookie_string

            except Exception as e:
                logger.error(f"Browser launch error (attempt {attempt}): {e}", exc_info=True)
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                if attempt < 3:
                    logger.info("Retrying in 15 seconds...")
                    time.sleep(15)

        logger.error("All 3 launch attempts failed.")
        return None

    def fetch_job_html(self, ciphertext: str) -> str | None:
        """
        Fetches the raw HTML for a specific job page using a headless browser to bypass
        Cloudflare's strict Turnstile on the HTML pages.
        """
        logger.info(f"🌐 Fetching HTML for {ciphertext} using Headless Selenium...")
        driver = None
        for attempt in range(1, 3):
            try:
                options = _build_options(self.user_agent)
                driver = webdriver.Chrome(options=options)
                driver.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": self.user_agent})
                driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": STEALTH_JS})
                driver.set_page_load_timeout(30)
                
                url = f"https://www.upwork.com/jobs/{ciphertext}"
                driver.get(url)
                
                # Wait for Cloudflare if necessary
                _wait_for_cloudflare(driver, timeout=60)
                
                # Wait a bit for Next.js to render
                time.sleep(3)
                
                html = driver.page_source
                driver.quit()
                return html
            except Exception as e:
                logger.error(f"Error fetching HTML for {ciphertext}: {e}")
                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
        return None

auth_manager = AuthManager()
