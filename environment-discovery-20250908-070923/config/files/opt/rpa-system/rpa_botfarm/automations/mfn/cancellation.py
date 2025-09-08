"""
MFN Portal Automation Module - Cancellation Service (CORRECTED)
Fixed to look for cancellation button on the customer detail page top bar
"""
from automations.mfn.validation import MetroFiberAutomation as ValidationAutomation
from automations.mfn.validation import execute as validation_execute

from itertools import chain
import os
import base64
import logging
import traceback
import time
from datetime import datetime, timedelta
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
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

logger = logging.getLogger(__name__)

class MetroFiberAutomation(ValidationAutomation):
    def __init__(self, job_id):
        super().__init__(job_id)
        self.customer_name = None
        self.cancellation_captured_id = None
        self.circuit_number = None

    def _find_and_click_cancellation_button(self):
        """Find and click cancellation button - FIXED TO HANDLE PAGE NAVIGATION"""
        logger.info(f"Job {self.job_id}: Looking for cancellation button")
        
        # CRITICAL FIX: We might be on the history page after validation, need to exit back to detail page
        logger.info(f"Job {self.job_id}: Checking if we need to exit history page first")
        
        # Check if we're on history page and need to exit
        if "query_logresult" in self.driver.current_url.lower():
            logger.info(f"Job {self.job_id}: We're on history page, clicking exit to get back to detail page")
            
            # Try to find and click the exit button
            exit_selectors = [
                "//a[@href='main.php']",  # Exit button that goes to main
                "//a[contains(text(), 'Exit')]",
                "//input[@value='Exit']",
                "//button[contains(text(), 'Exit')]"
            ]
            
            exit_clicked = False
            for selector in exit_selectors:
                try:
                    exit_button = self.driver.find_element(By.XPATH, selector)
                    if exit_button.is_displayed():
                        exit_button.click()
                        logger.info(f"Job {self.job_id}: Clicked exit button to return to detail page")
                        time.sleep(3)  # Wait for page to load
                        self.take_screenshot("exited_history_page")
                        exit_clicked = True
                        break
                except Exception as e:
                    continue
            
            if not exit_clicked:
                logger.warning(f"Job {self.job_id}: Could not find exit button, trying direct navigation")
                # Fallback: go back to customer detail page directly
                self.return_to_main()
                self.search_customer(circuit_number=self.circuit_number)
                self.select_first_result()
        
        # Now scroll to top to ensure cancellation button is visible
        logger.info(f"Job {self.job_id}: Scrolling to top to ensure cancellation button is visible")
        self.driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(2)  # Give time for scroll
        self.take_screenshot("ready_for_cancellation_button")
        
        # Direct JavaScript approach - much faster (ORIGINAL WORKING VERSION)
        try:
            script = """
                var buttons = document.querySelectorAll('a, button, input[type="button"]');
                for(var i=0; i<buttons.length; i++) {
                    var btn = buttons[i];
                    if(btn.textContent && btn.textContent.toLowerCase().includes('cancel')) {
                        btn.click();
                        return true;
                    }
                    if(btn.onclick && String(btn.onclick).includes('cancellation')) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            """
            result = self.driver.execute_script(script)
            if result:
                logger.info(f"Job {self.job_id}: Clicked cancellation button using JavaScript")
                self.take_screenshot("clicked_cancellation_button")
                return True
        except Exception as e:
            logger.warning(f"JavaScript approach failed: {str(e)}")
        
        # Only try one most reliable selector with short timeout (ORIGINAL VERSION)
        try:
            cancel_button = self.driver.find_element(By.XPATH, "//*[contains(text(), 'Cancellation') or contains(text(), 'Cancel')]")
            cancel_button.click()
            logger.info(f"Job {self.job_id}: Clicked cancellation button")
            self.take_screenshot("clicked_cancellation_button")
            return True
        except Exception as e:
            logger.error(f"Job {self.job_id}: Could not find cancellation button: {str(e)}")
            self.take_screenshot("missing_cancellation_button")
            return False

    def _fill_cancellation_form(self, effective_date=None):
        """Fill out the entire cancellation form properly"""
        logger.info(f"Job {self.job_id}: Filling cancellation form")
        
        try:
            # 1. Select cancellation reason (required field)
            if not self._select_cancellation_reason():
                logger.error(f"Job {self.job_id}: Failed to select cancellation reason")
                return False
            
            # 2. Set cancellation date if provided
            if effective_date:
                if not self._set_cancellation_date(effective_date):
                    logger.warning(f"Job {self.job_id}: Failed to set date, but continuing")
            
            # 3. Wait a moment for any dynamic calculations (penalty, etc.)
            time.sleep(2)
            
            # 4. Take screenshot of completed form
            self.take_screenshot("cancellation_form_filled")
            
            logger.info(f"Job {self.job_id}: Form filled successfully")
            return True
            
        except Exception as e:
            logger.error(f"Job {self.job_id}: Error filling cancellation form: {str(e)}")
            self.take_screenshot("form_fill_error")
            return False


    def _submit_cancellation_form(self):
        """Submit the cancellation form"""
        logger.info(f"Job {self.job_id}: Submitting cancellation form")
        
        try:
            # Look for save/submit buttons
            submit_selectors = [
                "//input[@type='submit' and @value='Save']",
                "//input[@type='submit' and contains(@value, 'Submit')]",
                "//button[contains(text(), 'Save')]",
                "//button[contains(text(), 'Submit')]",
                "//button[@type='submit']"
            ]
            
            wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
            
            for selector in submit_selectors:
                try:
                    buttons = self.driver.find_elements(By.XPATH, selector)
                    for button in buttons:
                        if button.is_displayed() and button.is_enabled():
                            logger.info(f"Job {self.job_id}: Found submit button: {button.get_attribute('value') or button.text}")
                            
                            try:
                                button.click()
                                logger.info(f"Job {self.job_id}: Clicked submit button")
                                self.take_screenshot("cancellation_form_submitted")
                                
                                # Handle any confirmation dialogs
                                self._handle_confirmation_dialog()
                                
                                return True
                            except Exception as click_error:
                                logger.debug(f"Submit click failed: {str(click_error)}")
                                try:
                                    self.driver.execute_script("arguments[0].click();", button)
                                    logger.info(f"Job {self.job_id}: Clicked submit button via JavaScript")
                                    self.take_screenshot("cancellation_form_submitted_js")
                                    
                                    # Handle any confirmation dialogs
                                    self._handle_confirmation_dialog()
                                    
                                    return True
                                except Exception as js_error:
                                    logger.debug(f"JavaScript submit click failed: {str(js_error)}")
                                    continue
                
                except Exception as selector_error:
                    logger.debug(f"Submit selector {selector} failed: {str(selector_error)}")
                    continue
            
            logger.error(f"Job {self.job_id}: Could not find or click submit button")
            return False
            
        except Exception as e:
            logger.error(f"Job {self.job_id}: Error submitting form: {str(e)}")
            return False

    def _handle_confirmation_dialog(self):
        """Handle confirmation dialogs"""
        logger.info(f"Job {self.job_id}: Checking for confirmation dialogs")
        
        try:
            # Handle JavaScript alerts
            try:
                alert = WebDriverWait(self.driver, 3).until(EC.alert_is_present())
                if alert:
                    alert_text = alert.text
                    logger.info(f"Job {self.job_id}: JavaScript alert: '{alert_text}'")
                    alert.accept()
                    logger.info(f"Job {self.job_id}: Accepted JavaScript alert")
                    time.sleep(2)
                    return True
            except TimeoutException:
                pass
            
            # Handle HTML confirmation buttons
            confirmation_selectors = [
                "//button[text()='OK' or text()='Yes' or text()='Confirm']",
                "//input[@value='OK' or @value='Yes' or @value='Confirm']"
            ]
            
            for selector in confirmation_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    for element in elements:
                        if element.is_displayed():
                            element.click()
                            logger.info(f"Job {self.job_id}: Clicked confirmation button")
                            time.sleep(2)
                            return True
                except Exception as e:
                    continue
            
            return False
            
        except Exception as e:
            logger.warning(f"Job {self.job_id}: Error handling confirmation: {str(e)}")
            return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((TimeoutException, ElementClickInterceptedException, WebDriverException)),
        before_sleep=before_sleep_log(logger, logging.INFO)
    )
    def perform_cancellation(self, effective_cancellation_date=None):
        """Updated cancellation process with proper form handling"""
        logger.info(f"Job {self.job_id}: Starting cancellation process")
        
        try:
            # 1. Click the cancellation button to get to the form
            if not self._find_and_click_cancellation_button():
                logger.error(f"Job {self.job_id}: Failed to click cancellation button")
                return False
            
            # 2. Wait for the cancellation form to load
            wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
            try:
                wait.until(EC.presence_of_element_located((By.ID, "comments")))
                logger.info(f"Job {self.job_id}: Cancellation form loaded")
            except TimeoutException:
                logger.error(f"Job {self.job_id}: Cancellation form did not load")
                return False
            
            # 3. Fill out the form properly
            if not self._fill_cancellation_form(effective_cancellation_date):
                logger.error(f"Job {self.job_id}: Failed to fill cancellation form")
                return False
            
            # 4. Save the cancellation request
            if not self._save_cancellation_request():
                logger.error(f"Job {self.job_id}: Failed to save cancellation request")
                return False
            
            logger.info(f"Job {self.job_id}: Cancellation process completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Job {self.job_id}: Error in cancellation process: {str(e)}")
            self.take_screenshot("cancellation_process_error")
            return False

    def _wait_for_form_ready(self):
        """Wait for the cancellation form to be fully loaded and ready"""
        logger.info(f"Job {self.job_id}: Waiting for form to be ready")
        wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
        
        try:
            # Wait for all critical form elements to be present
            wait.until(EC.presence_of_element_located((By.ID, "comments")))
            wait.until(EC.presence_of_element_located((By.ID, "save_reseller")))
            wait.until(EC.presence_of_element_located((By.ID, "cancellation_date")))
            
            # Wait for any JavaScript initialization to complete
            self.driver.execute_script("return jQuery.active == 0")
            
            logger.info(f"Job {self.job_id}: Form is ready")
            return True
            
        except Exception as e:
            logger.error(f"Job {self.job_id}: Form not ready: {str(e)}")
            return False



    def _select_cancellation_reason(self, reason=None):
        """Properly select a cancellation reason from the dropdown"""
        logger.info(f"Job {self.job_id}: Selecting cancellation reason")
        wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
        
        try:
            # Wait for the comments dropdown to be available
            comments_dropdown = wait.until(
                EC.element_to_be_clickable((By.ID, "comments"))
            )
            
            # Create a Select object to handle the dropdown
            select = Select(comments_dropdown)
            
            # If no specific reason provided, use a default one
            if not reason:
                reason = "No Reason Provided"  # This matches one of the options in the HTML
            
            try:
                # Try to select by visible text first
                select.select_by_visible_text(reason)
                logger.info(f"Job {self.job_id}: Selected cancellation reason: {reason}")
            except:
                # If the exact text doesn't match, try the first non-empty option
                select.select_by_index(1)  # Skip the empty "Please select..." option
                selected_option = select.first_selected_option
                logger.info(f"Job {self.job_id}: Selected fallback reason: {selected_option.text}")
            
            # Trigger change event
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", comments_dropdown)
            
            self.take_screenshot("cancellation_reason_selected")
            return True
            
        except Exception as e:
            logger.error(f"Job {self.job_id}: Error selecting cancellation reason: {str(e)}")
            self.take_screenshot("cancellation_reason_error")
            return False


    def _set_cancellation_date(self, effective_date=None, future_days=30):
        if effective_date:
            date_str = effective_date
        else:
            from datetime import datetime, timedelta
            future_date = datetime.now() + timedelta(days=future_days)
            date_str = future_date.strftime("%Y-%m-%d")
        
        logger.info(f"Job {self.job_id}: Setting cancellation date to {date_str}")
        wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
        
        try:
            date_input = wait.until(EC.presence_of_element_located((By.ID, "cancellation_date")))
            logger.info(f"Job {self.job_id}: Found cancellation date input")
            
            is_readonly = self.driver.execute_script("return arguments[0].readOnly;", date_input)
            
            if is_readonly:
                self.driver.execute_script(f"arguments[0].value = '{date_str}';", date_input)
                self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', { 'bubbles': true }));", date_input)
                logger.info(f"Job {self.job_id}: Set cancellation date to {date_str} using JavaScript")
            else:
                date_input.clear()
                date_input.send_keys(date_str)
                logger.info(f"Job {self.job_id}: Set cancellation date to {date_str} using sendKeys")
            
            actual_value = self.driver.execute_script("return arguments[0].value;", date_input)
            if actual_value != date_str:
                logger.warning(f"Job {self.job_id}: Date verification failed. Expected: {date_str}, Got: {actual_value}")
            
            self.take_screenshot("cancellation_date_set")
            return True
                
        except Exception as e:
            logger.error(f"Job {self.job_id}: Error setting cancellation date: {str(e)}")
            logger.warning(f"Job {self.job_id}: Will continue with cancellation despite date error")
            return False

    def _save_cancellation_request(self):
        """Enhanced save with proper confirmation handling"""
        logger.info(f"Job {self.job_id}: Saving cancellation request")
        wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
        
        try:
            # Find the save button
            save_button = wait.until(
                EC.element_to_be_clickable((By.ID, "save_reseller"))
            )
            
            # Check if button is disabled
            is_disabled = self.driver.execute_script("return arguments[0].disabled;", save_button)
            if is_disabled:
                logger.warning(f"Job {self.job_id}: Save button is disabled, enabling it")
                self.driver.execute_script("arguments[0].disabled = false;", save_button)
            
            # Click the save button - this will trigger the saveRequest() JavaScript function
            save_button.click()
            logger.info(f"Job {self.job_id}: Clicked save button")
            
            # Handle the penalty confirmation dialog if it appears
            try:
                WebDriverWait(self.driver, 5).until(EC.alert_is_present())
                alert = self.driver.switch_to.alert
                alert_text = alert.text
                logger.info(f"Job {self.job_id}: Confirmation dialog: {alert_text}")
                
                # Accept the penalty warning if it appears
                if "penalty" in alert_text.lower():
                    alert.accept()
                    logger.info(f"Job {self.job_id}: Accepted penalty confirmation")
                else:
                    alert.accept()
                    logger.info(f"Job {self.job_id}: Accepted dialog")
                    
            except TimeoutException:
                logger.info(f"Job {self.job_id}: No confirmation dialog appeared")
            
            # Wait for form submission to complete
            # The form submits to "data_altering/cancellation_request.php"
            try:
                # Wait for either success indication or page change
                WebDriverWait(self.driver, 10).until(
                    lambda driver: (
                        "cancellation_request.php" in driver.current_url or
                        "success" in driver.page_source.lower() or
                        driver.find_elements(By.XPATH, "//div[contains(text(), 'success') or contains(text(), 'Success')]")
                    )
                )
                logger.info(f"Job {self.job_id}: Form submission completed")
            except TimeoutException:
                logger.warning(f"Job {self.job_id}: No clear success indication, but continuing")
            
            self.take_screenshot("cancellation_saved")
            return True
            
        except Exception as e:
            logger.error(f"Job {self.job_id}: Error saving cancellation request: {str(e)}")
            self.take_screenshot("save_error")
            return False




    def get_customer_name(self):
        """Get customer name from the detail page"""
        if self.customer_name:
            logger.info(f"Job {self.job_id}: Using stored customer name: {self.customer_name}")
            return self.customer_name
        
        try:
            # Look for customer name in various locations on detail page
            customer_selectors = [
                "//input[@id='customer']",
                "//td[contains(text(), 'Customer Name')]/following-sibling::td",
                "//label[contains(text(), 'Customer')]/following-sibling::input",
                "//span[contains(@class, 'customer-name')]"
            ]
            
            for selector in customer_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    for element in elements:
                        if element.tag_name.lower() == "input":
                            extracted_name = element.get_attribute("value")
                        else:
                            extracted_name = element.text.strip()
                        
                        if extracted_name:
                            logger.info(f"Job {self.job_id}: Extracted customer name: {extracted_name}")
                            self.customer_name = extracted_name
                            return extracted_name
                except Exception as e:
                    logger.debug(f"Customer name selector {selector} failed: {str(e)}")
                    continue
                    
        except Exception as e:
            logger.warning(f"Job {self.job_id}: Error extracting customer name: {str(e)}")
        
        logger.warning(f"Job {self.job_id}: No customer name found, using default")
        return "customer"

    def save_execution_summary(self, results):
        """Save execution summary"""
        try:
            with open(self.execution_summary_path, "w", encoding="utf-8") as f:
                f.write(f"===== MFN Cancellation Execution Summary =====\n")
                f.write(f"Job ID: {self.job_id}\n")
                f.write(f"Circuit Number: {self.circuit_number}\n")
                f.write(f"Execution Time: {datetime.now().isoformat()}\n")
                f.write(f"Status: {results.get('status', 'unknown')}\n\n")
                
                # Service Data
                service_data = results.get('details', {})
                if service_data:
                    f.write("=== Service Data ===\n")
                    f.write(f"Service Location: {service_data.get('service_location', 'unknown')}\n")
                    f.write(f"Search Successful: {service_data.get('search_successful', False)}\n\n")
                
                # Customer Data
                customer_data = results.get('details', {}).get('customer_data', {})
                if customer_data:
                    f.write("=== Customer Data ===\n")
                    for key, value in customer_data.items():
                        f.write(f"{key}: {value}\n")
                    f.write("\n")
                
                # Screenshots
                f.write(f"=== Screenshots ===\n")
                f.write(f"Total screenshots: {len(self.screenshots)}\n")
                for screenshot in self.screenshots:
                    f.write(f"- {screenshot['name']} at {screenshot['timestamp']}\n")
                    
            logger.info(f"Job {self.job_id}: Execution summary saved")
        except Exception as e:
            logger.error(f"Job {self.job_id}: Failed to save execution summary: {str(e)}")

    def _navigate_to_orders_page(self):
        """Robust navigation to orders page"""
        for attempt in range(3):
            try:
                self.driver.get(f"{self.portal_url}/customer_requests.php")
                WebDriverWait(self.driver, 30).until(
                    EC.presence_of_element_located((By.ID, "flt0_example"))
                )
                return True
            except Exception as e:
                logger.warning(f"Orders navigation attempt {attempt+1} failed: {str(e)}")
        return False

    def _search_for_customer_in_orders(self):
        """Search for the customer in orders view"""
        try:
            search_input = WebDriverWait(self.driver, 30).until(
                EC.element_to_be_clickable((By.ID, "flt0_example"))
            )
            search_input.clear()
            search_input.send_keys(self.customer_name)
            search_input.send_keys(Keys.RETURN)
            
            # Wait for results to load
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.XPATH, f"//tr[contains(., '{self.customer_name}')]"))
            )
            return True
        except Exception as e:
            logger.error(f"Search failed: {str(e)}")
            return False

    def _approve_cancellation_request(self):
        """Complete approval process"""
        try:
            # Find and select the row
            target_row = WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((
                    By.XPATH, 
                    f"//tr[contains(., 'cancellation request') and contains(., '{self.customer_name}')]"
                ))
            )
            
            # Scroll to and double-click the row
            self.driver.execute_script(
                "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", 
                target_row
            )
            time.sleep(1)  # Allow for scroll animation
            ActionChains(self.driver).double_click(target_row).perform()
            
            # Click accept button with multiple fallbacks
            accept_button = WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.ID, "acceptOrder"))
            )
            
            # Nuclear option click
            self.driver.execute_script("""
                arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});
                arguments[0].click();
            """, accept_button)
            
            # Handle confirmation dialog if present
            self._handle_confirmation_dialog()
               
            return True
            
        except Exception as e:
            logger.error(f"Approval failed: {str(e)}")
            return False

    def _navigate_to_view_orders(self):
        """Wait for the dynamically added search input"""
        logger.info(f"Job {self.job_id}: Navigating to View Orders")
        self.driver.get(f"{self.portal_url}/customer_requests.php")
        
        try:
            # Wait for the dynamic search input added by TableFilter
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.ID, "flt0_example"))
            )
            logger.info(f"Job {self.job_id}: Search field loaded")
            return True
        
        except TimeoutException:
            logger.error(f"Job {self.job_id}: Search field not found")
            return False

    def _search_for_customer(self):
        logger.info(f"Job {self.job_id}: Searching for customer")
        wait = WebDriverWait(self.driver, 30)
        
        try:
            # Use the dynamic input's ID
            search_input = wait.until(
                EC.element_to_be_clickable((By.ID, "flt0_example"))
            )
            search_input.clear()
            logger.info(f"Job {self.job_id}: Typing: {self.customer_name}")
            search_input.send_keys(self.customer_name)
            search_input.send_keys(Keys.RETURN)
            
            # Wait for filtered results
            wait.until(
                EC.visibility_of_element_located((By.XPATH, f"//tr[contains(., '{self.customer_name}')]"))
            )
            return True
        except Exception as e:
            logger.error(f"Job {self.job_id}: Search failed: {str(e)}")
            return False

    def _navigate_to_orders_tab_and_search(self):
        """Improved navigation to orders page"""
        wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
        
        try:
            # Use the specific portal navigation structure
            view_orders = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "/html/body/div[3]/header/div/div/div/div/div/ul/li[4]/a")
            ))
            view_orders.click()
            logger.info(f"Job {self.job_id}: Navigated to View Orders")
            
            # Search for the customer
            self._search_for_customer()
            return True
            
        except Exception as e:
            logger.error(f"Job {self.job_id}: Error navigating to View Orders: {str(e)}")
            return False

    def extract_cancellation_captured_id(self):
        logger.info(f"Job {self.job_id}: Searching for cancellation captured ID in history")
        captured_data = {}
        
        try:
            try:
                self.return_to_main()
                self.search_customer(circuit_number=self.circuit_number)
                self.select_first_result()
            except Exception as e:
                logger.warning(f"Job {self.job_id}: Error navigating back to customer record: {str(e)}")
            
            history_buttons = self.driver.find_elements(By.ID, "history")
            if not history_buttons:
                history_buttons = self.driver.find_elements(By.XPATH, "//a[contains(text(), 'History') or contains(@href, 'history')]")
                
            if not history_buttons:
                logger.warning(f"Job {self.job_id}: History button not found")
                return captured_data
            
            try:
                history_buttons[0].click()
                logger.info(f"Job {self.job_id}: Clicked history button")
                time.sleep(2)
            except Exception as e:
                logger.error(f"Job {self.job_id}: Error clicking history button: {str(e)}")
                return captured_data
            
            tables = self.driver.find_elements(By.TAG_NAME, "table")
            if not tables:
                logger.warning(f"Job {self.job_id}: No history tables found")
                return captured_data
            
            logger.info(f"Job {self.job_id}: Found {len(tables)} tables in history view")
            
            for table_index, table in enumerate(tables):
                logger.info(f"Job {self.job_id}: Examining table {table_index+1} of {len(tables)}")
                rows = table.find_elements(By.TAG_NAME, "tr")
                logger.info(f"Job {self.job_id}: Table {table_index+1} has {len(rows)} rows")
                
                for row_index, row in enumerate(rows):
                    row_text = row.text.lower()
                    
                    if "cancellation" in row_text and "captured" in row_text:
                        logger.info(f"Job {self.job_id}: Found row with 'cancellation' and 'captured': {row_text}")
                        
                        cells = row.find_elements(By.TAG_NAME, "td")
                        
                        if cells and len(cells) > 0:
                            self.cancellation_captured_id = cells[0].text.strip()
                            logger.info(f"Job {self.job_id}: Extracted cancellation captured ID: {self.cancellation_captured_id}")
                            
                            captured_data = {
                                "cancellation_captured_id": self.cancellation_captured_id,
                                "row_index": row_index,
                                "table_index": table_index,
                                "row_text": row_text
                            }
                            
                            for i, cell in enumerate(cells):
                                captured_data[f"column_{i}"] = cell.text.strip()
                            
                            try:
                                self.driver.execute_script("arguments[0].style.backgroundColor = 'yellow';", row)
                                logger.info(f"Job {self.job_id}: Highlighted the captured row")
                            except Exception as e:
                                logger.warning(f"Job {self.job_id}: Failed to highlight row: {str(e)}")
                            
                            self.take_screenshot("cancellation_captured_row")
                            
                            evidence_dir = Config.get_job_evidence_dir(self.job_id)
                            capture_file_path = os.path.join(evidence_dir, "cancellation_captured_id.txt")
                            with open(capture_file_path, "w", encoding="utf-8") as f:
                                f.write(f"===== Cancellation Capture Data =====\n")
                                f.write(f"ID: {self.cancellation_captured_id}\n")
                                f.write(f"Row Text: {row_text}\n\n")
                                
                                f.write("Cell Data:\n")
                                for i, cell in enumerate(cells):
                                    f.write(f"Cell {i}: {cell.text.strip()}\n")
                            
                            logger.info(f"Job {self.job_id}: Saved capture data to {capture_file_path}")
                            return captured_data
            
            logger.warning(f"Job {self.job_id}: No row containing both 'cancellation' and 'captured' found")
            return captured_data
            
        except Exception as e:
            logger.error(f"Job {self.job_id}: Error extracting cancellation captured ID: {str(e)}")
            logger.error(traceback.format_exc())
            self.take_screenshot("cancellation_capture_error")
            return captured_data



    def cancel_service(self, circuit_number, customer_name="", customer_id="", fsan="", effective_cancellation_date=None):
        """Complete cancellation service method with all workflow steps"""
        self.circuit_number = circuit_number
        results = {
            "status": "failure",
            "message": "",
            "evidence": [],
            "screenshot_data": [],
            "details": {}
        }

        try:
            # Phase 1: Initialization and Login
            logger.info(f"Job {self.job_id}: Phase 1 - Initialization and Login")
            if not self.initialize_driver() or not self.login():
                results["message"] = "Initialization failed"
                return results

            # Phase 2: Search for customer (use validation method)
            logger.info(f"Job {self.job_id}: Phase 2 - Customer Search")
            if not self.search_customer(circuit_number, customer_name, customer_id, fsan):
                results["message"] = "Customer search failed"
                return results
                    
            # Phase 3: Select customer to get to detail page
            logger.info(f"Job {self.job_id}: Phase 3 - Customer Selection")
            if not self.select_first_result():
                results["message"] = "Customer selection failed"
                return results

            # Phase 4: Extract customer data and get customer name
            logger.info(f"Job {self.job_id}: Phase 4 - Extract Customer Data")
            customer_data = self.extract_customer_data()
            if customer_data and customer_data.get('customer'):
                self.customer_name = customer_data['customer']
                logger.info(f"Job {self.job_id}: Using customer name from data: {self.customer_name}")
            else:
                self.customer_name = self.get_customer_name()
            
            # Phase 5: Perform cancellation on the detail page (SUBMIT REQUEST)
            logger.info(f"Job {self.job_id}: Phase 5 - Submit Cancellation Request")
            cancellation_submitted = self.perform_cancellation(effective_cancellation_date)
            
            if not cancellation_submitted:
                results["message"] = "Failed to submit cancellation request"
                # Don't return here - still try to get updated data
            else:
                logger.info(f"Job {self.job_id}: Cancellation request submitted successfully")

            # Phase 6: Navigate to Orders page (APPROVAL WORKFLOW)
            logger.info(f"Job {self.job_id}: Phase 6 - Navigate to Orders for Approval")
            if not self._navigate_to_orders_page():
                logger.warning(f"Job {self.job_id}: Failed to navigate to orders page")
                if cancellation_submitted:
                    results["status"] = "partial_success"
                    results["message"] = f"Cancellation submitted for {circuit_number} but approval navigation failed"
                # Continue to validation even if this fails
            else:
                # Phase 7: Search for Cancellation Request in Orders
                logger.info(f"Job {self.job_id}: Phase 7 - Search for Cancellation Request")
                if not self._search_for_customer_in_orders():
                    logger.warning(f"Job {self.job_id}: Failed to find cancellation request in orders")
                    if cancellation_submitted:
                        results["status"] = "partial_success"
                        results["message"] = f"Cancellation submitted for {circuit_number} but request not found in orders"
                else:
                    # Phase 8: Approve the Cancellation Request
                    logger.info(f"Job {self.job_id}: Phase 8 - Approve Cancellation Request")
                    if not self._approve_cancellation_request():
                        logger.warning(f"Job {self.job_id}: Failed to approve cancellation request")
                        if cancellation_submitted:
                            results["status"] = "partial_success"
                            results["message"] = f"Cancellation submitted for {circuit_number} but approval failed"
                    else:
                        # Full success - request submitted AND approved
                        results["status"] = "success"
                        results["message"] = f"Cancellation fully completed and approved for {circuit_number}"
                        logger.info(f"Job {self.job_id}: Complete cancellation workflow successful")

            # If we haven't set a status yet but cancellation was submitted, mark as success
            if results["status"] == "failure" and cancellation_submitted:
                results["status"] = "success"
                results["message"] = f"Cancellation submitted for {circuit_number}"

        except Exception as workflow_error:
            logger.error(f"Job {self.job_id}: Workflow error: {str(workflow_error)}")
            logger.error(traceback.format_exc())
            results["message"] = f"Cancellation workflow error: {str(workflow_error)}"
            
        finally:
            # Always get updated data via validation (CRITICAL FOR STATUS DETERMINATION)
            time.sleep(3)  # Give the system time to process any changes
            
            logger.info(f"Job {self.job_id}: Final Phase - Fetching Updated Data via Validation")
            
            try:
                validation_result = validation_execute({
                    "job_id": self.job_id,
                    "circuit_number": circuit_number,
                    "customer_name": customer_name,
                    "customer_id": customer_id,
                    "fsan": fsan
                })
                
                # COMPLETELY REPLACE details with validation data (critical for status determination)
                if "details" in validation_result and validation_result["details"]:
                    results["details"] = validation_result["details"]
                    logger.info(f"Job {self.job_id}: Successfully updated with post-cancellation validation data")
                else:
                    logger.warning(f"Job {self.job_id}: No details found in validation result")
                    
            except Exception as validation_error:
                logger.error(f"Job {self.job_id}: Error in final validation: {str(validation_error)}")
                # Don't fail the whole job if validation fails
            
            # Collect evidence and screenshots
            try:
                evidence_files = []
                screenshot_data = []
                
                if hasattr(self, 'screenshot_dir') and self.screenshot_dir:
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
                
                results["evidence"] = evidence_files
                results["screenshot_data"] = screenshot_data
                
            except Exception as e:
                logger.warning(f"Error collecting evidence: {str(e)}")
            
            # Save execution summary and cleanup
            self.save_execution_summary(results)
            self.cleanup()

        return results

def execute(parameters):
    """Execute function for worker system"""
    job_id = parameters.get("job_id")
    circuit_number = parameters.get("circuit_number") or parameters.get("order_id")
    customer_name = parameters.get("customer_name", "")
    customer_id = parameters.get("customer_id", "")
    fsan = parameters.get("fsan", "")
    effective_cancellation_date = parameters.get("effective_cancellation_date")

    logger = Config.setup_logging(f"mfn_automation_{job_id}")
    
    if not job_id:
        logger.error("Missing required parameter: job_id")
        return {
            "status": "error",
            "message": "Missing required parameter: job_id"
        }
        
    if not circuit_number:
        logger.error("Missing required parameter: circuit_number")
        return {
            "status": "error",
            "message": "Missing required parameter: circuit_number"
        }
    
    automation = MetroFiberAutomation(job_id)
    
    results = automation.cancel_service(
        circuit_number=circuit_number,
        customer_name=customer_name,
        customer_id=customer_id,
        fsan=fsan,
        effective_cancellation_date=effective_cancellation_date
    )
    
    return results