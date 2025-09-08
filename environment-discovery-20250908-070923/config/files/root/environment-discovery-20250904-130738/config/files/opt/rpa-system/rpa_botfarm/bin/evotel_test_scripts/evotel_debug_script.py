#!/usr/bin/env python3
"""
Evotel Debug Script - Helps identify the exact issue with portal interaction
"""
import os
import sys
import time
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def create_debug_driver():
    """Create a Chrome driver for debugging"""
    options = ChromeOptions()
    
    # VISIBLE mode for debugging
    logger.info("Running Chrome in VISIBLE mode for debugging")
    
    # Basic stable options
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--start-maximized')
    
    # Reduce crash potential
    options.add_argument('--disable-crash-reporter')
    options.add_argument('--disable-logging')
    options.add_argument('--log-level=3')
    
    service = Service(executable_path=Config.CHROMEDRIVER_PATH)
    driver = webdriver.Chrome(service=service, options=options)
    
    driver.set_page_load_timeout(30)
    driver.implicitly_wait(5)
    
    return driver

def debug_login_process(driver):
    """Debug the login process step by step"""
    logger.info("=== DEBUGGING LOGIN PROCESS ===")
    
    try:
        # Navigate to login page
        logger.info("Navigating to Evotel login page...")
        driver.get(Config.EVOTEL_URL)
        
        # Wait for page load
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        logger.info("✓ Login page loaded")
        
        # Take screenshot
        driver.save_screenshot("debug_01_login_page.png")
        logger.info("✓ Screenshot saved: debug_01_login_page.png")
        
        # Find email field
        logger.info("Looking for email field...")
        email_field = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "#Email"))
        )
        logger.info("✓ Email field found")
        
        # Enter email
        email_field.clear()
        email_field.send_keys(Config.EVOTEL_EMAIL)
        logger.info("✓ Email entered")
        
        # Find password field
        logger.info("Looking for password field...")
        password_field = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "#Password"))
        )
        logger.info("✓ Password field found")
        
        # Enter password
        password_field.clear()
        password_field.send_keys(Config.EVOTEL_PASSWORD)
        logger.info("✓ Password entered")
        
        # Take screenshot before login
        driver.save_screenshot("debug_02_before_login.png")
        logger.info("✓ Screenshot saved: debug_02_before_login.png")
        
        # Find and click login button
        logger.info("Looking for login button...")
        login_button = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, "//*[@id='loginForm']/form/div[4]/div/button"))
        )
        logger.info("✓ Login button found")
        
        login_button.click()
        logger.info("✓ Login button clicked")
        
        # Wait for redirect
        logger.info("Waiting for login redirect...")
        WebDriverWait(driver, 20).until(
            EC.url_contains("/Manage/Index")
        )
        logger.info("✓ Login successful - redirected to Manage page")
        
        # Take screenshot after login
        driver.save_screenshot("debug_03_after_login.png")
        logger.info("✓ Screenshot saved: debug_03_after_login.png")
        
        return True
        
    except Exception as e:
        logger.error(f"Login debug failed: {str(e)}")
        driver.save_screenshot("debug_login_error.png")
        return False

def debug_search_process(driver, serial_number="48575443D9B290B1"):
    """Debug the search process step by step"""
    logger.info("=== DEBUGGING SEARCH PROCESS ===")
    
    try:
        # Find search field
        logger.info("Looking for search field...")
        
        # Get page source for analysis
        page_source = driver.page_source
        logger.info(f"Page source length: {len(page_source)}")
        
        # Look for search field with multiple methods
        search_field = None
        search_selectors = [
            "#SearchString",
            "input[name='SearchString']",
            "input[id='SearchString']"
        ]
        
        for selector in search_selectors:
            try:
                search_field = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                logger.info(f"✓ Search field found using: {selector}")
                break
            except TimeoutException:
                logger.warning(f"Search field not found with: {selector}")
                continue
        
        if not search_field:
            logger.error("✗ Search field not found with any selector")
            
            # Debug: Print all input elements
            inputs = driver.find_elements(By.TAG_NAME, "input")
            logger.info(f"Found {len(inputs)} input elements:")
            for i, inp in enumerate(inputs):
                try:
                    inp_id = inp.get_attribute("id")
                    inp_name = inp.get_attribute("name")
                    inp_type = inp.get_attribute("type")
                    inp_class = inp.get_attribute("class")
                    logger.info(f"  Input {i}: id='{inp_id}', name='{inp_name}', type='{inp_type}', class='{inp_class}'")
                except:
                    logger.info(f"  Input {i}: Could not get attributes")
            
            return False
        
        # Take screenshot before search
        driver.save_screenshot("debug_04_before_search.png")
        logger.info("✓ Screenshot saved: debug_04_before_search.png")
        
        # Test different input methods
        logger.info("Testing search field interaction...")
        
        # Method 1: Direct input
        try:
            logger.info("Trying Method 1: Direct clear and send_keys")
            search_field.clear()
            time.sleep(0.5)
            search_field.send_keys(serial_number)
            logger.info("✓ Method 1 successful")
            
            # Verify value was entered
            field_value = search_field.get_attribute("value")
            logger.info(f"Field value after Method 1: '{field_value}'")
            
        except Exception as e:
            logger.error(f"✗ Method 1 failed: {e}")
            
            # Method 2: JavaScript
            try:
                logger.info("Trying Method 2: JavaScript")
                driver.execute_script("arguments[0].value = '';", search_field)
                driver.execute_script("arguments[0].focus();", search_field)
                time.sleep(0.5)
                
                # Type character by character
                for char in serial_number:
                    search_field.send_keys(char)
                    time.sleep(0.1)
                
                logger.info("✓ Method 2 successful")
                
                # Verify value
                field_value = search_field.get_attribute("value")
                logger.info(f"Field value after Method 2: '{field_value}'")
                
            except Exception as e2:
                logger.error(f"✗ Method 2 also failed: {e2}")
                return False
        
        # Take screenshot after entering text
        driver.save_screenshot("debug_05_text_entered.png")
        logger.info("✓ Screenshot saved: debug_05_text_entered.png")
        
        # Find search button
        logger.info("Looking for search button...")
        search_button = None
        search_button_selectors = [
            "#btnSearch",
            "input[id='btnSearch']",
            "button[id='btnSearch']"
        ]
        
        for selector in search_button_selectors:
            try:
                search_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                logger.info(f"✓ Search button found using: {selector}")
                break
            except TimeoutException:
                logger.warning(f"Search button not found with: {selector}")
                continue
        
        if not search_button:
            logger.error("✗ Search button not found")
            
            # Debug: Print all buttons
            buttons = driver.find_elements(By.TAG_NAME, "button")
            inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='button'], input[type='submit']")
            all_clickable = buttons + inputs
            
            logger.info(f"Found {len(all_clickable)} clickable elements:")
            for i, elem in enumerate(all_clickable):
                try:
                    elem_id = elem.get_attribute("id")
                    elem_text = elem.text or elem.get_attribute("value")
                    elem_type = elem.get_attribute("type")
                    logger.info(f"  Element {i}: id='{elem_id}', text='{elem_text}', type='{elem_type}'")
                except:
                    logger.info(f"  Element {i}: Could not get attributes")
            
            # Try Enter key as fallback
            logger.info("Trying Enter key as fallback...")
            search_field.send_keys(Keys.RETURN)
            
        else:
            # Click search button
            logger.info("Clicking search button...")
            search_button.click()
            logger.info("✓ Search button clicked")
        
        # Wait for search results
        logger.info("Waiting for search results...")
        try:
            WebDriverWait(driver, 20).until(
                lambda d: (
                    "/Search" in d.current_url or
                    d.find_elements(By.ID, "WebGrid") or
                    "no results" in d.page_source.lower()
                )
            )
            logger.info("✓ Search results loaded")
            
            # Take screenshot of results
            driver.save_screenshot("debug_06_search_results.png")
            logger.info("✓ Screenshot saved: debug_06_search_results.png")
            
            # Analyze results
            current_url = driver.current_url
            logger.info(f"Current URL: {current_url}")
            
            # Look for results table
            webgrid = driver.find_elements(By.ID, "WebGrid")
            if webgrid:
                logger.info("✓ WebGrid found")
                
                # Look for service links
                service_links = driver.find_elements(By.XPATH, "//*[@id='WebGrid']/tbody/tr/td[3]/a")
                logger.info(f"Found {len(service_links)} service links")
                
                for i, link in enumerate(service_links[:3]):  # Show first 3
                    try:
                        link_text = link.text
                        link_href = link.get_attribute("href")
                        logger.info(f"  Service {i+1}: '{link_text}' -> {link_href}")
                    except:
                        logger.info(f"  Service {i+1}: Could not get link details")
                
                return True
            else:
                logger.warning("WebGrid not found - checking for no results")
                page_text = driver.page_source.lower()
                if "no results" in page_text or "not found" in page_text:
                    logger.info("No search results found (expected for some serial numbers)")
                    return True
                else:
                    logger.warning("Unknown search result state")
                    return False
                    
        except TimeoutException:
            logger.error("✗ Search results did not load within timeout")
            driver.save_screenshot("debug_search_timeout.png")
            logger.info("Screenshot saved: debug_search_timeout.png")
            return False
        
    except Exception as e:
        logger.error(f"Search debug failed: {str(e)}")
        driver.save_screenshot("debug_search_error.png")
        import traceback
        logger.error(traceback.format_exc())
        return False

def main():
    """Main debug function"""
    logger.info("=" * 60)
    logger.info("EVOTEL PORTAL DEBUG SESSION")
    logger.info("=" * 60)
    
    driver = None
    try:
        # Create driver
        logger.info("Creating debug browser...")
        driver = create_debug_driver()
        logger.info("✓ Debug browser created")
        
        # Debug login
        if debug_login_process(driver):
            logger.info("✓ Login debug completed successfully")
            
            # Debug search
            if debug_search_process(driver):
                logger.info("✓ Search debug completed successfully")
                
                logger.info("\n" + "=" * 60)
                logger.info("✓ ALL DEBUG TESTS PASSED")
                logger.info("The Evotel portal interaction is working correctly.")
                logger.info("The original error might be related to timing or Chrome stability.")
                logger.info("=" * 60)
                
            else:
                logger.error("\n" + "=" * 60)
                logger.error("✗ SEARCH DEBUG FAILED")
                logger.error("Check the search-related screenshots and logs above.")
                logger.error("=" * 60)
        else:
            logger.error("\n" + "=" * 60)
            logger.error("✗ LOGIN DEBUG FAILED")
            logger.error("Check your Evotel credentials and network connectivity.")
            logger.error("=" * 60)
            
        # Keep browser open for manual inspection
        input("\nPress Enter to close the browser and exit...")
        
    except Exception as e:
        logger.error(f"Debug session failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
    finally:
        if driver:
            try:
                driver.quit()
                logger.info("Debug browser closed")
            except:
                pass

if __name__ == "__main__":
    main()