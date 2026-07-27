import time
import asyncio
from typing import List, Dict
from selenium import webdriver
from selenium.webdriver.common.by import By

from auth_manager import _build_options, UA_STRING, STEALTH_JS, _wait_for_cloudflare
from logger import get_logger

logger = get_logger(__name__)

def verify_job_public(driver: webdriver.Chrome, job_id: str, ciphertext: str) -> bool:
    """
    Checks if a job page is public by navigating to its URL.
    Returns True if public, False if private/unavailable.
    """
    job_url = f"https://www.upwork.com/jobs/{ciphertext}"
    logger.info(f"Checking job {job_id} at {job_url}...")
    
    try:
        driver.get(job_url)
    except Exception as e:
        logger.error(f"Error navigating to job {job_id}: {e}")
        return True # By default, consider public
        
    if not _wait_for_cloudflare(driver, timeout=60):
        logger.debug(f"Cloudflare bypass timed out for job {job_id}.")
        return True # User requested to consider it public by default

    time.sleep(5)
    
    html = driver.page_source.lower()
    
    # Check using User's recommended XPaths for the forbidden image
    try:
        private_img = driver.find_elements(By.XPATH, "//img[@alt='Private listing'] | //img[contains(@src,'forbidden')] | //img[contains(@src,'/JobDetailsNuxt/_nuxt/forbidden')]")
        if private_img:
            logger.info(f"🔒 Job {job_id} is PRIVATE (found private listing image).")
            return False
    except Exception as e:
        pass
        
    # Check text indicators
    if "this job is a private listing" in html or "is no longer available" in html or "access is restricted" in html:
        logger.info(f"🔒 Job {job_id} is PRIVATE or UNAVAILABLE.")
        return False
        
    # Check public indicators
    try:
        if driver.find_elements(By.XPATH, "//div[contains(@class, 'job-description')] | //div[@data-test='job-description-text']"):
            logger.info(f"✅ Job {job_id} is PUBLIC.")
            return True
    except:
        pass
        
    # Default to assuming public if we got past CF but didn't find specific private markers
    logger.info(f"✅ Job {job_id} is PUBLIC.")
    return True

def filter_public_jobs(jobs: List[Dict]) -> List[Dict]:
    """
    Takes a list of jobs, uses Selenium to verify which are public,
    and returns only the public ones.
    """
    if not jobs:
        return []
        
    options = _build_options(UA_STRING)
    # Eager load strategy to skip waiting for tracking pixels
    options.page_load_strategy = 'eager'
    
    try:
        driver = webdriver.Chrome(options=options)
        driver.execute_cdp_cmd("Network.setUserAgentOverride", {
            "userAgent": UA_STRING,
            "platform": "Win32",
            "acceptLanguage": "en-US,en;q=0.9"
        })
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": STEALTH_JS})
        driver.set_page_load_timeout(45)
        driver.set_window_size(1920, 1080)
    except Exception as e:
        logger.error(f"Failed to initialize Selenium for job verification: {e}")
        return jobs # Fallback: return all jobs if Selenium fails
        
    public_jobs = []
    
    try:
        for job in jobs:
            job_id = job.get('job_id')
            ciphertext = job.get('ciphertext')
            if not ciphertext:
                # If no ciphertext, we can't check it via URL easily, just allow it
                public_jobs.append(job)
                continue
                
            is_public = verify_job_public(driver, job_id, ciphertext)
            if is_public:
                public_jobs.append(job)
    finally:
        driver.quit()
        
    logger.info(f"🏁 Verification complete. {len(public_jobs)} out of {len(jobs)} jobs are public.")
    return public_jobs
