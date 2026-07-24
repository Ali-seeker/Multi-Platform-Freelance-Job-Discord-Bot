import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from logger import get_logger
from auth_manager import _build_options, _wait_for_cloudflare, UA_STRING

logger = get_logger(__name__)

def filter_public_jobs(jobs_list):
    """
    Takes a list of job dictionaries.
    Uses Selenium to open each job's URL and checks if it is a private listing.
    Returns a list of ONLY public jobs.
    Additionally, tries to extract the full description for public jobs.
    """
    if not jobs_list:
        return []

    public_jobs = []
    
    logger.info(f"🔍 Starting Selenium verification for {len(jobs_list)} new jobs...")
    
    options = _build_options(UA_STRING)
    # options.add_argument("--headless=new")
    # Set page load strategy to eager so it doesn't wait for all resources
    options.page_load_strategy = 'eager'
    
    driver = None
    for attempt in range(3):
        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(30)
            driver.set_window_size(1920, 1080)
            break
        except Exception as e:
            logger.warning(f"Failed to launch Chrome (attempt {attempt+1}): {e}")
            time.sleep(2)
            
    if not driver:
        logger.error("Could not launch Selenium after 3 attempts.")
        # Return all jobs assuming they are public so we don't miss anything, or return [] to block all?
        # Safe fallback: return jobs_list so we don't lose data on browser failure.
        return jobs_list
        
    try:
        
        # 1. Go to homepage to clear Cloudflare first
        logger.info("Navigating to Upwork homepage to clear Cloudflare...")
        try:
            driver.get("https://www.upwork.com/")
        except Exception as e:
            logger.warning(f"Timeout or error loading homepage: {e}")
        
        if not _wait_for_cloudflare(driver, timeout=45):
            logger.warning("Cloudflare bypass on homepage took too long or failed.")
            # We'll continue anyway, maybe the job pages will work
        
        # 2. Check each job
        for job in jobs_list:
            job_id = job.get('job_id')
            # Using freelance-jobs/apply/ URL as it often handles redirects better
            job_url = f"https://www.upwork.com/freelance-jobs/apply/{job_id}"
            
            logger.info(f"Checking job {job_id} at {job_url}...")
            try:
                driver.get(job_url)
            except Exception as e:
                logger.warning(f"Timeout or error loading job {job_id}: {e}")
            
            # Wait for Cloudflare on the job page if any
            _wait_for_cloudflare(driver, timeout=45)
            
            # Allow page content to render
            time.sleep(5)
            
            # Check if it's a private job
            is_private = False
            try:
                # The primary indicator of a private job
                driver.find_element(By.XPATH, "//img[@alt='Private listing']")
                is_private = True
            except:
                pass
                
            if is_private:
                logger.info(f"🚫 Job {job_id} is PRIVATE. Skipping.")
                continue
                
            logger.info(f"✅ Job {job_id} is PUBLIC.")
            
            public_jobs.append(job)
            
    except Exception as e:
        logger.error(f"Error during Selenium job verification: {e}")
    finally:
        try:
            driver.quit()
        except:
            pass
            
    logger.info(f"🏁 Verification complete. {len(public_jobs)} out of {len(jobs_list)} jobs are public.")
    return public_jobs
