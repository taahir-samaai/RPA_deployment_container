"""
MFN Portal Automation Module
----------------------------
Handles service validation operations on the MetroFiber portal.
This module implements the execution interface expected by the worker system.
"""

import base64
import re
import os
import time
import logging
import traceback
from datetime import datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    TimeoutException, 
    NoSuchElementException, 
    WebDriverException,
    ElementClickInterceptedException
)
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

from config import Config

# Configure logging
logger = logging.getLogger(__name__)

class MetroFiberAutomation:
    """Class to handle MetroFiber portal automation"""
    
    def __init__(self, job_id):
        """Initialize the automation with job tracking"""
        self.job_id = job_id
        self.driver = None
        self.service_location = None  # Track where we found the service
        
        # Use job-specific screenshot directory from centralized config
        self.screenshot_dir = Path(Config.get_job_screenshot_dir(job_id))
        self.screenshots = []  # Initialize the list to store screenshot data
        self.execution_summary_path = Config.get_execution_summary_path(job_id)
        
        # Set up job-specific logger
        self.logger = Config.setup_logging(f"mfn_automation_{job_id}")
        
        # Load credentials from Config
        self.portal_url = Config.METROFIBER_URL
        self.email = Config.EMAIL
        self.password = Config.PASSWORD
        
        # Retry and timeout settings
        self.LOGIN_RETRY_ATTEMPTS = int(os.getenv("LOGIN_RETRY_ATTEMPTS", "3"))
        self.LOGIN_RETRY_MIN_WAIT = int(os.getenv("LOGIN_RETRY_MIN_WAIT", "2"))
        self.LOGIN_RETRY_MAX_WAIT = int(os.getenv("LOGIN_RETRY_MAX_WAIT", "10"))
        self.SEARCH_RETRY_ATTEMPTS = int(os.getenv("SEARCH_RETRY_ATTEMPTS", "3"))
        self.SEARCH_RETRY_MIN_WAIT = int(os.getenv("SEARCH_RETRY_MIN_WAIT", "2"))
        self.SEARCH_RETRY_MAX_WAIT = int(os.getenv("SEARCH_RETRY_MAX_WAIT", "10"))
        self.WAIT_TIMEOUT = int(os.getenv("WAIT_TIMEOUT", "15"))
        
        # Elements to extract (from improved version)
        self.elements_to_extract = [
            "id", "username", "customerTypeInfo", "customer", "customer_id_number", "mail",
            "home_number", "mobile_number", "office_number", "po_number", "install_name",
            "install_number", "install_email", "start_date_enter", "install_time", "area_detail",
            "complex_detail", "ad1", "port_detail", "resel", "originalbw", "device_type",
            "actual_device_type", "iptype", "originalip", "fsan", "mac", "activation",
            "systemDate", "price_nrc", "price_mrc", "package_upgrade_mrc", "exp_date"
        ]
        
        if not all([self.portal_url, self.email, self.password]):
            raise ValueError("Missing required configuration for MFN Portal access")
            
        self.logger.info(f"Job {job_id}: MetroFiberAutomation initialized with job-specific screenshot directory")

    def take_screenshot(self, name):
        """
        Capture screenshot for evidence and encode in base64
        
        Args:
            name: Descriptive name for the screenshot
            
        Returns:
            dict: Screenshot metadata including base64 encoded image
        """
        if not self.driver:
            self.logger.warning(f"Job {self.job_id}: Cannot take screenshot - no WebDriver")
            return None
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.job_id}_{name}_{timestamp}.png"
        filepath = self.screenshot_dir / filename
        
        try:
            # Take the screenshot
            self.driver.save_screenshot(str(filepath))
            self.logger.info(f"Job {self.job_id}: Screenshot saved to {filepath}")
            
            # Read the file and encode to base64
            with open(filepath, "rb") as img_file:
                b64_string = base64.b64encode(img_file.read()).decode('utf-8')
            
            # Store screenshot metadata and encoded image
            screenshot_data = {
                "name": name,
                "timestamp": timestamp,
                "filepath": str(filepath),
                "base64_data": b64_string,
                "mime_type": "image/png",
                "description": f"Screenshot: {name}"
            }
            
            # Add to screenshots list
            self.screenshots.append(screenshot_data)
            
            return screenshot_data
        except Exception as e:
            self.logger.error(f"Job {self.job_id}: Failed to take screenshot: {str(e)}")
            return None

    def initialize_driver(self):
        """Initialize Chrome driver with Cloudflare bypass optimizations"""
        try:
            if self.driver:
                self.driver.quit()
                
            import platform
            chrome_options = Options()
            
            # Basic Chrome options from Config
            if Config.START_MAXIMIZED:
                chrome_options.add_argument("--start-maximized")
            if Config.NO_SANDBOX:
                chrome_options.add_argument("--no-sandbox")
            if Config.DISABLE_DEV_SHM_USAGE:
                chrome_options.add_argument("--disable-dev-shm-usage")
            
            # CLOUDFLARE BYPASS - CRITICAL ADDITIONS
            chrome_options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            # Additional stealth options
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-plugins")
            chrome_options.add_argument("--window-size=1920,1080")
            
            # Handle headless mode
            if Config.HEADLESS:
                logger.info("Running in headless mode")
                chrome_options.add_argument("--headless=new")
            else:
                logger.info("Running in visible mode")
            
            # Use Config for driver path
            driver_path = Config.CHROMEDRIVER_PATH
            logger.info(f"Using ChromeDriver path: {driver_path}")
            
            from selenium.webdriver.chrome.service import Service
            service = Service(executable_path=driver_path)
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # CRITICAL: Remove webdriver property that Cloudflare detects
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            # Set longer timeouts for Cloudflare challenges
            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(10)
            self.driver.set_window_size(1920, 1080)
            
            logger.info(f"Job {self.job_id}: WebDriver initialized with Cloudflare bypass on {platform.system()}")
            return True
            
        except WebDriverException as e:
            logger.error(f"Job {self.job_id}: Failed to initialize WebDriver: {str(e)}")
            logger.error(f"Driver path attempted: {Config.CHROMEDRIVER_PATH}")
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None
            return False
    @retry(
        stop=stop_after_attempt(3),  # using class variable would be cleaner
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((TimeoutException, WebDriverException)),
        before_sleep=before_sleep_log(logger, logging.INFO)
    )
    def login(self):
        """Login to MetroFiber portal with retry capability"""
        self.driver.get(self.portal_url)
        logger.info(f"Job {self.job_id}: Navigated to MetroFiber portal")
        
        wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
        
        # Wait for and interact with login elements
        username_input = wait.until(EC.presence_of_element_located((By.ID, "username")))
        password_input = self.driver.find_element(By.ID, "password")
        login_button = self.driver.find_element(By.CLASS_NAME, "btnLogin")
        
        # Enter credentials
        username_input.clear()
        username_input.send_keys(self.email)
        password_input.clear()
        password_input.send_keys(self.password)
        
        # Take screenshot before login
        self.take_screenshot("pre_login")
        
        # Click login
        login_button.click()
        
        # Verify successful login by checking for an element that exists post-login
        wait.until(EC.presence_of_element_located((By.XPATH, "//a[@href='customers.php']")))
        logger.info(f"Job {self.job_id}: Successfully logged in to MetroFiber portal")
        
        # Take screenshot after login
        self.take_screenshot("post_login")
        return True
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((TimeoutException, ElementClickInterceptedException)),
        before_sleep=before_sleep_log(logger, logging.INFO)
    )
    def search_customer(self, circuit_number="", customer_name="", customer_id="", fsan=""):
        """
        Search for customer with fallback strategy.
        First tries active services, then deactivated services.
        """
        logger.info(f"Job {self.job_id}: Searching for customer - Circuit: {circuit_number}, Name: {customer_name}")

        def try_active_services_search():
            """Attempt to search in active services - UPDATED FOR NEW PORTAL STRUCTURE"""
            try:
                # Navigate to customer search in active services
                active_services = WebDriverWait(self.driver, self.WAIT_TIMEOUT).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[@href='customers.php']"))
                )
                active_services.click()
                logger.info(f"Job {self.job_id}: Navigated to Active Services")
                
                # Wait for search form
                wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
                
                # Fill search fields if provided
                if circuit_number:
                    circuit_input = wait.until(EC.presence_of_element_located((By.ID, "circuit_search")))
                    circuit_input.clear()
                    circuit_input.send_keys(circuit_number)
                
                if customer_name:
                    name_input = self.driver.find_element(By.ID, "name_search")
                    name_input.clear()
                    name_input.send_keys(customer_name)
                
                if customer_id:
                    id_input = self.driver.find_element(By.ID, "id_search")
                    id_input.clear()
                    id_input.send_keys(customer_id)
                    
                if fsan:
                    fsan_input = self.driver.find_element(By.ID, "fsan_search")
                    fsan_input.clear()
                    fsan_input.send_keys(fsan)
                
                # Take screenshot before search
                self.take_screenshot("active_services_search_form")
                
                # UPDATED: Click the new search button (button element instead of input)
                search_button = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//button[@type='submit' and @class='btn btn-primary' and text()='Search']")
                ))
                search_button.click()
                logger.info(f"Job {self.job_id}: Active Services search submitted")
                
                # NEW: Handle DataTables popups that appear twice in succession
                self._handle_datatables_popups()
                
                # Wait for results table to load (updated table ID)
                wait.until(EC.visibility_of_element_located(
                    (By.XPATH, "//table[@id='customersTable']/tbody/tr[1]")
                ))
                
                # NEW: Scroll down to ensure search results are visible
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
                time.sleep(1)
                
                # Take screenshot of search results
                self.take_screenshot("active_services_search_results")
                
                # Check if we have results (updated table ID)
                rows = self.driver.find_elements(By.XPATH, "//table[@id='customersTable']/tbody/tr")
                if rows:
                    # Filter out any "no data" rows
                    actual_rows = [row for row in rows if "No matching records found" not in row.text]
                    if actual_rows:
                        logger.info(f"Job {self.job_id}: Found {len(actual_rows)} results in Active Services")
                        return True
                
                logger.info(f"Job {self.job_id}: No results found in Active Services")
                return False
            
            except Exception as e:
                logger.warning(f"Job {self.job_id}: Active Services search failed: {str(e)}")
                return False
    
        def try_active_services_search():
            """Attempt to search in active services - UPDATED FOR NEW PORTAL STRUCTURE"""
            try:
                # Navigate to customer search in active services
                active_services = WebDriverWait(self.driver, self.WAIT_TIMEOUT).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[@href='customers.php']"))
                )
                active_services.click()
                logger.info(f"Job {self.job_id}: Navigated to Active Services")
                
                # Wait for search form
                wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
                
                # Fill search fields if provided
                if circuit_number:
                    circuit_input = wait.until(EC.presence_of_element_located((By.ID, "circuit_search")))
                    circuit_input.clear()
                    circuit_input.send_keys(circuit_number)
                
                if customer_name:
                    name_input = self.driver.find_element(By.ID, "name_search")
                    name_input.clear()
                    name_input.send_keys(customer_name)
                
                if customer_id:
                    id_input = self.driver.find_element(By.ID, "id_search")
                    id_input.clear()
                    id_input.send_keys(customer_id)
                    
                if fsan:
                    fsan_input = self.driver.find_element(By.ID, "fsan_search")
                    fsan_input.clear()
                    fsan_input.send_keys(fsan)
                
                # Take screenshot before search
                self.take_screenshot("active_services_search_form")
                
                # UPDATED: Click the new search button (button element instead of input)
                search_button = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//button[@type='submit' and @class='btn btn-primary' and text()='Search']")
                ))
                search_button.click()
                logger.info(f"Job {self.job_id}: Active Services search submitted")
                
                # NEW: Handle DataTables popups that appear twice in succession
                self._handle_datatables_popups()
                
                # Wait for results table to load (updated table ID)
                wait.until(EC.visibility_of_element_located(
                    (By.XPATH, "//table[@id='customersTable']/tbody/tr[1]")
                ))
                
                # NEW: Scroll down to ensure search results are visible
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
                time.sleep(1)
                
                # Take screenshot of search results
                self.take_screenshot("active_services_search_results")
                
                # Check if we have results (updated table ID)
                rows = self.driver.find_elements(By.XPATH, "//table[@id='customersTable']/tbody/tr")
                if rows:
                    # Filter out any "no data" rows
                    actual_rows = [row for row in rows if "No matching records found" not in row.text]
                    if actual_rows:
                        logger.info(f"Job {self.job_id}: Found {len(actual_rows)} results in Active Services")
                        return True
                
                logger.info(f"Job {self.job_id}: No results found in Active Services")
                return False
            
            except Exception as e:
                logger.warning(f"Job {self.job_id}: Active Services search failed: {str(e)}")
                return False



        def try_deactivated_services_search():
            """Attempt to search in deactivated services"""
            try:
                # Exit current view if needed
                try:
                    exit_link = WebDriverWait(self.driver, self.WAIT_TIMEOUT).until(
                        EC.element_to_be_clickable((By.XPATH, "//a[@href='main.php']"))
                    )
                    exit_link.click()
                    logger.info(f"Job {self.job_id}: Clicked Exit link")
                except Exception as e:
                    logger.warning(f"Job {self.job_id}: Could not click Exit link: {str(e)}")

                # Navigate to Deactivated Services
                deactivated_services = WebDriverWait(self.driver, self.WAIT_TIMEOUT).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[@href='inactive_customers.php']"))
                )
                deactivated_services.click()
                logger.info(f"Job {self.job_id}: Navigated to Deactivated Services")

                # Wait for page to load
                wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)

                # Add first condition (Circuit Number)
                add_condition_buttons = wait.until(
                    EC.presence_of_all_elements_located((By.XPATH, "//button[contains(@class, 'btn-secondary dtsb-add dtsb-button')]"))
                )

                # Click first Add Condition button
                add_condition_buttons[0].click()
                logger.info(f"Job {self.job_id}: Clicked first Add Condition button")

                # Wait for dropdown and select Circuit Number
                circuit_number_option = wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'dtsb-criteria')]//option[contains(text(), 'Circuit Number')]"))
                )
                circuit_number_option.click()
                logger.info(f"Job {self.job_id}: Selected Circuit Number condition")

                # Wait for condition to be added
                time.sleep(1)  

                # Click the second Add Condition button to open condition dropdown
                add_condition_buttons = self.driver.find_elements(By.XPATH, "//button[contains(@class, 'btn-secondary dtsb-add dtsb-button')]")
                if len(add_condition_buttons) > 1:
                    add_condition_buttons[1].click()
                    logger.info(f"Job {self.job_id}: Clicked second Add Condition button")

                # Select "Equals" condition
                condition_dropdown = wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//select[contains(@class, 'dtsb-condition dtsb-dropDown')]"))
                )
                condition_dropdown.click()

                # Choose "Equals" option
                equals_option = wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//select[contains(@class, 'dtsb-condition dtsb-dropDown')]/option[@value='=']"))
                )
                equals_option.click()
                logger.info(f"Job {self.job_id}: Selected 'Equals' condition")

                # Find and enter circuit number input
                circuit_input = wait.until(
                    EC.presence_of_element_located((By.XPATH, "//input[contains(@class, 'dtsb-value form-control dtsb-input')]"))
                )
                circuit_input.clear()
                circuit_input.send_keys(circuit_number)
                logger.info(f"Job {self.job_id}: Entered circuit number '{circuit_number}'")

                # Take screenshot of condition setup
                self.take_screenshot("deactivated_services_condition_setup")
                
                # Execute the search
                # Execute the search (automatic on input)
                logger.info(f"Job {self.job_id}: Search executes automatically on input")
                time.sleep(3)  # Wait for auto-filter to complete

                # Verify correct circuit appears
                try:
                    circuit_cell = wait.until(
                        EC.presence_of_element_located(
                            (By.XPATH, f"//td[contains(text(), '{circuit_number}')]")
                        )
                    )
                    logger.info(f"Job {self.job_id}: Found circuit {circuit_number} in deactivated services")
                    
                    self.service_location = "inactive"
                    self.take_screenshot("deactivated_services_filtered_results")
                    
                    return True
                    
                except TimeoutException:
                    logger.error(f"Job {self.job_id}: Circuit {circuit_number} not found in deactivated services")
                    return False
                    
            except Exception as e:
                logger.error(f"Job {self.job_id}: Deactivated Services search failed: {str(e)}")
                return False


        # Try active services search first
        if try_active_services_search():
            return True
    
        # If active services search fails, try deactivated services
        if try_deactivated_services_search():
            return True
    
        # Log failure if both searches fail
        logger.warning(f"Job {self.job_id}: Could not find customer in Active or Deactivated Services")
        return False

    def _handle_datatables_popups(self):
        """Handle DataTables warning popups that appear twice in succession"""
        try:
            logger.info(f"Job {self.job_id}: Checking for DataTables popups")
            
            # Wait a moment for popups to potentially appear
            time.sleep(2)
            
            for attempt in range(2):  # Handle up to 2 popups
                try:
                    # Look for various types of alert/popup elements
                    popup_selectors = [
                        "//div[contains(@class, 'alert')]",
                        "//div[contains(@class, 'modal')]", 
                        "//div[contains(text(), 'DataTables warning')]",
                        "//button[text()='OK']",
                        "//button[contains(@class, 'btn') and (text()='OK' or text()='Close')]"
                    ]
                    
                    popup_found = False
                    for selector in popup_selectors:
                        try:
                            popup_element = WebDriverWait(self.driver, 3).until(
                                EC.element_to_be_clickable((By.XPATH, selector))
                            )
                            if popup_element.is_displayed():
                                popup_element.click()
                                logger.info(f"Job {self.job_id}: Dismissed DataTables popup {attempt + 1}")
                                popup_found = True
                                time.sleep(1)
                                break
                        except TimeoutException:
                            continue
                        except Exception as e:
                            logger.debug(f"Job {self.job_id}: Error with popup selector {selector}: {str(e)}")
                            continue
                    
                    if not popup_found:
                        # Try JavaScript approach to dismiss any alerts
                        try:
                            self.driver.switch_to.alert.accept()
                            logger.info(f"Job {self.job_id}: Dismissed JavaScript alert {attempt + 1}")
                            time.sleep(1)
                        except:
                            # No alert present, break the loop
                            break
                            
                except Exception as e:
                    logger.debug(f"Job {self.job_id}: No popup found on attempt {attempt + 1}: {str(e)}")
                    break
        
        except Exception as e:
            logger.warning(f"Job {self.job_id}: Error handling DataTables popups: {str(e)}")

    def select_first_result(self):
        """Select the first result from search results - UPDATED FOR NEW TABLE STRUCTURE"""
        try:
            # Take screenshot before attempting to select row
            self.take_screenshot("before_row_selection")
            
            logger.info(f"Job {self.job_id}: Looking for results in Active Services table")
            
            # UPDATED: Use new table ID and look for the specific row structure
            wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
            
            # Wait for table to be ready
            wait.until(EC.visibility_of_element_located(
                (By.XPATH, "//table[@id='customersTable']/tbody/tr[1]")
            ))
            
            # Find all rows in the new table structure
            active_services_rows = self.driver.find_elements(
                By.XPATH, "//table[@id='customersTable']/tbody/tr"
            )
            
            if active_services_rows:
                logger.info(f"Job {self.job_id}: Found {len(active_services_rows)} rows in Active Services table")
                
                # Get the first row (filter out any empty or "no data" rows)
                first_row = None
                for row in active_services_rows:
                    if row.text and "No matching records found" not in row.text:
                        first_row = row
                        break
                
                if not first_row:
                    logger.error(f"Job {self.job_id}: No valid data rows found")
                    return False
                
                # Log the row content for debugging
                row_text = first_row.text
                logger.info(f"Job {self.job_id}: First row content: {row_text}")
                
                # Ensure row is visible
                self.driver.execute_script("arguments[0].scrollIntoView(true);", first_row)
                time.sleep(1)
                
                # Method 1: Try double-click on the first cell (ID column)
                try:
                    logger.info(f"Job {self.job_id}: Attempting double-click on first cell")
                    first_cell = first_row.find_element(By.XPATH, "./td[1]")
                    
                    actions = ActionChains(self.driver)
                    actions.double_click(first_cell).perform()
                    time.sleep(3)  # Wait for page to load
                    
                    self.take_screenshot("after_first_cell_doubleclick")
                    
                    # Check if we navigated to detail page
                    if "customersTable" not in self.driver.page_source or "edit.php" in self.driver.current_url:
                        logger.info(f"Job {self.job_id}: Successfully navigated to detail page")
                        return True
                        
                except Exception as e:
                    logger.warning(f"Job {self.job_id}: First cell double-click failed: {str(e)}")
                
                # Method 2: Try double-click on the entire row
                try:
                    logger.info(f"Job {self.job_id}: Attempting double-click on entire row")
                    actions = ActionChains(self.driver)
                    actions.double_click(first_row).perform()
                    time.sleep(3)  # Wait for page to load
                    
                    self.take_screenshot("after_row_doubleclick")
                    
                    # Check if we navigated to detail page
                    if "customersTable" not in self.driver.page_source or "edit.php" in self.driver.current_url:
                        logger.info(f"Job {self.job_id}: Successfully navigated to detail page")
                        return True
                        
                except Exception as e:
                    logger.warning(f"Job {self.job_id}: Row double-click failed: {str(e)}")
                
                # Method 3: Try JavaScript double-click
                try:
                    logger.info(f"Job {self.job_id}: Attempting JavaScript double-click")
                    self.driver.execute_script("""
                        arguments[0].dispatchEvent(new MouseEvent('dblclick', {
                            bubbles: true,
                            cancelable: true,
                            view: window
                        }));
                    """, first_row)
                    time.sleep(3)
                    
                    self.take_screenshot("after_javascript_doubleclick")
                    
                    # Check if we navigated to detail page
                    if "customersTable" not in self.driver.page_source or "edit.php" in self.driver.current_url:
                        logger.info(f"Job {self.job_id}: Successfully navigated to detail page")
                        return True
                        
                except Exception as e:
                    logger.warning(f"Job {self.job_id}: JavaScript double-click failed: {str(e)}")
                
                # Method 4: Look for clickable links in the row
                try:
                    logger.info(f"Job {self.job_id}: Looking for clickable links in row")
                    links = first_row.find_elements(By.XPATH, ".//a")
                    if links:
                        logger.info(f"Job {self.job_id}: Found {len(links)} links in row")
                        links[0].click()
                        time.sleep(3)
                        
                        self.take_screenshot("after_link_click")
                        
                        if "customersTable" not in self.driver.page_source:
                            logger.info(f"Job {self.job_id}: Successfully navigated via link")
                            return True
                            
                except Exception as e:
                    logger.warning(f"Job {self.job_id}: Link click failed: {str(e)}")
                
                logger.error(f"Job {self.job_id}: All row selection methods failed")
                return False
            
            else:
                logger.error(f"Job {self.job_id}: No rows found in Active Services table")
                return False
                
        except Exception as e:
            logger.error(f"Job {self.job_id}: Row selection error: {str(e)}")
            logger.error(traceback.format_exc())
            return False


    def extract_customer_data(self):
        """Extract customer data + complete history tables when circuit found"""
        try:
            self.logger.info(f"Job {self.job_id}: Starting customer data extraction")
            self.take_screenshot("customer_data_page")
            
            # ===== PHASE 1: EXISTING CUSTOMER DATA EXTRACTION (UNCHANGED) =====
            data = {
                "customer": "",
                "circuit_number": "",
                "area": "",
                "originalbw": "",
                "activation": "",
                "expiry_date": "0000-00-00",
                "status": ""
            }
            
            # Check if we're on a customer details page
            wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
            try:
                wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='text'] | //select | //textarea")))
                self.logger.info(f"Job {self.job_id}: Found form elements on page")
            except TimeoutException:
                self.logger.warning(f"Job {self.job_id}: No form elements found on page")
                self.take_screenshot("no_form_elements")
            
            # Extract standard customer data
            self.logger.info(f"Job {self.job_id}: Attempting to extract input elements")
            all_inputs = self.driver.find_elements(By.TAG_NAME, "input")
            all_selects = self.driver.find_elements(By.TAG_NAME, "select")
            all_textareas = self.driver.find_elements(By.TAG_NAME, "textarea")
            
            self.logger.info(f"Job {self.job_id}: Found {len(all_inputs)} inputs, {len(all_selects)} selects, {len(all_textareas)} textareas")
            
            # Process input elements
            for element in all_inputs:
                try:
                    element_id = element.get_attribute("id")
                    if element_id:
                        input_type = element.get_attribute("type")
                        element_value = element.get_attribute("value")
                        
                        if input_type in ["text", "email", "tel", "date"] and element_value:
                            if element_id in self.elements_to_extract:
                                clean_value = element_value.strip()
                                if clean_value:
                                    if element_id == "customer":
                                        data["customer"] = clean_value
                                    elif element_id == "circuit_number" or element_id == "fsan":
                                        data["circuit_number"] = clean_value
                                    elif element_id == "area_detail":
                                        data["area"] = clean_value
                                    elif element_id == "originalbw":
                                        data["originalbw"] = clean_value
                                    elif element_id == "activation":
                                        data["activation"] = clean_value
                                    elif element_id == "exp_date":
                                        data["expiry_date"] = clean_value
                                    else:
                                        data[element_id] = clean_value
                                    
                                    self.logger.info(f"Job {self.job_id}: Extracted {element_id}: {clean_value}")
                except Exception as e:
                    self.logger.warning(f"Job {self.job_id}: Error processing input element: {str(e)}")
                    continue
            
            # Process select elements
            for element in all_selects:
                try:
                    element_id = element.get_attribute("id")
                    if element_id in self.elements_to_extract:
                        selected_option = element.find_element(By.XPATH, ".//option[@selected]")
                        if selected_option:
                            clean_value = selected_option.text.strip()
                            if clean_value:
                                data[element_id] = clean_value
                                self.logger.info(f"Job {self.job_id}: Extracted select {element_id}: {clean_value}")
                except Exception as e:
                    continue
            
            # ===== PHASE 2: COMPLETE HISTORY TABLE EXTRACTION =====
            if data.get("circuit_number"):
                self.logger.info(f"Job {self.job_id}: Circuit found ({data['circuit_number']}), extracting complete history tables")
                
                # Extract history using view_history method
                history_result = self.view_history()
                
                if isinstance(history_result, dict) and "records" in history_result:
                    # Store only essential history data, not the massive JSON
                    data["cancellation_captured_ids"] = history_result.get("cancellation_captured_ids", [])
                    data["history_record_count"] = len(history_result.get("records", []))
                else:
                    self.logger.warning(f"Job {self.job_id}: History extraction failed or returned unexpected format")
                    data["complete_history_tables"] = history_result
            else:
                self.logger.info(f"Job {self.job_id}: No circuit number found, skipping history extraction")
            
            return data
            
        except Exception as e:
            self.logger.error(f"Job {self.job_id}: Error extracting customer data: {str(e)}")
            return {
                "customer": "ERROR: Data extraction failed",
                "circuit_number": "ERROR: Data extraction failed",
                "extraction_error": str(e)
            }

    def view_history(self):
        """View history by scrolling down and clicking view history button, then extract complete table"""
        try:
            self.logger.info(f"Job {self.job_id}: Starting view history process")
            self.take_screenshot("before_history_scroll")
            
            # Scroll down to find the view history button
            self.logger.info(f"Job {self.job_id}: Scrolling down to find view history button")
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            self.take_screenshot("after_scroll_down")
            
            # Try multiple strategies to find and click the history button
            history_clicked = False
            
            # Strategy 1: Look for button with ID "history"
            try:
                history_button = self.driver.find_element(By.ID, "history")
                if history_button.is_displayed():
                    history_button.click()
                    history_clicked = True
                    self.logger.info(f"Job {self.job_id}: Clicked history button using ID")
            except Exception as e:
                self.logger.debug(f"Job {self.job_id}: Strategy 1 failed: {str(e)}")
            
            # Strategy 2: Look for button/link with "history" text
            if not history_clicked:
                try:
                    history_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'History') or contains(text(), 'history')]")
                    for element in history_elements:
                        if element.is_displayed() and element.is_enabled():
                            element.click()
                            history_clicked = True
                            self.logger.info(f"Job {self.job_id}: Clicked history button using text search")
                            break
                except Exception as e:
                    self.logger.debug(f"Job {self.job_id}: Strategy 2 failed: {str(e)}")
            
            # Strategy 3: JavaScript click on any element containing "history"
            if not history_clicked:
                try:
                    result = self.driver.execute_script("""
                        var elements = document.querySelectorAll('*');
                        for(var i = 0; i < elements.length; i++) {
                            var elem = elements[i];
                            var text = elem.textContent || elem.value || elem.innerText || '';
                            if(text.toLowerCase().includes('history')) {
                                elem.click();
                                return true;
                            }
                        }
                        return false;
                    """)
                    if result:
                        history_clicked = True
                        self.logger.info(f"Job {self.job_id}: Clicked history button using JavaScript")
                except Exception as e:
                    self.logger.debug(f"Job {self.job_id}: Strategy 3 failed: {str(e)}")
            
            if not history_clicked:
                self.logger.error(f"Job {self.job_id}: Could not find or click history button")
                self.take_screenshot("history_button_not_found")
                return {"error": "History button not found", "records": []}
            
            # Wait for history page to load
            time.sleep(3)
            self.take_screenshot("history_page_loaded")
            
            # Extract the complete table
            self.logger.info(f"Job {self.job_id}: Extracting complete history table")
            
            # Find the main table (try ID "customersTable" first, then any table)
            table = None
            try:
                table = self.driver.find_element(By.ID, "customersTable")
                self.logger.info(f"Job {self.job_id}: Found table with ID 'customersTable'")
            except:
                tables = self.driver.find_elements(By.TAG_NAME, "table")
                if tables:
                    table = tables[0]
                    self.logger.info(f"Job {self.job_id}: Using first available table")
                else:
                    self.logger.error(f"Job {self.job_id}: No tables found on history page")
                    return {"error": "No tables found", "records": []}
            
            # MANUAL TABLE EXTRACTION - No dependencies
            structured_records = []
            captured_ids = []
            
            try:
                # Get all rows from the table
                rows = table.find_elements(By.TAG_NAME, "tr")
                self.logger.info(f"Job {self.job_id}: Found {len(rows)} rows in history table")
                
                # Process each row (skip header row)
                for row_index, row in enumerate(rows[1:], 1):  # Start from 1 to skip header
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        
                        if len(cells) >= 16:  # Ensure we have all 16 columns
                            # Extract text from each cell
                            cell_texts = [cell.text.strip() for cell in cells]
                            
                            # Create structured record
                            record = {
                                "id": cell_texts[0],
                                "customer_name": cell_texts[1],
                                "account_number": cell_texts[2],
                                "circuit_number": cell_texts[3],
                                "email": cell_texts[4],
                                "address": cell_texts[5],
                                "fsan": cell_texts[6],
                                "mobile_number": cell_texts[7],
                                "reseller": cell_texts[8],
                                "activation_date": cell_texts[9],
                                "ip_address": cell_texts[10],
                                "package": cell_texts[11],
                                "user_logged": cell_texts[12],
                                "time": cell_texts[13],
                                "record_type": cell_texts[14],
                                "upgrade": cell_texts[15],
                                "is_cancellation": "cancellation" in cell_texts[14].lower(),
                                "is_captured": "captured" in cell_texts[15].lower(),
                                "row_index": row_index
                            }
                            
                            structured_records.append(record)
                            
                            # Check for cancellation + captured
                            if record["is_cancellation"] and record["is_captured"]:
                                captured_ids.append(record["id"])
                                self.logger.info(f"Job {self.job_id}: Found cancellation captured ID: {record['id']}")
                            
                            self.logger.debug(f"Job {self.job_id}: Processed row {row_index}: {record['record_type']} - {record['upgrade']}")
                        
                        else:
                            self.logger.warning(f"Job {self.job_id}: Row {row_index} has only {len(cells)} cells, expected 16")
                            
                    except Exception as row_error:
                        self.logger.warning(f"Job {self.job_id}: Error processing row {row_index}: {str(row_error)}")
                        continue
                
                self.logger.info(f"Job {self.job_id}: Successfully extracted {len(structured_records)} records, {len(captured_ids)} cancellation captured")
                
            except Exception as table_error:
                self.logger.error(f"Job {self.job_id}: Error extracting table data: {str(table_error)}")
                return {"error": f"Table extraction failed: {str(table_error)}", "records": []}
            
            # Take final screenshot
            self.take_screenshot("history_extraction_complete")
            
            return {
                "records": structured_records,
                "cancellation_captured_ids": captured_ids,
                "total_records": len(structured_records),
                "table_found": True,
                "extraction_successful": True
            }
            
        except Exception as e:
            self.logger.error(f"Job {self.job_id}: Error in view_history: {str(e)}")
            self.take_screenshot("view_history_error")
            return {"error": str(e), "records": []}

    def get_structured_records(self, table_data):
        """Convert table to structured records"""
        records = []
        
        if not table_data.get("rows") or len(table_data["rows"]) <= 1:
            return records
        
        for row in table_data["rows"][1:]:  # Skip header
            cells = row.get("cells", [])
            if len(cells) >= 16:
                records.append({
                    "id": cells[0].get("text", "").strip(),
                    "customer_name": cells[1].get("text", "").strip(),
                    "account_number": cells[2].get("text", "").strip(),
                    "circuit_number": cells[3].get("text", "").strip(),
                    "email": cells[4].get("text", "").strip(),
                    "address": cells[5].get("text", "").strip(),
                    "fsan": cells[6].get("text", "").strip(),
                    "mobile_number": cells[7].get("text", "").strip(),
                    "reseller": cells[8].get("text", "").strip(),
                    "activation_date": cells[9].get("text", "").strip(),
                    "ip_address": cells[10].get("text", "").strip(),
                    "package": cells[11].get("text", "").strip(),
                    "user_logged": cells[12].get("text", "").strip(),
                    "time": cells[13].get("text", "").strip(),
                    "record_type": cells[14].get("text", "").strip(),
                    "upgrade": cells[15].get("text", "").strip(),
                    "is_cancellation": "cancellation" in cells[14].get("text", "").lower(),
                    "is_captured": "captured" in cells[15].get("text", "").lower()
                })
        
        return records

    def find_cancellation_captured(self, records):
        """Find cancellation + captured records"""
        captured_ids = []
        for record in records:
            if record.get("is_cancellation") and record.get("is_captured"):
                captured_ids.append(record["id"])
        return captured_ids

    def return_to_main(self):
        """Direct navigation instead of UI clicks"""
        logger.info(f"Job {self.job_id}: Force-returning to main")
        try:
            self.driver.get(f"{self.portal_url}/main.php")
            WebDriverWait(self.driver, self.WAIT_TIMEOUT).until(
                EC.title_contains("MetroFibre Portal")
            )
            return True
        except Exception as e:
            logger.error(f"Return to main failed: {str(e)}")
            return False
    
    def cleanup(self):
        """Clean up resources with improved error handling"""
        # Close WebDriver if it exists
        if self.driver:
            try:
                self.driver.quit()
                logger.info(f"Job {self.job_id}: Browser closed")
            except Exception as e:
                logger.error(f"Job {self.job_id}: Error closing browser: {str(e)}")
                
        # Clean up any temporary files
        try:
            temp_dir = Path(f"/tmp/automation_{self.job_id}")
            if temp_dir.exists():
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"Job {self.job_id}: Temporary directory cleaned up")
        except Exception as e:
            logger.error(f"Job {self.job_id}: Error cleaning up temporary files: {str(e)}")

    def save_execution_summary(self, results):
        """Save a single execution summary with all findings"""
        try:
            with open(self.execution_summary_path, "w", encoding="utf-8") as f:
                f.write(f"===== MFN Validation Execution Summary =====\n")
                f.write(f"Job ID: {self.job_id}\n")
                f.write(f"Circuit Number: {results.get('details', {}).get('circuit_number', 'N/A')}\n")
                f.write(f"Execution Time: {datetime.now().isoformat()}\n")
                f.write(f"Status: {results.get('status', 'unknown')}\n\n")
                
                # Customer Data Section
                customer_data = results.get('details', {}).get('customer_data', {})
                if customer_data:
                    f.write("=== Customer Data ===\n")
                    for key, value in customer_data.items():
                        f.write(f"{key}: {value}\n")
                    f.write("\n")
                
                # Service Location
                f.write(f"Service Location: {results.get('details', {}).get('service_location', 'unknown')}\n")
                
                # Cancellation Data if present
                cancellation_data = results.get('details', {}).get('cancellation_data', {})
                if cancellation_data.get('found'):
                    f.write("\n=== Cancellation Data ===\n")
                    f.write(f"Found: {cancellation_data.get('found')}\n")
                    if cancellation_data.get('primary_row'):
                        for key, value in cancellation_data['primary_row'].items():
                            f.write(f"{key}: {value}\n")
                
                # Screenshots taken
                f.write(f"\n=== Screenshots ===\n")
                f.write(f"Total screenshots: {len(self.screenshots)}\n")
                for screenshot in self.screenshots:
                    f.write(f"- {screenshot['name']} at {screenshot['timestamp']}\n")
                    
            logger.info(f"Job {self.job_id}: Execution summary saved to {self.execution_summary_path}")
        except Exception as e:
            logger.error(f"Job {self.job_id}: Failed to save execution summary: {str(e)}")

    def extract_deactivated_cancellation_data(self):
        """
        Extract cancellation data from an already-loaded deactivated services page.
        Captures ALL rows in the table, not just the first valid match.

        Returns:
            dict: Dictionary containing extracted data
        """
        logger.info(f"Job {self.job_id}: Extracting cancellation data from deactivated services page")
        time.sleep(3)
        try:
            # Take screenshot of the current page
            self.take_screenshot("deactivated_page_extract")

            # Wait for table to be available
            wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)

            # Try to find the table
            table = None
            for selector in ["#ChangeLogTable", "#customersTable", "table.dataTable", "table"]:
                try:
                    table = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if table:
                        logger.info(f"Job {self.job_id}: Found table using selector: {selector}")
                        break
                except Exception as e:
                    logger.debug(f"Job {self.job_id}: Table selector {selector} failed: {str(e)}")
                    continue

            if not table:
                logger.warning(f"Job {self.job_id}: No table found in deactivated services")
                return {"error": "No table found", "found": False}

            # Get all rows
            rows = table.find_elements(By.TAG_NAME, "tr")

            if not rows:
                logger.warning(f"Job {self.job_id}: No rows found in deactivated services table")
                return {"error": "No rows found", "found": False}

            logger.info(f"Job {self.job_id}: Found {len(rows)} rows in deactivated services table")

            # Initialize result data structure
            result = {
                "found": False,
                "rows": [],  # List to store all row data
                "primary_row": {},  # Will store the first valid row with circuit number
                "processed_rows": 0
            }

            # Skip the header row if present
            start_row = 1 if len(rows) > 1 else 0
            has_highlighted_row = False

            # Process ALL rows
            for row_idx in range(start_row, len(rows)):
                try:
                    row = rows[row_idx]
                    cells = row.find_elements(By.TAG_NAME, "td")
                    logger.info(f"Job {self.job_id}: Row {row_idx} has {len(cells)} cells")

                    if cells and len(cells) > 0:
                        # Map columns based on your screenshot - adjust if needed
                        column_mapping = {
                            0: "id",
                            1: "customer_name", 
                            2: "account_number",
                            3: "circuit_number",
                            4: "date_time",
                            5: "record_type",
                            6: "change_type", 
                            7: "reseller",
                            8: "activation_date"
                        }

                        # Extract cell text and log each cell for debugging
                        cell_data = []
                        for i, cell in enumerate(cells):
                            try:
                                text = cell.text.strip()
                                logger.debug(f"Job {self.job_id}: Cell {i} text: '{text}'")
                                cell_data.append(text)
                            except Exception as cell_err:
                                logger.warning(f"Job {self.job_id}: Error extracting cell {i} text: {str(cell_err)}")
                                cell_data.append("")

                        # Create a row data dictionary
                        row_data = {
                            "row_index": row_idx,
                            "full_row_text": " | ".join(cell_data)
                        }

                        # Map available data using column mapping
                        for i, cell_text in enumerate(cell_data):
                            if i in column_mapping and cell_text:  # Only add non-empty values
                                row_data[column_mapping[i]] = cell_text
                                
                        # Add numbered columns for every cell regardless of mapping
                        for i, cell_text in enumerate(cell_data):
                            row_data[f"column_{i}"] = cell_text

                        # Add this row to our results list
                        result["rows"].append(row_data)
                        result["processed_rows"] += 1

                        # If this row has a circuit number and we haven't highlighted any row yet,
                        # store it as the primary row and highlight it
                        if "circuit_number" in row_data and row_data["circuit_number"] and not has_highlighted_row:
                            logger.info(f"Job {self.job_id}: Found primary row with circuit number: {row_data['circuit_number']}")
                            result["primary_row"] = row_data.copy()
                            result["found"] = True
                            has_highlighted_row = True
                            
                            # Highlight the row for the screenshot
                            try:
                                self.driver.execute_script("arguments[0].style.backgroundColor = 'yellow';", row)
                                logger.info(f"Job {self.job_id}: Highlighted row {row_idx}")
                                # Take screenshot of the highlighted row
                                self.take_screenshot(f"deactivated_row_{row_idx}")
                            except Exception as highlight_err:
                                logger.warning(f"Job {self.job_id}: Could not highlight row: {str(highlight_err)}")

                except Exception as row_err:
                    logger.warning(f"Job {self.job_id}: Error processing row {row_idx}: {str(row_err)}")

            # If we haven't found a primary row with circuit number, but we did process some rows,
            # use the first processed row as primary
            if not result["found"] and result["rows"]:
                result["primary_row"] = result["rows"][0]
                result["found"] = True
                logger.info(f"Job {self.job_id}: No row with circuit number found, using first row as primary")

            # Add circuit number to the top level for compatibility with existing code
            if result["primary_row"].get("circuit_number"):
                result["circuit_number"] = result["primary_row"]["circuit_number"]
                result["status"] = "deactivated"
                
            # Take a final screenshot
            self.take_screenshot("deactivated_data_extracted")
            
            return result

        except Exception as e:
            logger.error(f"Job {self.job_id}: Error extracting deactivated service data: {str(e)}")
            logger.error(traceback.format_exc())
            self.take_screenshot("deactivated_extract_error")
            return {"error": str(e), "found": False}
        
    def extract_cancellation_data_simple(self):
        """Simple cancellation data extraction using existing patterns"""
        cancellation_data = {"found": False}
        
        try:
            # Take screenshot for evidence
            self.take_screenshot("extracting_cancellation_data")
            
            # Look for cancellation indicators in current page
            try:
                # Try to find cancellation text in the page
                page_text = self.driver.page_source.lower()
                if "cancellation" in page_text:
                    
                    # Try to extract from visible table rows
                    rows = self.driver.find_elements(By.XPATH, "//tr[td]")
                    for row in rows:
                        row_text = row.text.lower()
                        if "cancellation" in row_text or "cancelled" in row_text:
                            cells = row.find_elements(By.TAG_NAME, "td")
                            if cells and len(cells) >= 3:
                                cancellation_data["found"] = True
                                cancellation_data["cancellation_captured_id"] = cells[0].text.strip()
                                
                                # Build basic cancellation data
                                cancellation_data["primary_row"] = {
                                    "id": cells[0].text.strip() if len(cells) > 0 else "",
                                    "customer_name": cells[1].text.strip() if len(cells) > 1 else "",
                                    "circuit_number": cells[2].text.strip() if len(cells) > 2 else "",
                                    "record_info": row_text
                                }
                                
                                logger.info(f"Job {self.job_id}: Found cancellation data with ID: {cancellation_data['cancellation_captured_id']}")
                                break
                                
            except Exception as e:
                logger.warning(f"Job {self.job_id}: Error extracting cancellation details: {str(e)}")
                
        except Exception as e:
            logger.error(f"Job {self.job_id}: Error in extract_cancellation_data_simple: {str(e)}")
        
        return cancellation_data

    def extract_detailed_service_status(self, customer_data, cancellation_data, service_location):
        """
        Extract detailed service status info for sophisticated status determination.
        This brings MFN up to OSN-level status granularity by analyzing the combination
        of active and deactivated service data.
        
        Args:
            customer_data (dict): Data from active services search
            cancellation_data (dict): Data from deactivated services search  
            service_location (str): Where the service was found ("active", "inactive", or "not_found")
            
        Returns:
            dict: Detailed status flags for sophisticated status determination
        """
        logger.info(f"Job {self.job_id}: Extracting detailed service status")
        
        detailed_status = {
            "service_found": False,
            "is_active": False,
            "has_active_service": False,
            "has_cancellation_data": False,
            "pending_cease_order": False,
            "cancellation_implementation_date": None,
            "cancellation_captured_id": None,
            "service_status_type": "unknown"
        }
        
        # Determine if service was found at all
        if customer_data or cancellation_data.get("found"):
            detailed_status["service_found"] = True
            
            # Case 1: Service found in ACTIVE services
            if service_location == "active" and customer_data:
                detailed_status["is_active"] = True
                detailed_status["has_active_service"] = True
                detailed_status["service_status_type"] = "active_validated"
                
                # NEW: Check history table data for cancellation records
                history_records = customer_data.get("complete_history_tables", {}).get("records", [])
                cancellation_captured_ids = customer_data.get("cancellation_captured_ids", [])
                
                # Check if history table shows cancellation data
                has_history_cancellation = bool(cancellation_captured_ids)
                
                if has_history_cancellation:
                    detailed_status["has_cancellation_data"] = True
                    detailed_status["pending_cease_order"] = True  # KEY FLAG for "Cancellation Pending"
                    detailed_status["service_status_type"] = "active_with_pending_cancellation"
                    detailed_status["cancellation_captured_id"] = cancellation_captured_ids[0]
                    
                    logger.info(f"Job {self.job_id}: Service is ACTIVE with PENDING CANCELLATION from history table")
                    logger.info(f"Job {self.job_id}: Cancellation captured ID: {cancellation_captured_ids[0]}")
                    
                # ALSO check if there's cancellation data from deactivated services search
                elif cancellation_data.get("found"):
                    detailed_status["has_cancellation_data"] = True
                    detailed_status["pending_cease_order"] = True  # KEY FLAG for "Cancellation Pending"
                    detailed_status["service_status_type"] = "active_with_pending_cancellation"
                    
                    logger.info(f"Job {self.job_id}: Service is ACTIVE with PENDING CANCELLATION from deactivated search")
                    
                    # Extract cancellation ID
                    if cancellation_data.get("cancellation_captured_id"):
                        detailed_status["cancellation_captured_id"] = cancellation_data["cancellation_captured_id"]
                else:
                    logger.info(f"Job {self.job_id}: Service is FULLY ACTIVE (no cancellation data)")
            
            # Should also check expiry dates in customer_data
            if customer_data.get("expiry_date") and customer_data["expiry_date"] != "0000-00-00":
                detailed_status["pending_cease_order"] = True

            # Case 2: Service found in DEACTIVATED services only
            elif service_location == "inactive":
                detailed_status["is_active"] = False
                detailed_status["has_cancellation_data"] = True
                detailed_status["service_status_type"] = "cancelled_implemented"
                
                logger.info(f"Job {self.job_id}: Service is ALREADY CANCELLED")
                
                # Extract cancellation details
                if cancellation_data.get("found"):
                    primary_row = cancellation_data.get("primary_row", {})
                    
                    # Set implementation date (MFN uses the row date_time as cancellation date)
                    if primary_row.get("date_time"):
                        detailed_status["cancellation_implementation_date"] = primary_row["date_time"]
                    
                    # Extract cancellation ID (prefer captured_id, fallback to row id)
                    if cancellation_data.get("cancellation_captured_id"):
                        detailed_status["cancellation_captured_id"] = cancellation_data["cancellation_captured_id"]
                    elif primary_row.get("id"):
                        detailed_status["cancellation_captured_id"] = primary_row["id"]
            
            # Case 3: Service found but unclear state (shouldn't happen but defensive)
            else:
                detailed_status["service_status_type"] = "found_unclear_state"
                logger.warning(f"Job {self.job_id}: Service found but unclear state")
        
        else:
            # No service found anywhere
            detailed_status["service_status_type"] = "not_found"
            logger.info(f"Job {self.job_id}: Service NOT FOUND in any location")
        
        logger.info(f"Job {self.job_id}: Detailed status type: {detailed_status['service_status_type']}")
        logger.info(f"Job {self.job_id}: Pending cease order: {detailed_status['pending_cease_order']}")
        
        return detailed_status

    def validate_service(self, circuit_number, customer_name="", customer_id="", fsan=""):
        """
        SIMPLE FIX: Main validation method with correct service location detection
        Only fixing the service_location detection, keeping all other logic the same
        """
        results = {
            "status": "failure",
            "message": "",
            "evidence": [],
            "screenshot_data": [],
            "details": {}
        }

        try:
            # Phase 1: Initialization and Login
            if not self.initialize_driver() or not self.login():
                results["message"] = "Initialization failed"
                results["details"] = {
                    "found": False,
                    "circuit_number": circuit_number,
                    "error": "Failed to initialize driver or login",
                    "customer_data": {},
                    "service_location": "error"
                }
                return results

            # Phase 2: Search in Active Services First, then Deactivated (existing logic)
            logger.info(f"Job {self.job_id}: Searching in active services")
            search_successful = self.search_customer(circuit_number, customer_name, customer_id, fsan)
            
            # SIMPLE FIX: Determine service location based on search results
            # The search_customer method sets self.service_location = "inactive" only during deactivated search
            if hasattr(self, 'service_location') and self.service_location == "inactive":
                service_location = "inactive"
                logger.info(f"Job {self.job_id}: Service found in deactivated services")
            elif search_successful:
                service_location = "active"
                logger.info(f"Job {self.job_id}: Service found in active services")
            else:
                service_location = "not_found"
                logger.info(f"Job {self.job_id}: Service not found in any location")

            if not search_successful:
                results["message"] = "Customer not found in active or deactivated services"
                results["details"] = {
                    "found": False,
                    "circuit_number": circuit_number,
                    "search_attempted": True,
                    "customer_data": {},
                    "service_location": "not_found"
                }
                return results

            # Phase 3: Select and Extract Data (existing logic)
            if not self.select_first_result():
                results["message"] = "Customer selection failed"
                results["details"] = {
                    "found": False,
                    "circuit_number": circuit_number,
                    "search_successful": True,
                    "selection_failed": True,
                    "customer_data": {},
                    "service_location": service_location
                }
                return results

            # Phase 4: Extract customer data (existing logic - works for both active and deactivated)
            customer_data = self.extract_customer_data()
            
            # Phase 5: Try to extract cancellation data for deactivated services (existing logic)
            cancellation_data = {"found": False}
            if service_location == "inactive":
                cancellation_data = self.extract_cancellation_data_simple()

            # Phase 6: NEW - Extract detailed service status for sophisticated status determination
            detailed_status = self.extract_detailed_service_status(customer_data, cancellation_data, service_location)

            # Phase 7: Build comprehensive results with enhanced data
            if customer_data or cancellation_data.get("found"):
                results["status"] = "success"
                results["message"] = f"Service data found for {circuit_number} in {service_location} services"
                results["details"] = {
                    # Basic compatibility fields (keep existing structure)
                    "found": detailed_status["service_found"],
                    "circuit_number": circuit_number,
                    "customer_data": customer_data,
                    "cancellation_data": cancellation_data,
                    "service_location": service_location,  # FIXED: Now shows correct location
                    
                    # NEW: Enhanced status fields for sophisticated determination
                    "service_found": detailed_status["service_found"],
                    "is_active": detailed_status["is_active"],
                    "has_active_service": detailed_status["has_active_service"],
                    "has_cancellation_data": detailed_status["has_cancellation_data"],
                    "pending_cease_order": detailed_status["pending_cease_order"],  # DRIVES "Cancellation Pending"
                    "cancellation_implementation_date": detailed_status["cancellation_implementation_date"],  # DRIVES "Already Cancelled"
                    "cancellation_captured_id": detailed_status["cancellation_captured_id"],
                    "service_status_type": detailed_status["service_status_type"],
                    
                    # Additional metadata for orchestrator (keep existing)
                    "search_successful": True,
                    "data_extraction_successful": True,
                    "validation_status": "complete",
                    "data_source": "mfn_portal",
                    "extraction_timestamp": datetime.now().isoformat(),
                    
                    # Legacy compatibility fields (keep existing)
                    "is_deactivated": service_location == "inactive",
                    "customer_is_active": detailed_status["is_active"],
                    "service_is_active": detailed_status["is_active"]
                }
            else:
                results["details"] = {
                    "found": False,
                    "circuit_number": circuit_number,
                    "customer_data": {},
                    "cancellation_data": {"found": False},
                    "service_location": "not_found",
                    "search_attempted": True,
                    "message": "No service data found despite successful search"
                }

        except Exception as e:
            logger.error(f"Job {self.job_id}: Validation error: {str(e)}")
            logger.error(traceback.format_exc())
            results["message"] = f"Validation error: {str(e)}"
            results["details"] = {
                "found": False,
                "circuit_number": circuit_number,
                "error": str(e),
                "customer_data": {},
                "cancellation_data": {"found": False},
                "service_location": "error",
                "traceback": traceback.format_exc()
            }

        finally:
            # Use existing cleanup and evidence collection methods (unchanged)
            try:
                # Collect evidence using existing pattern
                evidence_files = []
                screenshot_data = []
                
                # Collect screenshots (existing pattern)
                if hasattr(self, 'screenshot_dir') and self.screenshot_dir:
                    try:
                        screenshot_dir = Path(self.screenshot_dir)
                        if screenshot_dir.exists():
                            for screenshot_file in screenshot_dir.glob(f"{self.job_id}_*.png"):
                                try:
                                    with open(screenshot_file, 'rb') as f:
                                        image_data = base64.b64encode(f.read()).decode()
                                    screenshot_data.append({
                                        "name": screenshot_file.stem,
                                        "base64_data": image_data,
                                        "path": str(screenshot_file),
                                        "timestamp": datetime.now().isoformat()
                                    })
                                except Exception as e:
                                    logger.warning(f"Error encoding screenshot {screenshot_file}: {str(e)}")
                    except Exception as e:
                        logger.warning(f"Error collecting screenshots: {str(e)}")
                
                # Add evidence and screenshots to results
                results["evidence"] = evidence_files
                results["screenshot_data"] = screenshot_data
                
            except Exception as e:
                logger.warning(f"Error collecting evidence: {str(e)}")
            
            self.save_execution_summary(results)
            
            # Use existing cleanup method
            self.cleanup()

        return results





def execute(parameters):
    """
    Execute function interface for worker system.
    
    Args:
        parameters (dict): Parameters from the job request.
            Required: 
                - job_id: The unique job identifier
                - order_id: Used as circuit_number for validation
            Optional:
                - customer_name: Customer name for search
                - customer_id: Customer ID for search
                - fsan: FSAN for search
                
    Returns:
        dict: Results including status, message, evidence paths, and base64 screenshots
    """
    # Extract parameters
    job_id = parameters.get("job_id") or parameters.get("order_id")
    circuit_number = parameters.get("circuit_number") or parameters.get("order_id")
    customer_name = parameters.get("customer_name", "")
    customer_id = parameters.get("customer_id", "")
    fsan = parameters.get("fsan", "")
    
    # Set up job-specific logger
    logger = Config.setup_logging(f"mfn_automation_{job_id}")
    
    # Validate required parameters
    if not job_id:
        logger.error("Missing required parameter: job_id or order_id")
        return {
            "status": "error",
            "message": "Missing required parameter: job_id or order_id"
        }
        
    if not circuit_number:
        logger.error("Missing required parameter: circuit_number or order_id")
        return {
            "status": "error",
            "message": "Missing required parameter: circuit_number or order_id"
        }
    
    # Initialize automation
    automation = MetroFiberAutomation(job_id)
    
    # Run validation
    results = automation.validate_service(
        circuit_number=circuit_number,
        customer_name=customer_name,
        customer_id=customer_id,
        fsan=fsan
    )
    return results
