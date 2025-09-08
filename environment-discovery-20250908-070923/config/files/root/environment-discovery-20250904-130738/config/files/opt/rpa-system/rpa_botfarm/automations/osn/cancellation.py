"""
OSN Cancellation Automation - Enhanced Implementation
====================================================

A comprehensive OSN cancellation module following validation.py best practices.
Implements strategy pattern, proper error handling, and robust automation flows.
Now includes validation execution at the end for comprehensive data collection.
"""

import os
import time
import logging
import traceback
import json
import base64
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from enum import Enum
from abc import ABC, abstractmethod

# Third-party imports
from selenium.webdriver.chrome.service import Service
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException,
    WebDriverException, ElementNotInteractableException, ElementClickInterceptedException
)
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type, before_sleep_log
from pydantic import BaseModel, Field

# Import existing config
from config import Config

# Import OSN validation module for post-cancellation validation
try:
    from automations.osn.validation import execute as validation_execute
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("Could not import OSN validation module - validation will be skipped")
    validation_execute = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== UTILITY FUNCTIONS ====================

def datetime_serializer(obj):
    """JSON serializer for datetime objects"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

def serialize_safely(data):
    """Safely serialize data with datetime handling"""
    return json.loads(json.dumps(data, default=datetime_serializer))

# ==================== ENUMERATIONS ====================

class CancellationStatus(str, Enum):
    """Enumeration for cancellation status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"
    ALREADY_CANCELLED = "already_cancelled"

class CancellationResultType(str, Enum):
    """Enumeration for cancellation results"""
    SUBMITTED = "submitted"
    ALREADY_DEACTIVATED = "already_deactivated"
    NOT_FOUND = "not_found"
    ERROR = "error"

class FormInteractionMethod(str, Enum):
    """Methods for form interaction"""
    STANDARD = "standard"
    JAVASCRIPT = "javascript"
    ACTION_CHAINS = "action_chains"

# ==================== DATA MODELS ====================

class CancellationRequest(BaseModel):
    """Request model for cancellation"""
    job_id: str = Field(..., description="Unique job identifier")
    circuit_number: str = Field(..., description="Circuit number to cancel")
    solution_id: str = Field(..., description="Solution ID for external reference")
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

class CancellationDetails(BaseModel):
    """Model for cancellation details"""
    order_number: Optional[str] = None
    external_reference: str
    requested_date: Optional[str] = None
    submission_date: datetime
    status: str
    confirmation_received: bool = False

class CancellationResult(BaseModel):
    """Result model for cancellation"""
    job_id: str
    circuit_number: str
    status: CancellationStatus
    message: str
    result_type: CancellationResultType
    cancellation_details: Optional[CancellationDetails] = None
    execution_time: Optional[float] = None
    screenshots: List[ScreenshotData] = []
    screenshot_dir: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None

# ==================== SERVICES ====================

class BrowserService:
    """Service for managing browser instances"""
    
    def __init__(self, config: Config):
        self.config = config
        self.driver: Optional[webdriver.Chrome] = None
        self.logger = logging.getLogger(self.__class__.__name__)
    
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
            except Exception as e:
                self.logger.error(f"Error during driver cleanup: {str(e)}")

class ScreenshotService:
    """Service for managing screenshots and evidence"""
    
    def __init__(self, job_id: str, screenshot_dir: Path, execution_summary_path: str):
        self.job_id = job_id
        self.screenshot_dir = screenshot_dir
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.execution_summary_path = execution_summary_path
        self.screenshots = []  # ADD THIS
        self.logger = logging.getLogger(self.__class__.__name__)  # ADD THIS
    
    def take_screenshot(self, driver: webdriver.Chrome, name: str) -> Optional[ScreenshotData]:
        """Take screenshot and save with metadata"""
        try:
            timestamp = datetime.now()
            filename = f"{name}_{timestamp.strftime('%Y%m%d_%H%M%S')}.png"
            filepath = self.screenshot_dir / filename
            
            # Take screenshot
            driver.save_screenshot(str(filepath))
            
            # Read and encode to base64
            with open(filepath, 'rb') as f:
                screenshot_data = base64.b64encode(f.read()).decode()
            
            # Create screenshot object
            screenshot = ScreenshotData(
                name=name,
                timestamp=timestamp,
                data=screenshot_data,
                path=str(filepath)
            )
            
            self.screenshots.append(screenshot)
            self.logger.info(f"Screenshot saved: {filepath}")
            return screenshot
            
        except Exception as e:
            self.logger.error(f"Failed to take screenshot: {str(e)}")
            return None
    
    def get_all_screenshots(self) -> List[ScreenshotData]:
        """Get all screenshots taken"""
        return self.screenshots
    
    def save_execution_summary(self, request, result):
        """Save execution summary with all cancellation details"""
        try:
            with open(self.execution_summary_path, "w", encoding="utf-8") as f:
                f.write(f"===== OSN Cancellation Execution Summary =====\n")
                f.write(f"Job ID: {request.job_id}\n")
                f.write(f"Circuit Number: {request.circuit_number}\n")
                f.write(f"Solution ID: {request.solution_id}\n")
                f.write(f"Execution Time: {datetime.now().isoformat()}\n")
                f.write(f"Status: {result.status.value}\n")
                f.write(f"Result Type: {result.result_type.value}\n\n")
                
                # Cancellation Details
                if result.cancellation_details:
                    f.write("=== Cancellation Details ===\n")
                    f.write(f"Order Number: {result.cancellation_details.order_number}\n")
                    f.write(f"External Reference: {result.cancellation_details.external_reference}\n")
                    f.write(f"Requested Date: {result.cancellation_details.requested_date}\n")
                    f.write(f"Submission Date: {result.cancellation_details.submission_date.isoformat()}\n")
                    f.write(f"Confirmation Received: {result.cancellation_details.confirmation_received}\n\n")
                
                # Error Details
                if result.error_details:
                    f.write("=== Error Details ===\n")
                    for key, value in result.error_details.items():
                        f.write(f"{key}: {value}\n")
                    f.write("\n")
                
                # Screenshots
                f.write(f"=== Screenshots ===\n")
                f.write(f"Total screenshots: {len(self.screenshots)}\n")
                for screenshot in self.screenshots:
                    f.write(f"- {screenshot.name} at {screenshot.timestamp.isoformat()}\n")
                    
            logger.info(f"Execution summary saved")
        except Exception as e:
            logger.error(f"Failed to save execution summary: {str(e)}")

# ==================== STRATEGY INTERFACES ====================

class IErrorDetectionStrategy(ABC):
    """Interface for error detection strategies"""
    
    @abstractmethod
    def has_error(self, driver: webdriver.Chrome) -> bool:
        """Check if page has errors"""
        pass

class IAccessDeniedDetectionStrategy(ABC):
    """Interface for access denied detection strategies"""
    
    @abstractmethod
    def is_access_denied(self, driver: webdriver.Chrome) -> bool:
        """Check if access is denied (service already cancelled)"""
        pass

class IFormInteractionStrategy(ABC):
    """Interface for form interaction strategies"""
    
    @abstractmethod
    def fill_external_reference(self, driver: webdriver.Chrome, reference: str) -> bool:
        """Fill external reference field"""
        pass
    
    @abstractmethod
    def fill_cancellation_date(self, driver: webdriver.Chrome, date_str: str) -> bool:
        """Fill cancellation date field"""
        pass
    
    @abstractmethod
    def submit_cancellation(self, driver: webdriver.Chrome) -> bool:
        """Submit cancellation form"""
        pass

class IConfirmationStrategy(ABC):
    """Interface for confirmation handling strategies"""
    
    @abstractmethod
    def handle_confirmation_dialog(self, driver: webdriver.Chrome) -> bool:
        """Handle confirmation dialog"""
        pass
    
    @abstractmethod
    def extract_order_number(self, driver: webdriver.Chrome) -> Optional[str]:
        """Extract order number from success page"""
        pass

# ==================== STRATEGY IMPLEMENTATIONS ====================

class StandardErrorDetectionStrategy(IErrorDetectionStrategy):
    """Standard error detection strategy"""
    
    def has_error(self, driver: webdriver.Chrome) -> bool:
        """Check for common error indicators"""
        error_selectors = [
            "//div[contains(@class, 'error')]",
            "//div[contains(@class, 'alert-danger')]", 
            "//span[contains(text(), 'Error')]",
            "//div[contains(text(), 'An error occurred')]",
            "//div[contains(@class, 'p-message-error')]"
        ]
        
        for selector in error_selectors:
            try:
                driver.find_element(By.XPATH, selector)
                return True
            except NoSuchElementException:
                continue
        
        return False

class OSNAccessDeniedDetectionStrategy(IAccessDeniedDetectionStrategy):
    """OSN-specific access denied detection"""
    
    def is_access_denied(self, driver: webdriver.Chrome) -> bool:
        """Check for access denied indicators"""
        current_url = driver.current_url
        
        # Check URL for access denied
        if "error/access-denied" in current_url:
            return True
        
        # Check for access denied text
        access_denied_selectors = [
            "//h1[contains(text(), 'Access Denied')]",
            "//div[contains(text(), 'You do not have permission')]",
            "//div[contains(text(), 'Access denied')]"
        ]
        
        for selector in access_denied_selectors:
            try:
                driver.find_element(By.XPATH, selector)
                return True
            except NoSuchElementException:
                continue
        
        return False

class RobustFormInteractionStrategy(IFormInteractionStrategy):
    """Robust form interaction with multiple fallback methods"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def fill_external_reference(self, driver: webdriver.Chrome, reference: str) -> bool:
        """Fill external reference field with multiple methods"""
        selectors = [
            "//input[@formcontrolname='reference']",
            "input[formcontrolname='reference']",
            "#externalReference",
            "input[name='reference']"
        ]
        
        for selector in selectors:
            element = self._find_element_safely(driver, selector)
            if element:
                if self._fill_input_robustly(element, reference):
                    self.logger.info(f"Successfully filled external reference: {reference}")
                    return True
        
        self.logger.error("Failed to fill external reference field")
        return False
    
    def fill_cancellation_date(self, driver: webdriver.Chrome, date_str: str) -> bool:
        """Fill cancellation date field with special handling for Angular components"""
        if not date_str:
            self.logger.info("No cancellation date provided, using default")
            return True
        
        selectors = [
            "p-calendar input",
            "input[formcontrolname='ceaseDate']",
            ".p-calendar input",
            "input[type='date']"
        ]
        
        for selector in selectors:
            element = self._find_element_safely(driver, selector)
            if element:
                if self._fill_date_field(element, date_str):
                    self.logger.info(f"Successfully filled cancellation date: {date_str}")
                    return True
        
        self.logger.warning("Could not find or fill cancellation date field")
        return True  # Not critical for basic cancellation
    
    def submit_cancellation(self, driver: webdriver.Chrome) -> bool:
        """Submit cancellation form with multiple methods"""
        submit_selectors = [
            "//button[contains(@class, 'p-button') and .//span[text()='Submit']]",
            "//button[contains(text(), 'Submit')]",
            "//input[@type='submit']",
            "#submitButton"
        ]
        
        for selector in submit_selectors:
            element = self._find_element_safely(driver, selector)
            if element:
                if self._click_element_robustly(driver, element):
                    self.logger.info("Successfully submitted cancellation form")
                    return True
        
        self.logger.error("Failed to submit cancellation form")
        return False
    
    def _find_element_safely(self, driver: webdriver.Chrome, selector: str) -> Optional[webdriver.remote.webelement.WebElement]:
        """Safely find element with timeout"""
        try:
            if selector.startswith("//"):
                return WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, selector))
                )
            else:
                return WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
        except TimeoutException:
            return None
    
    def _fill_input_robustly(self, element, value: str) -> bool:
        """Fill input field with multiple methods"""
        methods = [
            lambda: self._method_clear_and_send_keys(element, value),
            lambda: self._method_javascript_fill(element, value),
            lambda: self._method_select_all_and_type(element, value)
        ]
        
        for method in methods:
            try:
                if method():
                    return self._verify_input_value(element, value)
            except Exception as e:
                self.logger.debug(f"Fill method failed: {str(e)}")
                continue
        
        return False
    
    def _fill_date_field(self, element, date_str: str) -> bool:
        """Fill date field with special handling for Angular date components"""
        try:
            # Format date for different input types
            formatted_date = self._format_date_for_input(date_str)
            
            # Clear the field first
            element.clear()
            element.send_keys(Keys.CONTROL + "a")
            element.send_keys(Keys.DELETE)
            
            # Type date character by character with small delays
            for char in formatted_date:
                element.send_keys(char)
                time.sleep(0.1)
            
            # Press Tab to commit the value
            element.send_keys(Keys.TAB)
            time.sleep(1)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error filling date field: {str(e)}")
            return False
    
    def _click_element_robustly(self, driver: webdriver.Chrome, element) -> bool:
        """Click element with multiple methods"""
        # Scroll to element first
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
        time.sleep(1)
        
        methods = [
            lambda: element.click(),
            lambda: driver.execute_script("arguments[0].click();", element),
            lambda: ActionChains(driver).move_to_element(element).click().perform()
        ]
        
        for method in methods:
            try:
                method()
                return True
            except Exception as e:
                self.logger.debug(f"Click method failed: {str(e)}")
                continue
        
        return False
    
    def _method_clear_and_send_keys(self, element, value: str) -> bool:
        """Standard clear and send keys method"""
        element.clear()
        element.send_keys(value)
        return True
    
    def _method_javascript_fill(self, element, value: str) -> bool:
        """JavaScript fill method"""
        driver = element.parent
        driver.execute_script("arguments[0].value = '';", element)
        driver.execute_script("arguments[0].focus();", element)
        element.send_keys(value)
        return True
    
    def _method_select_all_and_type(self, element, value: str) -> bool:
        """Select all and replace method"""
        element.click()
        element.send_keys(Keys.CONTROL + "a")
        element.send_keys(value)
        return True
    
    def _verify_input_value(self, element, expected_value: str) -> bool:
        """Verify that input has the expected value"""
        try:
            actual_value = element.get_attribute("value")
            return actual_value == expected_value
        except:
            return False
    
    def _format_date_for_input(self, date_str: str) -> str:
        """Format date string for input field"""
        if "/" in date_str:
            parts = date_str.split("/")
            if len(parts) == 3:
                day, month, year = parts
                return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        return date_str

class OSNConfirmationStrategy(IConfirmationStrategy):
    """OSN-specific confirmation handling"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def handle_confirmation_dialog(self, driver: webdriver.Chrome) -> bool:
        """Handle OSN confirmation dialog"""
        try:
            # Wait for confirmation dialog
            wait = WebDriverWait(driver, 10)
            dialog = wait.until(EC.presence_of_element_located(
                (By.XPATH, "//div[contains(@class, 'p-dialog')]")
            ))
            
            self.logger.info("Confirmation dialog appeared")
            
            # Find and click continue button
            continue_selectors = [
                "//button[@id='ceaseActiveServiceOrderSubmit']",
                "//button[.//span[text()='Continue']]",
                "//button[contains(text(), 'Continue')]",
                "//button[contains(@class, 'p-button-success')]"
            ]
            
            for selector in continue_selectors:
                try:
                    continue_button = wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                    
                    # Try different click methods
                    try:
                        continue_button.click()
                        self.logger.info("Clicked Continue button with regular click")
                        return True
                    except:
                        driver.execute_script("arguments[0].click();", continue_button)
                        self.logger.info("Clicked Continue button with JavaScript")
                        return True
                        
                except TimeoutException:
                    continue
            
            self.logger.error("Could not find or click Continue button")
            return False
            
        except Exception as e:
            self.logger.error(f"Error handling confirmation dialog: {str(e)}")
            return False
    
    def extract_order_number(self, driver: webdriver.Chrome) -> Optional[str]:
        """Extract order number from success page"""
        try:
            # Wait for success message
            wait = WebDriverWait(driver, 10)
            success_element = wait.until(EC.presence_of_element_located(
                (By.XPATH, "//h1[contains(text(), 'Cease active service request submitted successfully')]")
            ))
            
            self.logger.info("Success message found")
            
            # Look for order number
            order_selectors = [
                "//p[contains(text(), 'Order number')]",
                "//div[contains(text(), 'Order number')]",
                "//span[contains(text(), 'Order number')]"
            ]
            
            for selector in order_selectors:
                try:
                    order_element = driver.find_element(By.XPATH, selector)
                    order_text = order_element.text
                    
                    # Extract number using regex
                    import re
                    match = re.search(r'Order number[:\s]+#?(\d+)', order_text)
                    if match:
                        order_number = match.group(1)
                        self.logger.info(f"Extracted order number: {order_number}")
                        return order_number
                        
                except NoSuchElementException:
                    continue
            
            self.logger.warning("Could not extract order number from success page")
            return None
            
        except Exception as e:
            self.logger.error(f"Error extracting order number: {str(e)}")
            return None

# ==================== PAGE OBJECTS ====================

class LoginPage:
    """Page object for OSN login functionality"""
    
    def __init__(self, driver: webdriver.Chrome, email: str, password: str):
        self.driver = driver
        self.email = email
        self.password = password
        self.logger = logging.getLogger(self.__class__.__name__)
        self.wait = WebDriverWait(driver, 30)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(3),
        retry=retry_if_exception_type((TimeoutException, WebDriverException))
    )
    def login(self):
        """Perform login to OSN portal"""
        try:
            self.driver.get("https://partners.openserve.co.za/login")
            self.logger.info("Navigated to OSN login page")
            
            # Wait for page to load completely
            time.sleep(5)
            self.wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")
            
            # Find and fill email field
            email_input = self.wait.until(EC.element_to_be_clickable((By.ID, "email")))
            email_input.clear()
            email_input.send_keys(self.email)
            
            # Find and fill password
            password_input = self.driver.find_element(By.ID, "password")
            password_input.clear()
            password_input.send_keys(self.password)
            
            # Click login button
            login_button = self.driver.find_element(By.ID, "next")
            login_button.click()
            
            # Wait for successful login
            self.wait.until(EC.presence_of_element_located((By.ID, "navOrders")))
            
            self.logger.info("Login successful")
            
        except Exception as e:
            self.logger.error(f"Login failed: {str(e)}")
            raise

class CancellationPage:
    """Page object for OSN cancellation functionality"""
    
    def __init__(self, driver: webdriver.Chrome, 
                 form_strategy: IFormInteractionStrategy,
                 confirmation_strategy: IConfirmationStrategy):
        self.driver = driver
        self.form_strategy = form_strategy
        self.confirmation_strategy = confirmation_strategy
        self.logger = logging.getLogger(self.__class__.__name__)
        self.wait = WebDriverWait(driver, 30)
    
    def navigate_to_cancellation(self, circuit_number: str) -> bool:
        """Navigate to cancellation page for specific circuit"""
        try:
            cancel_url = f"https://partners.openserve.co.za/active-services/{circuit_number}/cease-service"
            self.driver.get(cancel_url)
            
            # Wait for page to load
            time.sleep(3)
            
            # Check for "Cease active service" heading
            try:
                self.wait.until(EC.presence_of_element_located(
                    (By.XPATH, "//h2[contains(text(), 'Cease active service')]")
                ))
                self.logger.info("Successfully loaded cancellation page")
                return True
            except TimeoutException:
                self.logger.warning("Could not confirm cancellation page loaded")
                return False
                
        except Exception as e:
            self.logger.error(f"Error navigating to cancellation page: {str(e)}")
            return False
    
    def submit_cancellation_request(self, solution_id: str, requested_date: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """Submit cancellation request and return success status and order number"""
        try:
            # Wait for form to be ready
            time.sleep(2)
            
            # Fill external reference
            if not self.form_strategy.fill_external_reference(self.driver, solution_id):
                raise Exception("Failed to fill external reference")
            
            # Fill cancellation date if provided
            if requested_date:
                if not self.form_strategy.fill_cancellation_date(self.driver, requested_date):
                    self.logger.warning("Failed to set requested date, continuing with default")
            
            # Wait for UI to stabilize
            time.sleep(2)
            
            # Submit the form
            if not self.form_strategy.submit_cancellation(self.driver):
                raise Exception("Failed to submit cancellation form")
            
            # Handle confirmation dialog
            if not self.confirmation_strategy.handle_confirmation_dialog(self.driver):
                raise Exception("Failed to handle confirmation dialog")
            
            # Extract order number from success page
            order_number = self.confirmation_strategy.extract_order_number(self.driver)
            
            self.logger.info("Cancellation request submitted successfully")
            return True, order_number
            
        except Exception as e:
            self.logger.error(f"Error submitting cancellation request: {str(e)}")
            return False, None

# ==================== MAIN AUTOMATION CLASS ====================

class OSNCancellationAutomation:
    """Main OSN cancellation automation class"""
    
    def __init__(self, 
                 config: Config,
                 error_detection_strategy: IErrorDetectionStrategy,
                 access_denied_strategy: IAccessDeniedDetectionStrategy,
                 form_interaction_strategy: IFormInteractionStrategy,
                 confirmation_strategy: IConfirmationStrategy):
        
        self.config = config
        self.error_detection_strategy = error_detection_strategy
        self.access_denied_strategy = access_denied_strategy
        self.form_interaction_strategy = form_interaction_strategy
        self.confirmation_strategy = confirmation_strategy
        
        self.logger = logging.getLogger(self.__class__.__name__)
        self.browser_service: Optional[BrowserService] = None
        self.screenshot_service: Optional[ScreenshotService] = None
        self.driver: Optional[webdriver.Chrome] = None
    
    def _setup_services(self, job_id: str):
        """Setup required services"""
        # Setup browser service
        self.browser_service = BrowserService(self.config)
        self.driver = self.browser_service.create_driver(job_id)
        
        # Setup screenshot service
        screenshot_dir = Path(Config.get_job_screenshot_dir(job_id))
        execution_summary_path = Config.get_execution_summary_path(job_id)
        self.screenshot_service = ScreenshotService(job_id, screenshot_dir, execution_summary_path)
    
    def _cleanup_services(self):
        """Cleanup services"""
        if self.browser_service:
            self.browser_service.cleanup()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(3),
        retry=retry_if_exception_type((TimeoutException, WebDriverException)),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    def cancel_service(self, request: CancellationRequest) -> CancellationResult:
        """Main cancellation method"""
        start_time = time.time()
        
        try:
            self.logger.info(f"Starting cancellation for job {request.job_id}, circuit {request.circuit_number}")
            
            # Setup services
            self._setup_services(request.job_id)
            
            # Take initial screenshot
            self.screenshot_service.take_screenshot(self.driver, "initial_state")
            
            # Perform login
            login_page = LoginPage(
                self.driver, 
                Config.OSEMAIL,
                Config.OSPASSWORD
            )
            login_page.login()
            self.screenshot_service.take_screenshot(self.driver, "after_login")
            
            # Navigate to cancellation page
            cancellation_page = CancellationPage(
                self.driver,
                self.form_interaction_strategy,
                self.confirmation_strategy
            )
            
            if not cancellation_page.navigate_to_cancellation(request.circuit_number):
                # Check if access denied (already cancelled)
                if self.access_denied_strategy.is_access_denied(self.driver):
                    self.screenshot_service.take_screenshot(self.driver, "access_denied")
                    return self._create_already_cancelled_result(request)
                else:
                    return self._create_error_result(request, "Failed to navigate to cancellation page")
            
            self.screenshot_service.take_screenshot(self.driver, "cancellation_page_loaded")
            
            # Check for errors
            if self.error_detection_strategy.has_error(self.driver):
                self.screenshot_service.take_screenshot(self.driver, "error_detected")
                return self._create_error_result(request, "Error detected on cancellation page")
            
            # Submit cancellation request
            success, order_number = cancellation_page.submit_cancellation_request(
                request.solution_id, 
                request.requested_date
            )
            
            if success:
                self.screenshot_service.take_screenshot(self.driver, "cancellation_success")
                result = self._create_success_result(request, order_number, start_time)
                self.screenshot_service.save_execution_summary(request, result)
                return result
            else:
                self.screenshot_service.take_screenshot(self.driver, "cancellation_failed")
                result = self._create_error_result(request, "Failed to submit cancellation request")
                self.screenshot_service.save_execution_summary(request, result)
                return result
            
        except Exception as e:
            self.logger.error(f"Cancellation failed: {str(e)}")
            self.logger.error(traceback.format_exc())
            
            # Take error screenshot
            if self.screenshot_service and self.driver:
                self.screenshot_service.take_screenshot(self.driver, "error_state")
            
            return self._create_error_result(request, str(e))
            
        finally:
            self._cleanup_services()
    
    def _create_success_result(self, request: CancellationRequest, order_number: Optional[str], start_time: float) -> CancellationResult:
        """Create success result"""
        execution_time = time.time() - start_time
        
        cancellation_details = CancellationDetails(
            order_number=order_number,
            external_reference=request.solution_id,
            requested_date=request.requested_date,
            submission_date=datetime.now(),
            status="submitted",
            confirmation_received=order_number is not None
        )
        
        return CancellationResult(
            job_id=request.job_id,
            circuit_number=request.circuit_number,
            status=CancellationStatus.SUCCESS,
            message=f"Successfully submitted cancellation for circuit {request.circuit_number}",
            result_type=CancellationResultType.SUBMITTED,
            cancellation_details=cancellation_details,
            execution_time=execution_time,
            screenshots=self.screenshot_service.get_all_screenshots() if self.screenshot_service else [],
            screenshot_dir=str(self.screenshot_service.screenshot_dir) if self.screenshot_service else None
        )
    
    def _create_already_cancelled_result(self, request: CancellationRequest) -> CancellationResult:
        """Create result for already cancelled service"""
        return CancellationResult(
            job_id=request.job_id,
            circuit_number=request.circuit_number,
            status=CancellationStatus.ALREADY_CANCELLED,
            message=f"Service {request.circuit_number} appears to be already cancelled",
            result_type=CancellationResultType.ALREADY_DEACTIVATED,
            screenshots=self.screenshot_service.get_all_screenshots() if self.screenshot_service else [],
            screenshot_dir=str(self.screenshot_service.screenshot_dir) if self.screenshot_service else None
        )
    
    def _create_error_result(self, request: CancellationRequest, error_message: str) -> CancellationResult:
        """Create error result"""
        return CancellationResult(
            job_id=request.job_id,
            circuit_number=request.circuit_number,
            status=CancellationStatus.ERROR,
            message=error_message,
            result_type=CancellationResultType.ERROR,
            screenshots=self.screenshot_service.get_all_screenshots() if self.screenshot_service else [],
            screenshot_dir=str(self.screenshot_service.screenshot_dir) if self.screenshot_service else None,
            error_details={"error": error_message, "timestamp": datetime.now().isoformat()}
        )

# ==================== FACTORY ====================

class OSNCancellationFactory:
    """Factory for creating OSN cancellation automation"""
    
    @staticmethod
    def create_standard_automation(config: Config) -> OSNCancellationAutomation:
        """Create standard OSN cancellation automation"""
        return OSNCancellationAutomation(
            config=config,
            error_detection_strategy=StandardErrorDetectionStrategy(),
            access_denied_strategy=OSNAccessDeniedDetectionStrategy(),
            form_interaction_strategy=RobustFormInteractionStrategy(),
            confirmation_strategy=OSNConfirmationStrategy()
        )

# ==================== MAIN EXECUTION FUNCTION ====================

def execute(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main execution function for OSN cancellation.
    Now includes validation execution at the end for comprehensive data collection.
    
    Parameters:
        parameters (dict): Must contain:
            - job_id: Unique job identifier
            - circuit_number: Circuit number to cancel
            - solution_id: Solution ID for external reference
            - requested_date: Optional cancellation date (DD/MM/YYYY)
    
    Returns:
        dict: Cancellation results with status, details, and evidence
    """
    
    # Extract parameters for validation
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
            return {
                "status": "error",
                "message": "Missing required parameter: job_id",
                "details": {"error": "job_id is required"},
                "screenshot_data": []
            }
        
        if not circuit_number:
            return {
                "status": "error", 
                "message": "Missing required parameter: circuit_number",
                "details": {"error": "circuit_number is required"},
                "screenshot_data": []
            }
            
        if not solution_id:
            return {
                "status": "error",
                "message": "Missing required parameter: solution_id", 
                "details": {"error": "solution_id is required for OSN cancellations"},
                "screenshot_data": []
            }
        
        # Create cancellation request
        request = CancellationRequest(
            job_id=job_id,
            circuit_number=circuit_number,
            solution_id=solution_id,
            requested_date=parameters.get("requested_date")
        )
        
        # Create automation using factory
        automation = OSNCancellationFactory.create_standard_automation(Config)
        
        # Execute cancellation
        result = automation.cancel_service(request)
        
        # Convert to dictionary for compatibility
        results = {
            "status": "success" if result.status == CancellationStatus.SUCCESS else "failure",
            "message": result.message,
            "details": {
                "found": result.status == CancellationStatus.SUCCESS,
                "circuit_number": result.circuit_number,
                "result_type": result.result_type.value,
                "cancellation_status": result.status.value,
                "execution_time": result.execution_time,
                "cancellation_details": result.cancellation_details.dict() if result.cancellation_details else None,
                "error_details": result.error_details,
                # Add fields that orchestrator expects for successful cancellations
                "cancellation_submitted": result.status == CancellationStatus.SUCCESS,
                "cancellation_captured_id": result.cancellation_details.order_number if result.cancellation_details and result.cancellation_details.order_number else None,
                "service_found": True,  # If we got to cancellation page, service exists
                "is_active": result.status != CancellationStatus.ALREADY_CANCELLED
            },
            "screenshot_data": [
                {
                    "name": screenshot.name,
                    "timestamp": screenshot.timestamp.isoformat(),
                    "base64_data": screenshot.data,
                    "path": screenshot.path
                }
                for screenshot in result.screenshots
            ]
        }
        
    except Exception as e:
        logger.error(f"Cancellation execution failed: {str(e)}")
        logger.error(traceback.format_exc())
        results = {
            "status": "error",
            "message": f"Execution error: {str(e)}",
            "details": {
                "error": str(e),
                "traceback": traceback.format_exc()
            },
            "screenshot_data": []
        }
    
    finally:
        # ALWAYS execute validation regardless of cancellation success/failure
        # This follows the same pattern as MFN cancellation
        time.sleep(3)  # Give the system time to settle
        
        logger.info(f"Job {job_id}: Now fetching updated data via validation")
        
        if validation_execute:
            try:
                # Use validation to get updated data for EVERY cancellation attempt
                validation_result = validation_execute({
                    "job_id": job_id,
                    "circuit_number": circuit_number
                })
                
                # COMPLETELY REPLACE our details with the validation details
                if "details" in validation_result and validation_result["details"]:
                    # This is the critical fix - completely replace the details
                    results["details"] = validation_result["details"]
                    logger.info(f"Job {job_id}: Successfully replaced details with validation data")
                    
                    # Also merge any validation screenshots
                    if "screenshot_data" in validation_result and validation_result["screenshot_data"]:
                        existing_screenshots = results.get("screenshot_data", [])
                        validation_screenshots = validation_result["screenshot_data"]
                        results["screenshot_data"] = existing_screenshots + validation_screenshots
                        logger.info(f"Job {job_id}: Merged {len(validation_screenshots)} validation screenshots")
                else:
                    logger.warning(f"Job {job_id}: No details found in validation result")
                    
            except Exception as validation_error:
                logger.error(f"Job {job_id}: Validation execution failed: {str(validation_error)}")
                # Don't fail the entire process if validation fails
                # Just add the validation error to the details
                if "details" not in results:
                    results["details"] = {}
                results["details"]["validation_error"] = str(validation_error)
        else:
            logger.warning(f"Job {job_id}: Validation module not available - skipping validation")
            if "details" not in results:
                results["details"] = {}
            results["details"]["validation_skipped"] = "Validation module not available"
    
    return results
