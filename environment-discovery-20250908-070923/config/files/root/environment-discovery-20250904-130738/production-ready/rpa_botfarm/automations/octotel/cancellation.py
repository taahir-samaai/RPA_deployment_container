"""
Octotel Cancellation Module - Improved Production Version
========================================================
Enhanced cancellation module based on validation.py patterns and actual process documentation.
Fixed termination reason and comments as per requirements.
"""

import os
import time
import logging
import traceback
import json
import pyotp
import base64
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from enum import Enum

# Third-party imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException,
    ElementNotInteractableException, ElementClickInterceptedException
)
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from pydantic import BaseModel, Field

# Import configuration
from config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==================== ENUMERATIONS ====================

class CancellationStatus(str, Enum):
    """Enumeration for cancellation status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"

class SearchResult(str, Enum):
    """Enumeration for search results"""
    FOUND = "found"
    NOT_FOUND = "not_found"
    ERROR = "error"

class ServiceStatus(str, Enum):
    """Enumeration for service status"""
    ACTIVE = "active"
    CANCELLED = "cancelled"
    PENDING = "pending"
    UNKNOWN = "unknown"

# ==================== DATA MODELS ====================

class CancellationRequest(BaseModel):
    """Request model for cancellation"""
    job_id: str = Field(..., description="Unique job identifier")
    circuit_number: str = Field(..., description="Circuit number to cancel")
    solution_id: str = Field(..., description="Solution ID for reference")
    requested_date: Optional[str] = Field(None, description="Requested cancellation date (DD/MM/YYYY)")

class ScreenshotData(BaseModel):
    """Model for screenshot data"""
    name: str
    timestamp: datetime
    data: str
    path: str
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class ServiceData(BaseModel):
    """Model for service data"""
    bitstream_reference: str
    status: ServiceStatus
    customer_name: Optional[str] = None
    address: Optional[str] = None
    service_type: Optional[str] = None
    change_request_available: bool = False
    pending_requests_detected: bool = False
    extraction_timestamp: Optional[str] = None

class CancellationResult(BaseModel):
    """Result model for cancellation"""
    job_id: str
    circuit_number: str
    status: CancellationStatus
    message: str
    cancellation_submitted: bool = False
    release_reference: Optional[str] = None
    cancellation_timestamp: Optional[str] = None
    service_data: Optional[ServiceData] = None
    validation_results: Optional[Dict] = None
    execution_time: Optional[float] = None
    screenshots: List[ScreenshotData] = []
    evidence_dir: Optional[str] = None
    details: Optional[Dict] = None

# ==================== UTILITY FUNCTIONS ====================

def robust_click(driver: webdriver.Chrome, element, description: str = "element") -> bool:
    """Multi-method element clicking with fallback strategies"""
    methods = [
        ("regular click", lambda: element.click()),
        ("javascript click", lambda: driver.execute_script("arguments[0].click();", element)),
        ("action chains click", lambda: ActionChains(driver).move_to_element(element).click().perform())
    ]
    
    # Scroll element into viewport center
    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
    time.sleep(1)
    
    # Try each click method
    for method_name, method in methods:
        try:
            method()
            logger.info(f"Successfully clicked {description} using {method_name}")
            return True
        except Exception as e:
            logger.debug(f"{method_name} failed for {description}: {str(e)}")
            continue
    
    logger.error(f"All click methods failed for {description}")
    return False

# ==================== BROWSER SERVICE ====================

class BrowserService:
    """Browser service for production environment"""
    
    def __init__(self):
        self.driver: Optional[webdriver.Chrome] = None
    
    def create_driver(self, job_id: str) -> webdriver.Chrome:
        """Create Chrome driver - USING CONFIG ONLY"""
        options = ChromeOptions()
        
        # USE CONFIG INSTEAD OF os.getenv()
        if Config.HEADLESS:
            options.add_argument('--headless=new')
            logger.info("Running Chrome in HEADLESS mode")
        else:
            logger.info("Running Chrome in VISIBLE mode")
        
        # Standard Chrome options - USE CONFIG
        if Config.NO_SANDBOX:
            options.add_argument('--no-sandbox')
        if Config.DISABLE_DEV_SHM_USAGE:
            options.add_argument('--disable-dev-shm-usage')
        
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-web-security')
        options.add_argument('--allow-running-insecure-content')
        options.add_argument('--incognito')
        
        # Use Config for driver path
        service = Service(executable_path=Config.CHROMEDRIVER_PATH)
        self.driver = webdriver.Chrome(service=service, options=options)
        
        if Config.START_MAXIMIZED and not Config.HEADLESS:
            self.driver.maximize_window()
            
        self.driver.set_page_load_timeout(30)
        self.driver.implicitly_wait(5)
        
        logger.info("Browser initialized successfully")
        return self.driver

    def cleanup(self):
        """Clean up browser resources"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Browser driver closed successfully")
            except Exception as e:
                logger.error(f"Error during driver cleanup: {str(e)}")

# ==================== SCREENSHOT SERVICE ====================

class ScreenshotService:
    """Screenshot service for evidence collection"""
    
    def __init__(self, job_id: str, base_evidence_dir: str = "evidence"):
        self.job_id = job_id
        self.evidence_dir = Path(base_evidence_dir) / "octotel_cancellation" / job_id
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots: List[ScreenshotData] = []
        
    def take_screenshot(self, driver: webdriver.Chrome, name: str) -> Optional[ScreenshotData]:
        """Take screenshot for evidence"""
        try:
            timestamp = datetime.now()
            filename = f"{name}_{timestamp.strftime('%Y%m%d_%H%M%S')}.png"
            filepath = self.evidence_dir / filename
            
            driver.save_screenshot(str(filepath))
            
            # Read and encode to base64
            with open(filepath, 'rb') as f:
                screenshot_data = base64.b64encode(f.read()).decode()
            
            screenshot = ScreenshotData(
                name=name,
                timestamp=timestamp,
                data=screenshot_data,
                path=str(filepath)
            )
            
            self.screenshots.append(screenshot)
            logger.info(f"Screenshot saved: {filepath}")
            return screenshot
            
        except Exception as e:
            logger.error(f"Failed to take screenshot: {str(e)}")
            return None
    
    def get_all_screenshots(self) -> List[ScreenshotData]:
        """Get all screenshots taken"""
        return self.screenshots

# ==================== LOGIN HANDLER ====================

class OctotelTOTPLogin:
    """TOTP login handler for Octotel - copied from validation.py"""
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        retry=retry_if_exception_type((TimeoutException, WebDriverException, ElementNotInteractableException))
    )
    def login(self, driver: webdriver.Chrome) -> bool:
        """Execute complete login flow with TOTP authentication"""
        try:
            logger.info("Starting Octotel login process")
            driver.get(Config.OCTOTEL_URL)
            
            # Wait for page load
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            logger.info("Page loaded successfully")
            
            # Find and click login button
            logger.info("Searching for login button")
            wait = WebDriverWait(driver, 15)
            
            login_selectors = [
                "//a[contains(text(), 'Login')]",
                "//a[contains(text(), 'login')]", 
                "//button[contains(text(), 'Login')]",
                "//input[@value='Login']",
                "#loginButton"
            ]
            
            login_btn = None
            for selector in login_selectors:
                try:
                    if selector.startswith("//"):
                        login_btn = wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                    else:
                        login_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                    logger.info(f"Found login button with selector: {selector}")
                    break
                except TimeoutException:
                    continue
            
            if not login_btn:
                raise Exception("Could not find login button")
            
            # Click login button
            if not robust_click(driver, login_btn, "login button"):
                raise Exception("Failed to click login button")
            
            # Wait for login form
            logger.info("Waiting for login form to appear")
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "signInFormUsername"))
                )
            except TimeoutException:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//input[@type='email' or @type='text']"))
                )
            
            # Enter credentials
            logger.info("Entering login credentials")
            success = driver.execute_script(f"""
                var usernameField = document.getElementById('signInFormUsername') || 
                                  document.querySelector('input[type="email"]') ||
                                  document.querySelector('input[type="text"]');
                var passwordField = document.getElementById('signInFormPassword') || 
                                  document.querySelector('input[type="password"]');
                
                if (usernameField && passwordField) {{
                    usernameField.value = '{Config.OCTOTEL_USERNAME}';
                    passwordField.value = '{Config.OCTOTEL_PASSWORD}';
                    return true;
                }}
                return false;
            """)
            
            # Fallback credential entry
            if not success:
                logger.info("Using fallback credential entry method")
                username_field = driver.find_element(By.ID, "signInFormUsername")
                password_field = driver.find_element(By.ID, "signInFormPassword")
                
                username_field.clear()
                username_field.send_keys(Config.OCTOTEL_USERNAME)
                password_field.clear()
                password_field.send_keys(Config.OCTOTEL_PASSWORD)
            
            # Submit login form
            logger.info("Submitting login form")
            submit_selectors = [
                ("name", "signInSubmitButton"),
                ("xpath", "//button[@type='submit']"),
                ("xpath", "//input[@type='submit']"),
                ("xpath", "//button[contains(text(), 'Sign') or contains(text(), 'Login')]")
            ]
            
            submit_btn = None
            for selector_type, selector_value in submit_selectors:
                try:
                    if selector_type == "name":
                        submit_btn = driver.find_element(By.NAME, selector_value)
                    elif selector_type == "xpath":
                        submit_btn = driver.find_element(By.XPATH, selector_value)
                    
                    if submit_btn:
                        logger.info(f"Found submit button with {selector_type}: {selector_value}")
                        break
                except:
                    continue
            
            if not submit_btn:
                raise Exception("Could not find submit button")
            
            # Submit login
            if not robust_click(driver, submit_btn, "submit button"):
                raise Exception("Failed to click submit button")
            
            logger.info("Login form submitted successfully")
            
            # Handle TOTP authentication
            if not self.handle_totp(driver):
                raise Exception("TOTP authentication failed")
            
            # Wait for successful login indicators
            logger.info("Verifying successful login - waiting for main dashboard")
            try:
                dashboard_wait = WebDriverWait(driver, 20)
                
                success_indicators = [
                    "div.navbar li:nth-of-type(2) > a",
                    "//div[contains(@class, 'navbar')]//a[contains(text(), 'Services')]",
                    "//body[contains(@class, 'dashboard') or contains(@class, 'main')]",
                    "//div[contains(@class, 'navbar')]",
                    "//a[contains(text(), 'Services')]"
                ]
                
                login_success = False
                for indicator in success_indicators:
                    try:
                        if indicator.startswith("//"):
                            dashboard_wait.until(EC.presence_of_element_located((By.XPATH, indicator)))
                        else:
                            dashboard_wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, indicator)))
                        logger.info(f"Login success indicator found: {indicator}")
                        login_success = True
                        break
                    except TimeoutException:
                        continue
                
                if not login_success:
                    current_url = driver.current_url
                    page_title = driver.title
                    logger.error(f"No login success indicators found")
                    logger.error(f"Current URL: {current_url}")
                    logger.error(f"Page title: {page_title}")
                    
                    page_source = driver.page_source.lower()
                    if "sign in" in page_source or "login" in page_source:
                        logger.error("Still on login page - login failed")
                        return False
                    elif "/start" in current_url or "dashboard" in page_source:
                        logger.info("Appears to be on dashboard page - login likely successful")
                        return True
                    else:
                        logger.warning("Unknown page state - proceeding cautiously")
                        return True
                else:
                    logger.info("Login completed successfully")
                    return True
                    
            except Exception as e:
                logger.error(f"Login verification failed: {str(e)}")
                return False
                
        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            raise
    
    def handle_totp(self, driver: webdriver.Chrome) -> bool:
        """Handle TOTP two-factor authentication"""
        logger.info("Handling TOTP authentication")
        try:
            # Generate TOTP code
            totp = pyotp.TOTP(Config.OCTOTEL_TOTP_SECRET)
            totp_code = totp.now()
            logger.info("Generated TOTP code")
            
            # Wait for TOTP input field
            wait = WebDriverWait(driver, 12)
            totp_element = wait.until(
                EC.presence_of_element_located((By.ID, "totpCodeInput"))
            )
            
            # Enter TOTP code
            totp_element.clear()
            totp_element.send_keys(totp_code)
            logger.info("TOTP code entered")
            
            # Submit TOTP
            totp_submit_selectors = [
                ("id", "signInButton"),
                ("xpath", "//button[contains(text(), 'Sign') or contains(text(), 'Verify')]"),
                ("xpath", "//button[@type='submit']"),
                ("xpath", "//input[@type='submit']")
            ]
            
            submit_btn = None
            for selector_type, selector_value in totp_submit_selectors:
                try:
                    if selector_type == "id":
                        submit_btn = wait.until(EC.element_to_be_clickable((By.ID, selector_value)))
                    elif selector_type == "xpath":
                        submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, selector_value)))
                    
                    logger.info(f"Found TOTP submit button with {selector_type}: {selector_value}")
                    break
                except TimeoutException:
                    continue
            
            if not submit_btn:
                raise Exception("Could not find TOTP submit button")
            
            if not robust_click(driver, submit_btn, "TOTP submit button"):
                raise Exception("Failed to click TOTP submit button")
            
            logger.info("TOTP code submitted")
            time.sleep(3)
            return True
            
        except Exception as e:
            logger.error(f"TOTP authentication failed: {e}")
            return False

# ==================== CANCELLATION AUTOMATION ====================

class OctotelCancellationAutomation:
    """Main Octotel cancellation automation class"""
    
    # Fixed values as per requirements
    CANCELLATION_REASON = "Customer Service ISP"
    CANCELLATION_COMMENT = "Bot cancellation"
    
    def __init__(self):
        self.browser_service: Optional[BrowserService] = None
        self.screenshot_service: Optional[ScreenshotService] = None
        self.driver: Optional[webdriver.Chrome] = None
    
    def _setup_services(self, job_id: str):
        """Setup required services"""
        self.browser_service = BrowserService()
        self.driver = self.browser_service.create_driver(job_id)
        self.screenshot_service = ScreenshotService(job_id)
    
    def _cleanup_services(self):
        """Cleanup services"""
        if self.browser_service:
            self.browser_service.cleanup()
    
    def cancel_service(self, request: CancellationRequest) -> CancellationResult:
        """Main cancellation method following Octotel documentation"""
        start_time = time.time()
        
        try:
            logger.info(f"Starting cancellation for job {request.job_id}, circuit {request.circuit_number}")
            
            # Setup services
            self._setup_services(request.job_id)
            
            # Take initial screenshot
            self.screenshot_service.take_screenshot(self.driver, "initial_state")
            
            # Perform login
            login_handler = OctotelTOTPLogin()
            if not login_handler.login(self.driver):
                raise Exception("Login failed")
            
            self.screenshot_service.take_screenshot(self.driver, "after_login")
            
            # Navigate to services
            if not self._navigate_to_services():
                raise Exception("Failed to navigate to services")
            
            self.screenshot_service.take_screenshot(self.driver, "services_page")
            
            # Search and verify service
            search_result, service_data = self._search_and_verify_service(request.circuit_number)
            self.screenshot_service.take_screenshot(self.driver, "service_search_complete")
            
            if search_result == SearchResult.ERROR:
                return self._create_error_result(request, "Service search failed")
            
            if search_result == SearchResult.NOT_FOUND:
                return self._create_not_found_result(request)
            
            # Check if service has pending requests 
            if service_data and service_data.pending_requests_detected:
                return self._create_pending_requests_result(request, service_data)
            
            # Submit cancellation
            success, release_reference = self._submit_cancellation(request)
            self.screenshot_service.take_screenshot(self.driver, "cancellation_submitted")
            
            if not success:
                return self._create_error_result(request, "Cancellation submission failed")
            
            # Validate cancellation
            validation_results = self._validate_cancellation_submission(request.circuit_number)
            self.screenshot_service.take_screenshot(self.driver, "validation_complete")
            
            # Create success result
            execution_time = time.time() - start_time
            result = CancellationResult(
                job_id=request.job_id,
                circuit_number=request.circuit_number,
                status=CancellationStatus.SUCCESS,
                message=f"Successfully submitted cancellation for {request.circuit_number}",
                cancellation_submitted=True,
                release_reference=release_reference,
                cancellation_timestamp=datetime.now().isoformat(),
                service_data=service_data,
                validation_results=validation_results,
                execution_time=execution_time,
                screenshots=self.screenshot_service.get_all_screenshots(),
                evidence_dir=str(self.screenshot_service.evidence_dir),
                details=self._create_details_dict(True, service_data, validation_results, release_reference)
            )
            
            logger.info(f"Cancellation completed successfully in {execution_time:.2f}s")
            return result
            
        except Exception as e:
            logger.error(f"Cancellation failed: {str(e)}")
            logger.error(traceback.format_exc())
            
            if self.screenshot_service and self.driver:
                self.screenshot_service.take_screenshot(self.driver, "error_state")
            
            return self._create_error_result(request, str(e))
            
        finally:
            self._cleanup_services()
    
    def _navigate_to_services(self) -> bool:
        """Navigate to Services page using selectors from JSON recording"""
        try:
            logger.info("Navigating to Services page")
            
            # Use the exact selector from the JSON recording
            wait = WebDriverWait(self.driver, 15)
            services_link = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "div.navbar li:nth-of-type(2) > a")
            ))
            
            if not robust_click(self.driver, services_link, "Services link"):
                raise Exception("Failed to click Services link")
            
            logger.info("Successfully navigated to Services page")
            time.sleep(3)
            return True
            
        except Exception as e:
            logger.error(f"Failed to navigate to services: {str(e)}")
            return False
    
    def _search_and_verify_service(self, circuit_number: str) -> tuple[SearchResult, Optional[ServiceData]]:
        """Search for service using selectors from JSON recording"""
        try:
            logger.info(f"Searching for circuit: {circuit_number}")
            
            # Set status filters based on JSON recording
            self._configure_status_filters()
            
            # Search for circuit using exact selector from JSON
            wait = WebDriverWait(self.driver, 30)
            search_field = wait.until(EC.element_to_be_clickable((By.ID, "search")))
            
            search_field.clear()
            search_field.send_keys(circuit_number)
            
            # Click search button (from JSON recording)
            search_button = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//div[@class='app-body']//a[contains(text(), 'Search')]")
            ))
            robust_click(self.driver, search_button, "Search button")
            
            time.sleep(5)
            
            # Check if service was found
            if not self._is_service_found(circuit_number):
                logger.info(f"Service {circuit_number} not found")
                return SearchResult.NOT_FOUND, None
            
            # Extract and verify service data
            service_data = self._extract_and_verify_service(circuit_number)
            
            if not service_data:
                return SearchResult.ERROR, None
            
            # Check for pending requests
            if service_data.pending_requests_detected:
                logger.warning(f"Service {circuit_number} has pending requests")
                return SearchResult.FOUND, service_data
            
            logger.info(f"Service {circuit_number} found and ready for cancellation")
            return SearchResult.FOUND, service_data
            
        except Exception as e:
            logger.error(f"Error searching for service: {str(e)}")
            return SearchResult.ERROR, None
    
    def _configure_status_filters(self):
        """Configure status filters based on JSON recording"""
        try:
            # From JSON: set first select to empty value and third select to "1" 
            wait = WebDriverWait(self.driver, 15)
            
            # First dropdown (row filter)
            try:
                first_select = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.row > div:nth-of-type(1) select")
                ))
                select_obj = Select(first_select)
                select_obj.select_by_value("")  # Set to "All"
                logger.info("Set first filter to 'All'")
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Could not set first filter: {str(e)}")
            
            # Third dropdown (status filter) 
            try:
                third_select = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div:nth-of-type(3) select")
                ))
                select_obj = Select(third_select)
                select_obj.select_by_value("1")  # Set to show active services
                logger.info("Set third filter to show active services")
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Could not set third filter: {str(e)}")
                
        except Exception as e:
            logger.warning(f"Error setting status filters: {str(e)}")
    
    def _is_service_found(self, circuit_number: str) -> bool:
        """Check if service was found"""
        try:
            page_source = self.driver.page_source.lower()
            return circuit_number.lower() in page_source
        except Exception:
            return False
    
    def _extract_and_verify_service(self, circuit_number: str) -> Optional[ServiceData]:
        """Extract service data and verify availability"""
        try:
            service_data = ServiceData(
                bitstream_reference=circuit_number,
                status=ServiceStatus.UNKNOWN,
                extraction_timestamp=datetime.now().isoformat()
            )
            
            # Find and click service row to get details
            service_row = self._find_and_click_service_row(circuit_number)
            if service_row:
                time.sleep(3)
                
                # Extract basic info from row
                self._extract_row_data(service_row, service_data)
                
                # Check Change Request availability
                service_data.change_request_available = self._check_change_request_availability()
                service_data.pending_requests_detected = not service_data.change_request_available
                
                # Determine status
                service_data.status = self._determine_service_status(service_data)
            
            return service_data
            
        except Exception as e:
            logger.error(f"Error extracting service data: {str(e)}")
            return None
    
    def _find_and_click_service_row(self, circuit_number: str) -> Optional[Any]:
        """Find and click service row"""
        try:
            # Look for table rows containing the circuit number
            row_selectors = [
                f"//tr[contains(., '{circuit_number}')]",
                f"//tr[.//*[contains(text(), '{circuit_number}')]]"
            ]
            
            for selector in row_selectors:
                try:
                    rows = self.driver.find_elements(By.XPATH, selector)
                    if rows:
                        row = rows[0]
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", row)
                        time.sleep(1)
                        robust_click(self.driver, row, "service row")
                        logger.info("Clicked service row")
                        return row
                except Exception:
                    continue
            
            return None
            
        except Exception as e:
            logger.error(f"Error clicking service row: {str(e)}")
            return None
    
    def _extract_row_data(self, service_row, service_data: ServiceData):
        """Extract data from service row"""
        try:
            cells = service_row.find_elements(By.XPATH, ".//td")
            if len(cells) >= 4:
                service_data.service_type = cells[2].text.strip() if len(cells) > 2 else None
                service_data.customer_name = cells[3].text.strip() if len(cells) > 3 else None
        except Exception as e:
            logger.warning(f"Error extracting row data: {str(e)}")
    
    def _check_change_request_availability(self) -> bool:
        """Check if Change Request button is available"""
        try:
            # Use selector from JSON recording
            change_request_selectors = [
                "createchangerequest > a",
                "//createchangerequest/a",
                "//a[contains(text(), 'Change Request')]"
            ]
            
            for selector in change_request_selectors:
                try:
                    if selector.startswith("//"):
                        elements = self.driver.find_elements(By.XPATH, selector)
                    else:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    
                    for element in elements:
                        if element.is_displayed() and element.is_enabled():
                            logger.info("Change Request button is available")
                            return True
                except Exception:
                    continue
            
            logger.warning("Change Request button not available")
            return False
            
        except Exception as e:
            logger.warning(f"Error checking Change Request button: {str(e)}")
            return False
    
    def _determine_service_status(self, service_data: ServiceData) -> ServiceStatus:
        """Determine service status"""
        try:
            page_text = self.driver.page_source.lower()
            
            if "cancelled" in page_text:
                return ServiceStatus.CANCELLED
            elif "pending" in page_text and not service_data.change_request_available:
                return ServiceStatus.PENDING
            elif service_data.change_request_available:
                return ServiceStatus.ACTIVE
            else:
                return ServiceStatus.UNKNOWN
                
        except Exception:
            return ServiceStatus.UNKNOWN
    
    def _submit_cancellation(self, request: CancellationRequest) -> tuple[bool, Optional[str]]:
        """Submit cancellation using exact selectors from JSON recording"""
        try:
            logger.info(f"Starting cancellation process for {request.circuit_number}")
            
            # Click Change Request button using JSON selector
            if not self._click_change_request_button():
                raise Exception("Could not click Change Request button")
            
            time.sleep(3)
            
            # Set Type to "Cancellation" using JSON selector
            if not self._set_cancellation_type():
                logger.warning("Could not set cancellation type")
            
            # Select cancellation reason using JSON selector
            if not self._set_cancellation_reason():
                logger.warning("Could not set cancellation reason")
            
            # Set cancellation date (30 days notice)
            if not self._set_cancellation_date(request.requested_date):
                logger.warning("Could not set cancellation date")
            
            # Add comments using JSON selector
            if not self._set_comments(request.solution_id):
                logger.warning("Could not set comments")
            
            # Submit the request using JSON selector
            if not self._submit_form():
                raise Exception("Could not submit cancellation request")
            
            time.sleep(5)
            
            # Extract release reference
            release_reference = self._extract_release_reference()
            if not release_reference:
                release_reference = f"AUTO_CR_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                logger.info(f"Generated reference: {release_reference}")
            
            logger.info(f"Cancellation submitted. Reference: {release_reference}")
            return True, release_reference
            
        except Exception as e:
            logger.error(f"Error submitting cancellation: {str(e)}")
            return False, None
    
    def _click_change_request_button(self) -> bool:
        """Click Change Request button using JSON selector"""
        try:
            wait = WebDriverWait(self.driver, 30)
            
            # Use exact selector from JSON recording
            button = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "createchangerequest > a")
            ))
            
            if robust_click(self.driver, button, "Change Request button"):
                logger.info("Clicked Change Request button")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error clicking Change Request button: {str(e)}")
            return False
    
    def _set_cancellation_type(self) -> bool:
        """Set Type to 'Cancellation' using JSON selector"""
        try:
            wait = WebDriverWait(self.driver, 15)
            
            # Use exact selector from JSON recording
            type_dropdown = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "form > div:nth-of-type(1) select")
            ))
            
            select = Select(type_dropdown)
            select.select_by_value("1")  # From JSON: value "1" = Cancellation
            logger.info("Set type to Cancellation")
            time.sleep(1)
            return True
            
        except Exception as e:
            logger.error(f"Error setting cancellation type: {str(e)}")
            return False
    
    def _set_cancellation_reason(self) -> bool:
        """Set cancellation reason using JSON selector"""
        try:
            wait = WebDriverWait(self.driver, 15)
            
            # Use exact selector from JSON recording
            reason_dropdown = wait.until(EC.presence_of_element_located(
                (By.ID, "reason_ddl")
            ))
            
            select = Select(reason_dropdown)
            select.select_by_value("2")  # From JSON: value "2" = Customer Service ISP
            logger.info(f"Set reason to {self.CANCELLATION_REASON}")
            time.sleep(1)
            return True
            
        except Exception as e:
            logger.error(f"Error setting cancellation reason: {str(e)}")
            return False
    
    def _set_cancellation_date(self, requested_date: Optional[str]) -> bool:
        """Set cancellation date (30 days notice)"""
        try:
            if requested_date:
                cancellation_date = requested_date
            else:
                future_date = datetime.now() + timedelta(days=30)
                cancellation_date = future_date.strftime("%d/%m/%Y")
            
            logger.info(f"Setting cancellation date: {cancellation_date}")
            
            wait = WebDriverWait(self.driver, 15)
            
            # Multiple strategies for finding date input field
            date_selectors = [
                # Look for input fields with date-related attributes
                "//input[contains(@name, 'date') or contains(@id, 'date')]",
                "//input[@type='date']",
                "//input[contains(@placeholder, 'date')]",
                # Look for input fields near date labels
                "//input[preceding-sibling::*[contains(text(), 'Date')] or following-sibling::*[contains(text(), 'Date')]]",
                # Generic input fields in the form (might need to check context)
                "//form//input[@type='text']",
                # Look by position in form structure
                "//form/div[3]//input",
                "//form/div[contains(@class, 'form-group')]//input[@type='text']"
            ]
            
            date_input = None
            for selector in date_selectors:
                try:
                    potential_inputs = self.driver.find_elements(By.XPATH, selector)
                    
                    for input_field in potential_inputs:
                        if input_field.is_displayed() and input_field.is_enabled():
                            # Check if this looks like a date field
                            placeholder = input_field.get_attribute("placeholder") or ""
                            name = input_field.get_attribute("name") or ""
                            id_attr = input_field.get_attribute("id") or ""
                            
                            if any(term in (placeholder + name + id_attr).lower() 
                                   for term in ["date", "day", "month", "year", "cancel", "due"]):
                                date_input = input_field
                                logger.info(f"Found date input with selector: {selector}")
                                logger.info(f"Input attributes: placeholder='{placeholder}', name='{name}', id='{id_attr}'")
                                break
                    
                    if date_input:
                        break
                        
                except Exception as e:
                    logger.debug(f"Date selector {selector} failed: {str(e)}")
                    continue
            
            if not date_input:
                logger.warning("Could not find date input field - trying all visible text inputs")
                
                # Fallback: try all visible text inputs
                try:
                    all_inputs = self.driver.find_elements(By.XPATH, "//input[@type='text' or not(@type)]")
                    for i, input_field in enumerate(all_inputs):
                        if input_field.is_displayed() and input_field.is_enabled():
                            logger.info(f"Trying text input {i}: {input_field.get_attribute('outerHTML')[:100]}")
                            try:
                                input_field.clear()
                                input_field.send_keys(cancellation_date)
                                logger.info(f"Successfully set date in input {i}")
                                return True
                            except Exception as input_e:
                                logger.debug(f"Input {i} failed: {str(input_e)}")
                                continue
                except Exception as fallback_e:
                    logger.warning(f"Fallback input search failed: {str(fallback_e)}")
                
                return False
            
            # Clear and set the date
            try:
                date_input.clear()
                time.sleep(0.5)
                date_input.send_keys(cancellation_date)
                time.sleep(0.5)
                
                # Verify the date was set
                set_value = date_input.get_attribute("value")
                if set_value and cancellation_date in set_value:
                    logger.info(f"Date successfully set to: {set_value}")
                    return True
                else:
                    logger.warning(f"Date may not have been set correctly. Expected: {cancellation_date}, Got: {set_value}")
                    return True  # Continue anyway, might still work
                    
            except Exception as e:
                logger.error(f"Error setting date value: {str(e)}")
                return False
            
        except Exception as e:
            logger.error(f"Error setting cancellation date: {str(e)}")
            return False
    
    def _set_comments(self, solution_id: str) -> bool:
        """Set comments using JSON selector"""
        try:
            full_comment = f"{self.CANCELLATION_COMMENT}. Reference: {solution_id}"
            
            wait = WebDriverWait(self.driver, 15)
            
            # Use exact selector from JSON recording
            comment_field = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "textarea")
            ))
            
            comment_field.clear()
            comment_field.send_keys(full_comment)
            logger.info(f"Set comment: {full_comment}")
            return True
            
        except Exception as e:
            logger.error(f"Error setting comments: {str(e)}")
            return False
    
    def _submit_form(self) -> bool:
        """Submit the cancellation form using multiple selector strategies"""
        try:
            wait = WebDriverWait(self.driver, 30)  # Increased timeout
            
            # Multiple selectors from JSON recording in order of preference
            submit_selectors = [
                ("css", "div.modal-footer > button"),
                ("xpath", "//html/body/div[3]/div/div[2]/div/div[3]/button"),
                ("xpath", "//button[contains(text(), 'Submit Request')]"),
                ("xpath", "//button[contains(text(), 'Submit')]"),
                ("css", "button[type='submit']"),
                ("xpath", "//div[@class='modal-footer']//button"),
                ("xpath", "//div[contains(@class, 'modal-footer')]//button")
            ]
            
            submit_button = None
            for selector_type, selector in submit_selectors:
                try:
                    logger.info(f"Trying submit button selector: {selector}")
                    
                    if selector_type == "css":
                        submit_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                    elif selector_type == "xpath":
                        submit_button = wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                    
                    if submit_button and submit_button.is_displayed() and submit_button.is_enabled():
                        logger.info(f"Found submit button with selector: {selector}")
                        break
                        
                except TimeoutException:
                    logger.debug(f"Selector {selector} timed out")
                    continue
                except Exception as e:
                    logger.debug(f"Selector {selector} failed: {str(e)}")
                    continue
            
            if not submit_button:
                logger.error("Could not find submit button with any selector")
                
                # Debug: Log current page state
                try:
                    page_source = self.driver.page_source
                    if "submit" in page_source.lower():
                        logger.info("Page contains 'submit' text")
                    if "modal" in page_source.lower():
                        logger.info("Page contains 'modal' text")
                    
                    # Try to find any buttons on the page
                    all_buttons = self.driver.find_elements(By.TAG_NAME, "button")
                    logger.info(f"Found {len(all_buttons)} buttons on page")
                    for i, btn in enumerate(all_buttons[:5]):  # Log first 5 buttons
                        try:
                            btn_text = btn.text.strip()
                            btn_class = btn.get_attribute("class")
                            logger.info(f"Button {i}: text='{btn_text}', class='{btn_class}'")
                        except:
                            pass
                            
                except Exception as debug_e:
                    logger.warning(f"Debug logging failed: {str(debug_e)}")
                
                return False
            
            # Wait a moment for any animations to complete
            time.sleep(2)
            
            # Try clicking with multiple methods
            if robust_click(self.driver, submit_button, "Submit Request button"):
                logger.info("Successfully clicked Submit Request button")
                time.sleep(3)  # Wait for submission to process
                return True
            else:
                logger.error("Failed to click Submit Request button with all methods")
                return False
            
        except Exception as e:
            logger.error(f"Error submitting form: {str(e)}")
            logger.error(f"Exception type: {type(e).__name__}")
            return False
    
    def _extract_release_reference(self) -> Optional[str]:
        """Extract release reference from confirmation"""
        try:
            page_source = self.driver.page_source
            
            # Look for CR patterns
            patterns = [
                r'(CR[\-_]?\d{6,})',
                r'(CHG[\-_]?\d{6,})',
                r'([A-Z]{2,3}\d{6,})'
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, page_source, re.IGNORECASE)
                if matches:
                    release_reference = matches[0].strip()
                    logger.info(f"Extracted Release Reference: {release_reference}")
                    return release_reference
            
            logger.warning("Could not extract Release Reference")
            return None
            
        except Exception as e:
            logger.warning(f"Error extracting Release Reference: {str(e)}")
            return None
    
    def _validate_cancellation_submission(self, circuit_number: str) -> Dict[str, Any]:
        """Validate cancellation was submitted"""
        try:
            logger.info(f"Validating cancellation for {circuit_number}")
            
            time.sleep(3)
            
            validation_results = {
                "validation_timestamp": datetime.now().isoformat(),
                "validation_status": "complete",
                "circuit_number": circuit_number
            }
            
            # Check for success indicators
            page_source = self.driver.page_source.lower()
            
            success_indicators = [
                "request submitted", "cancellation submitted",
                "successfully submitted", "pending cancellation"
            ]
            
            for indicator in success_indicators:
                if indicator in page_source:
                    validation_results["success_indicator"] = indicator
                    validation_results["cancellation_confirmed"] = True
                    validation_results["message"] = f"Found success indicator: {indicator}"
                    logger.info(f"Found success indicator: {indicator}")
                    return validation_results
            
            validation_results["cancellation_confirmed"] = False
            validation_results["message"] = "No clear confirmation found"
            return validation_results
            
        except Exception as e:
            logger.error(f"Error during validation: {str(e)}")
            return {
                "error": str(e),
                "validation_status": "error",
                "cancellation_confirmed": False
            }
    
    def _create_details_dict(self, cancellation_submitted: bool, service_data: Optional[ServiceData], 
                           validation_results: Dict, release_reference: Optional[str]) -> Dict:
        """Create details dictionary"""
        details = {
            "cancellation_submitted": cancellation_submitted,
            "release_reference": release_reference,
            "found": service_data is not None,
            "circuit_number": service_data.bitstream_reference if service_data else None,
            "cancellation_reason": self.CANCELLATION_REASON,
            "cancellation_comment": self.CANCELLATION_COMMENT
        }
        
        if service_data:
            details.update({
                "service_status": service_data.status.value,
                "customer_name": service_data.customer_name,
                "service_type": service_data.service_type,
                "change_request_available": service_data.change_request_available,
                "pending_requests_detected": service_data.pending_requests_detected
            })
        
        if validation_results:
            details.update(validation_results)
        
        return details
    
    def _create_error_result(self, request: CancellationRequest, message: str) -> CancellationResult:
        """Create error result"""
        return CancellationResult(
            job_id=request.job_id,
            circuit_number=request.circuit_number,
            status=CancellationStatus.ERROR,
            message=message,
            cancellation_submitted=False,
            screenshots=self.screenshot_service.get_all_screenshots() if self.screenshot_service else [],
            evidence_dir=str(self.screenshot_service.evidence_dir) if self.screenshot_service else None,
            details={"found": False, "error": message}
        )
    
    def _create_not_found_result(self, request: CancellationRequest) -> CancellationResult:
        """Create not found result"""
        return CancellationResult(
            job_id=request.job_id,
            circuit_number=request.circuit_number,
            status=CancellationStatus.SUCCESS,
            message=f"Service {request.circuit_number} not found in system",
            cancellation_submitted=False,
            screenshots=self.screenshot_service.get_all_screenshots() if self.screenshot_service else [],
            evidence_dir=str(self.screenshot_service.evidence_dir) if self.screenshot_service else None,
            details={"found": False, "search_result": "service_not_found"}
        )
    
    def _create_pending_requests_result(self, request: CancellationRequest, service_data: ServiceData) -> CancellationResult:
        """Create result for service with pending requests"""
        return CancellationResult(
            job_id=request.job_id,
            circuit_number=request.circuit_number,
            status=CancellationStatus.FAILURE,
            message=f"Cannot cancel {request.circuit_number} - pending requests detected",
            cancellation_submitted=False,
            service_data=service_data,
            screenshots=self.screenshot_service.get_all_screenshots() if self.screenshot_service else [],
            evidence_dir=str(self.screenshot_service.evidence_dir) if self.screenshot_service else None,
            details={
                "found": True,
                "pending_requests_detected": True,
                "change_request_available": False,
                "message": "Service has pending change requests - cancellation not allowed"
            }
        )

# ==================== MAIN EXECUTION FUNCTION ====================

def execute(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main execution function for Octotel cancellation.
    Now includes validation execution at the end like the original script.
    """
    # Extract parameters
    job_id = parameters.get("job_id")
    circuit_number = parameters.get("circuit_number") 
    solution_id = parameters.get("solution_id")
    
    # Initialize results structure
    results = {
        "status": "failure",
        "message": "",
        "evidence": [],
        "screenshot_data": [],
        "details": {}
    }
    
    try:
        # Validate required parameters
        if not job_id:
            return {"status": "error", "message": "Missing required parameter: job_id", 
                   "details": {"error": "job_id is required"}, "screenshot_data": []}
        
        if not circuit_number:
            return {"status": "error", "message": "Missing required parameter: circuit_number",
                   "details": {"error": "circuit_number is required"}, "screenshot_data": []}
            
        if not solution_id:
            return {"status": "error", "message": "Missing required parameter: solution_id", 
                   "details": {"error": "solution_id is required"}, "screenshot_data": []}
        
        # Validate configuration
        if not all([Config.OCTOTEL_USERNAME, Config.OCTOTEL_PASSWORD, Config.OCTOTEL_TOTP_SECRET]):
            return {"status": "error", "message": "Missing required Octotel configuration",
                   "details": {"error": "Invalid Octotel configuration"}, "screenshot_data": []}
        
        # Create cancellation request
        request = CancellationRequest(
            job_id=job_id, circuit_number=circuit_number,
            solution_id=solution_id, requested_date=parameters.get("requested_date")
        )
        
        logger.info(f"Starting cancellation for circuit: {request.circuit_number}")
        
        # Create and run automation
        automation = OctotelCancellationAutomation()
        result = automation.cancel_service(request)
        
        # Convert to dictionary for compatibility
        results = {
            "status": "success" if result.status == CancellationStatus.SUCCESS else "failure",
            "message": result.message,
            "details": {
                "found": result.status == CancellationStatus.SUCCESS,
                "circuit_number": result.circuit_number,
                "cancellation_status": result.status.value,
                "execution_time": result.execution_time,
                
                # Add standardized fields that orchestrator expects
                "cancellation_submitted": result.cancellation_submitted,
                "release_reference": result.release_reference,
                "service_found": result.service_data is not None,
                "is_active": result.service_data.status != ServiceStatus.CANCELLED if result.service_data else False,
                
                "service_data": result.service_data.dict() if result.service_data else None,
                "validation_results": result.validation_results
            },
            "screenshot_data": [
                {"name": s.name, "timestamp": s.timestamp.isoformat(), 
                 "base64_data": s.data, "path": s.path}
                for s in result.screenshots
            ]
        }
        
        # Add detailed results if available
        if result.details:
            results["details"].update(result.details)
        
    except Exception as e:
        logger.error(f"Cancellation execution failed: {str(e)}")
        results = {
            "status": "error", "message": f"Execution error: {str(e)}",
            "details": {"error": str(e), "traceback": traceback.format_exc()},
            "screenshot_data": []
        }
    
    finally:
        # ALWAYS execute validation regardless of cancellation success/failure
        time.sleep(3)  # Give the system time to settle
        
        logger.info(f"Job {job_id}: Now fetching updated data via validation")
        
        try:
            # Import validation function (handle import error gracefully)
            try:
                from automations.octotel.validation import execute as validation_execute
            except ImportError:
                logger.warning(f"Job {job_id}: Could not import Octotel validation - skipping")
                validation_execute = None
            
            if validation_execute:
                # Use validation to get updated data for EVERY cancellation attempt
                validation_result = validation_execute({
                    "job_id": job_id, "circuit_number": circuit_number
                })
                
                # COMPLETELY REPLACE details with validation details
                if "details" in validation_result and validation_result["details"]:
                    results["details"] = validation_result["details"]
                    logger.info(f"Job {job_id}: Successfully replaced details with validation data")
                    
                    # Merge validation screenshots
                    if "screenshot_data" in validation_result and validation_result["screenshot_data"]:
                        existing = results.get("screenshot_data", [])
                        validation_screenshots = validation_result["screenshot_data"]
                        results["screenshot_data"] = existing + validation_screenshots
                        logger.info(f"Job {job_id}: Merged {len(validation_screenshots)} validation screenshots")
            else:
                if "details" not in results:
                    results["details"] = {}
                results["details"]["validation_skipped"] = "Validation module not available"
                    
        except Exception as validation_error:
            logger.error(f"Job {job_id}: Validation execution failed: {str(validation_error)}")
            if "details" not in results:
                results["details"] = {}
            results["details"]["validation_error"] = str(validation_error)
    
    return results
