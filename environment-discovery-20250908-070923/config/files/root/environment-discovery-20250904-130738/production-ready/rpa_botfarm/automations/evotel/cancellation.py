"""
Evotel Cancellation Automation - Enhanced with Sophisticated Service Selection
=============================================================================
Updated with enhanced service selection logic.

"""

import os
import time
import logging
import traceback
import json
import base64
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from enum import Enum
from abc import ABC, abstractmethod

# Third-party imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service
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

# Import Evotel validation module for post-cancellation validation
try:
    from automations.evotel.validation import execute as validation_execute
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("Could not import Evotel validation module - validation will be skipped")
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

def filter_active_service_links(driver, logger):
    """
    FIXED: Filter service links to only return active (blue) links, excluding greyed out ones
    Now with proper flow control to actually skip gray links
    
    Args:
        driver: Selenium WebDriver instance
        logger: Logger instance
        
    Returns:
        List of active service link elements
    """
    try:
        # Find all service links
        all_service_links = driver.find_elements(By.XPATH, "//*[@id='WebGrid']/tbody/tr/td[3]/a")
        
        if not all_service_links:
            logger.warning("No service links found")
            return []
        
        active_links = []
        
        for i, link in enumerate(all_service_links):
            is_active = True  # Flag to track if link should be considered active
            link_text = ""
            href = ""
            
            try:
                # Get basic link info
                link_text = link.text.strip()
                href = link.get_attribute("href") or ""
                
                # 1. Check if link has valid href
                if not href or href in ["#", "javascript:void(0)", "javascript:;"]:
                    logger.info(f"Link {i+1}: Skipping - invalid href: {href}")
                    continue
                
                # 2. Check CSS classes for disabled/inactive indicators
                css_classes = link.get_attribute("class") or ""
                disabled_classes = ["disabled", "inactive", "text-muted", "greyed-out", "grey", "not-clickable"]
                
                if any(disabled_class in css_classes.lower() for disabled_class in disabled_classes):
                    logger.info(f"Link {i+1}: Skipping - has disabled class: {css_classes}")
                    continue
                
                # 3. Check if element is actually clickable
                if not link.is_enabled():
                    logger.info(f"Link {i+1}: Skipping - element not enabled")
                    continue
                
                # 4. CRITICAL FIX: Check inline style for gray colors
                inline_style = link.get_attribute("style") or ""
                if inline_style:
                    style_lower = inline_style.lower()
                    
                    # Check for specific gray hex colors
                    gray_hex_colors = [
                        "#c0c0c0",  # Light gray (found in your HTML)
                        "#cccccc",  # Another light gray
                        "#999999",  # Medium gray
                        "#666666",  # Dark gray
                        "#808080",  # Standard gray
                        "#a9a9a9",  # Dark gray
                        "#d3d3d3",  # Light gray
                        "#bebebe",  # Gray
                    ]
                    
                    # Check if any gray hex color is in the inline style
                    for gray_color in gray_hex_colors:
                        if gray_color in style_lower:
                            logger.info(f"Link {i+1}: Skipping - has gray hex inline style: {gray_color}")
                            is_active = False
                            break
                    
                    if not is_active:
                        continue
                    
                    # Check for CSS color names
                    gray_names = ["color: gray", "color: grey", "color: silver"]
                    for gray_name in gray_names:
                        if gray_name in style_lower:
                            logger.info(f"Link {i+1}: Skipping - has gray color name: {gray_name}")
                            is_active = False
                            break
                    
                    if not is_active:
                        continue
                    
                    # Check for RGB gray patterns
                    import re
                    rgb_patterns = [
                        r'rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
                        r'rgba\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*[\d.]+\s*\)'
                    ]
                    
                    for pattern in rgb_patterns:
                        matches = re.findall(pattern, style_lower)
                        for match in matches:
                            if len(match) >= 3:
                                try:
                                    r, g, b = int(match[0]), int(match[1]), int(match[2])
                                    # Check if it's a gray color (similar R, G, B values)
                                    if abs(r - g) < 30 and abs(g - b) < 30 and abs(r - b) < 30:
                                        # Additional check: if values are in gray range
                                        avg_value = (r + g + b) / 3
                                        if avg_value < 200:  # Not too bright (white)
                                            logger.info(f"Link {i+1}: Skipping - has gray RGB inline style: rgb({r},{g},{b})")
                                            is_active = False
                                            break
                                except ValueError:
                                    continue
                        
                        if not is_active:
                            break
                    
                    if not is_active:
                        continue
                
                # 5. Check computed styles as fallback
                try:
                    color = driver.execute_script(
                        "return window.getComputedStyle(arguments[0]).color;", 
                        link
                    )
                    
                    if color:
                        import re
                        rgb_match = re.search(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', color)
                        if rgb_match:
                            r, g, b = map(int, rgb_match.groups())
                            # Check if it's a grey color
                            if abs(r - g) < 50 and abs(g - b) < 50 and abs(r - b) < 50 and max(r, g, b) < 150:
                                logger.info(f"Link {i+1}: Skipping - greyed out computed color: {color}")
                                continue
                
                except Exception as e:
                    logger.debug(f"Link {i+1}: Could not check computed color: {e}")
                
                # 6. Check for low opacity
                try:
                    opacity = driver.execute_script(
                        "return window.getComputedStyle(arguments[0]).opacity;", 
                        link
                    )
                    if opacity and float(opacity) < 0.6:
                        logger.info(f"Link {i+1}: Skipping - low opacity: {opacity}")
                        continue
                except Exception as e:
                    logger.debug(f"Link {i+1}: Could not check opacity: {e}")
                
                # 7. Check if link text is valid
                if not link_text:
                    logger.debug(f"Link {i+1}: Skipping - empty text")
                    continue
                
                # If we get here, the link is considered active
                logger.info(f"Link {i+1}: Active link found - '{link_text}' (href: {href[:50]}...)")
                active_links.append(link)
                
            except Exception as e:
                logger.warning(f"Error checking link {i+1} ({link_text}): {e}")
                continue
        
        logger.info(f"Found {len(active_links)} active links out of {len(all_service_links)} total links")
        return active_links
        
    except Exception as e:
        logger.error(f"Error filtering active service links: {e}")
        return []

def navigate_to_active_service(driver, logger, prefer_last=True):
    """
    Navigate to an active service link, preferring the last (most recent) active service
    
    Args:
        driver: Selenium WebDriver instance
        logger: Logger instance
        prefer_last: If True, clicks the last active link; if False, clicks the first
        
    Returns:
        Optional[str]: Service UUID if successful, None if failed
    """
    try:
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.by import By
        
        wait = WebDriverWait(driver, 15)
        
        # Wait for service links to be present
        wait.until(
            EC.presence_of_element_located((By.XPATH, "//*[@id='WebGrid']/tbody/tr/td[3]/a"))
        )
        
        # Get filtered active service links
        active_service_links = filter_active_service_links(driver, logger)
        
        if not active_service_links:
            logger.error("No active service links found")
            return None
        
        # Select which link to click
        if prefer_last:
            service_link = active_service_links[-1]  # Last (most recent) active service
            position = "last"
        else:
            service_link = active_service_links[0]   # First active service
            position = "first"
        
        # Get service name before clicking
        service_name = service_link.text
        logger.info(f"Found {len(active_service_links)} active service(s), navigating to {position} active service: {service_name}")
        
        # Use the existing robust_click function
        if not robust_click(driver, service_link, f"{position} active service link"):
            raise Exception(f"Failed to click {position} active service link")
        
        # Wait for service info page
        WebDriverWait(driver, 15).until(
            EC.url_contains("/Service/Info/")
        )
        
        # Extract service UUID from URL
        current_url = driver.current_url
        service_uuid = current_url.split("/Service/Info/")[-1] if "/Service/Info/" in current_url else ""
        
        # Remove any query parameters
        if "?" in service_uuid:
            service_uuid = service_uuid.split("?")[0]
        
        logger.info(f"Successfully navigated to active service info page: {service_uuid}")
        return service_uuid
        
    except Exception as e:
        logger.error(f"Error navigating to active service: {str(e)}")
        return None


def extract_active_service_info(driver, logger):
    """
    Extract service information from search results, only clicking on active service links
    
    Args:
        driver: Selenium WebDriver instance
        logger: Logger instance
        
    Returns:
        Dict[str, Any]: Service information or error details
    """
    try:
        logger.info("Extracting active service information")
        
        # Navigate to active service using the enhanced logic
        service_uuid = navigate_to_active_service(driver, logger, prefer_last=True)
        
        if not service_uuid:
            return {"error": "Failed to navigate to active service"}
        
        # Extract service information from the page
        current_url = driver.current_url
        
        # Try to get service name from the page
        try:
            service_name_element = driver.find_element(By.XPATH, "//h2[contains(@class, 'service-name')] | //h1 | //title")
            service_name = service_name_element.text.strip()
        except:
            service_name = "Unknown Service"
        
        service_info = {
            "service_name": service_name,
            "service_uuid": service_uuid,
            "service_url": current_url,
            "extraction_timestamp": datetime.now().isoformat(),
            "is_active_service": True
        }
        
        logger.info(f"Successfully extracted active service info: {service_name}")
        return service_info
        
    except Exception as e:
        logger.error(f"Error extracting active service info: {str(e)}")
        return {"error": str(e)}


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

class ServiceStatus(str, Enum):
    """Service status enumeration"""
    ACTIVE = "active"
    CANCELLED = "cancelled"
    PENDING = "pending"
    UNKNOWN = "unknown"

# ==================== DATA MODELS ====================

class CancellationRequest(BaseModel):
    """Request model for cancellation - Updated to use circuit_number"""
    job_id: str = Field(..., description="Unique job identifier")
    circuit_number: str = Field(..., description="Circuit number to cancel (maps to Evotel serial number)")
    solution_id: Optional[str] = Field(None, description="Solution ID for external reference (optional for Evotel)")
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
    work_order_number: Optional[str] = None
    service_uuid: Optional[str] = None
    external_reference: Optional[str] = None
    requested_date: Optional[str] = None
    submission_date: datetime
    status: str
    confirmation_received: bool = False
    work_order_updated: bool = False

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
    evidence_dir: Optional[str] = None
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
                self.logger.info("Browser cleaned up successfully")
            except Exception as e:
                self.logger.error(f"Error during driver cleanup: {str(e)}")

class ScreenshotService:
    """Service for managing screenshots and evidence"""
    
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.evidence_dir = Path(Config.get_job_screenshot_dir(job_id))
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots: List[ScreenshotData] = []
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def take_screenshot(self, driver: webdriver.Chrome, name: str) -> Optional[ScreenshotData]:
        """Take screenshot and save with metadata"""
        try:
            timestamp = datetime.now()
            filename = f"{name}_{timestamp.strftime('%Y%m%d_%H%M%S')}.png"
            filepath = self.evidence_dir / filename
            
            driver.save_screenshot(str(filepath))
            
            with open(filepath, 'rb') as f:
                screenshot_data = base64.b64encode(f.read()).decode()
            
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

# ==================== STRATEGY INTERFACES ====================

class IErrorDetectionStrategy(ABC):
    """Interface for error detection strategies"""
    
    @abstractmethod
    def has_error(self, driver: webdriver.Chrome) -> bool:
        """Check if page has errors"""
        pass

class IServiceSearchStrategy(ABC):
    """Interface for service search strategies"""
    
    @abstractmethod
    def search_service(self, driver: webdriver.Chrome, circuit_number: str) -> bool:
        """Search for service by circuit number (serial number)"""
        pass
    
    @abstractmethod
    def navigate_to_service(self, driver: webdriver.Chrome) -> Optional[str]:
        """Navigate to service details and return service UUID"""
        pass

class ICancellationFormStrategy(ABC):
    """Interface for cancellation form strategies"""
    
    @abstractmethod
    def initiate_cancellation(self, driver: webdriver.Chrome) -> bool:
        """Click cancel service button"""
        pass
    
    @abstractmethod
    def fill_cancellation_form(self, driver: webdriver.Chrome, reason: str, comment: str) -> bool:
        """Fill cancellation form"""
        pass
    
    @abstractmethod
    def confirm_cancellation(self, driver: webdriver.Chrome) -> bool:
        """Confirm cancellation submission"""
        pass

class IWorkOrderStrategy(ABC):
    """Interface for work order management strategies"""
    
    @abstractmethod
    def navigate_to_work_orders(self, driver: webdriver.Chrome) -> bool:
        """Navigate to work orders section"""
        pass
    
    @abstractmethod
    def update_work_order_status(self, driver: webdriver.Chrome, comment: str) -> Optional[str]:
        """Update work order status and return work order number"""
        pass

# ==================== ENHANCED STRATEGY IMPLEMENTATIONS ====================

class StandardErrorDetectionStrategy(IErrorDetectionStrategy):
    """Standard error detection strategy"""
    
    def has_error(self, driver: webdriver.Chrome) -> bool:
        """Check for common error indicators"""
        error_indicators = [
            "error", "Error", "ERROR",
            "not found", "Not Found", "NOT FOUND",
            "access denied", "Access Denied", "ACCESS DENIED",
            "invalid", "Invalid", "INVALID"
        ]
        
        try:
            page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
            return any(indicator.lower() in page_text for indicator in error_indicators)
        except:
            return False
        
class SimplifiedEvotelServiceSearchStrategy(IServiceSearchStrategy):
    """Simplified Evotel service search strategy - selects last service"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def search_service(self, driver: webdriver.Chrome, circuit_number: str) -> bool:
        """Search for service using circuit number"""
        try:
            self.logger.info(f"Searching for circuit number: {circuit_number}")
            
            # Perform search
            wait = WebDriverWait(driver, 15)
            search_field = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#SearchString"))
            )
            
            if not robust_click(driver, search_field, "search field"):
                raise Exception("Failed to click search field")
            
            search_field.clear()
            time.sleep(0.5)
            search_field.send_keys(circuit_number)
            
            self.logger.info(f"Circuit number entered: {circuit_number}")
            
            # Click search button
            search_button = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='btnSearch']"))
            )
            
            if not robust_click(driver, search_button, "search button"):
                raise Exception("Failed to click search button")
            
            # Wait for results
            WebDriverWait(driver, 20).until(
                lambda d: "/Search" in d.current_url or d.find_elements(By.ID, "WebGrid")
            )
            
            time.sleep(2)
            
            # Check if results found
            service_links = driver.find_elements(By.XPATH, "//*[@id='WebGrid']/tbody/tr/td[3]/a")
            
            if service_links:
                self.logger.info(f"Found {len(service_links)} service results")
                return True
            else:
                self.logger.info("No service results found")
                return False
                
        except Exception as e:
            self.logger.error(f"Service search failed: {str(e)}")
            return False
    
    def navigate_to_service(self, driver: webdriver.Chrome) -> Optional[str]:
        """Navigate to last ACTIVE service and return service UUID - UPDATED TO SKIP GREYED OUT LINKS"""
        try:
            wait = WebDriverWait(driver, 15)
        
            # Wait for service links to be present
            wait.until(
                EC.presence_of_element_located((By.XPATH, "//*[@id='WebGrid']/tbody/tr/td[3]/a"))
            )
        
            # Use the new enhanced active service navigation
            service_uuid = navigate_to_active_service(driver, self.logger, prefer_last=True)
        
            if not service_uuid:
                raise Exception("No active service links found or navigation failed")
        
            return service_uuid
        
        except Exception as e:
            self.logger.error(f"Error navigating to active service: {str(e)}")
            return None

# ==================== ORIGINAL STRATEGIES (UNCHANGED) ====================

class EvotelCancellationFormStrategy(ICancellationFormStrategy):
    """Evotel-specific cancellation form strategy with date setting"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def initiate_cancellation(self, driver: webdriver.Chrome) -> bool:
        """Click cancel service button"""
        try:
            wait = WebDriverWait(driver, 15)
            
            # Verify we're on the service info page
            current_url = driver.current_url
            if "/Service/Info/" not in current_url:
                self.logger.error(f"Not on service info page. Current URL: {current_url}")
                return False
            
            self.logger.info(f"On service info page: {current_url}")
            
            # Find cancel service button
            cancel_button_selectors = [
                "//a[text()='Cancel Service']",
                "//a[contains(text(), 'Cancel Service')]",
                "//a[contains(@href, '/Service/Cancel/')]",
                "div.container a:nth-of-type(3)",
                "//*[@id='divInfoArea']//a[contains(text(), 'Cancel')]"
            ]
            
            cancel_button = None
            for selector in cancel_button_selectors:
                try:
                    if selector.startswith("//"):
                        cancel_button = wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                    else:
                        cancel_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                    
                    self.logger.info(f"Found Cancel Service button using selector: {selector}")
                    break
                except TimeoutException:
                    continue
            
            if not cancel_button:
                self.logger.error("Cancel Service button not found")
                return False
            
            # Click the cancel button
            if not robust_click(driver, cancel_button, "cancel service button"):
                return False
            
            # Wait for cancellation page
            try:
                WebDriverWait(driver, 15).until(EC.url_contains("/Service/Cancel/"))
                self.logger.info("Successfully navigated to cancellation page")
                return True
            except TimeoutException:
                self.logger.error("Did not navigate to cancellation page")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to initiate cancellation: {str(e)}")
            return False
    
    def fill_cancellation_form(self, driver: webdriver.Chrome, reason: str, comment: str, cancellation_date: str = None) -> bool:
        """Fill cancellation form with reason, comment, and date"""
        try:
            wait = WebDriverWait(driver, 15)
            
            # Fill cancellation reason dropdown
            reason_dropdown = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#CancellationReason"))
            )
            
            Select(reason_dropdown).select_by_visible_text(reason)
            self.logger.info(f"Selected cancellation reason: {reason}")
            
            # Fill comment field
            comment_field = driver.find_element(By.CSS_SELECTOR, "#CancellationComment")
            comment_field.clear()
            comment_field.send_keys(comment)
            self.logger.info(f"Entered cancellation comment: {comment}")
            
            # Set cancellation effective date
            if not self._set_cancellation_date(driver, cancellation_date):
                self.logger.warning("Failed to set cancellation date, continuing anyway")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to fill cancellation form: {str(e)}")
            return False
    
    def _set_cancellation_date(self, driver: webdriver.Chrome, cancellation_date: str = None) -> bool:
        """Set the cancellation effective date using date picker"""
        try:
            # Use provided date or calculate exactly 30 days from current date
            if not cancellation_date:
                from datetime import date, timedelta
                target_date = date.today() + timedelta(days=30)
                cancellation_date = target_date.strftime("%d/%m/%Y")
            
            self.logger.info(f"Setting cancellation date to: {cancellation_date}")
            
            # Find the cancellation effective date field
            date_field_selectors = [
                "#CancellationEffectiveDate",
                "input[name='CancellationEffectiveDate']",
                "input[id*='EffectiveDate']"
            ]
            
            date_field = None
            for selector in date_field_selectors:
                try:
                    date_field = driver.find_element(By.CSS_SELECTOR, selector)
                    break
                except NoSuchElementException:
                    continue
            
            if not date_field:
                self.logger.warning("Cancellation effective date field not found")
                return False
            
            # Click on the date field to open date picker
            if not robust_click(driver, date_field, "cancellation effective date field"):
                return False
            
            time.sleep(1)  # Wait for date picker to appear
            
            # Check if date picker is visible
            try:
                date_picker = driver.find_element(By.ID, "ui-datepicker-div")
                if date_picker.is_displayed():
                    self.logger.info("Date picker opened successfully")
                    return self._navigate_date_picker(driver, cancellation_date)
                else:
                    # Try direct input if date picker doesn't appear
                    return self._set_date_directly(driver, date_field, cancellation_date)
            except NoSuchElementException:
                # Try direct input if date picker doesn't exist
                return self._set_date_directly(driver, date_field, cancellation_date)
                
        except Exception as e:
            self.logger.error(f"Error setting cancellation date: {str(e)}")
            return False
    
    def _navigate_date_picker(self, driver: webdriver.Chrome, target_date: str) -> bool:
        """Navigate the date picker to select the target date"""
        try:
            # Parse target date (DD/MM/YYYY)
            day, month, year = map(int, target_date.split("/"))
            
            # Get current date picker month/year
            current_month_year = driver.find_element(By.CLASS_NAME, "ui-datepicker-title")
            current_text = current_month_year.text  # e.g., "August 2025"
            
            # Navigate to correct month (simplified navigation)
            # For dates 30 days in future, we may need to navigate forward one month
            try:
                next_button = driver.find_element(By.CSS_SELECTOR, "a.ui-datepicker-next > span")
                if next_button.is_displayed():
                    robust_click(driver, next_button, "date picker next button")
                    time.sleep(0.5)
            except NoSuchElementException:
                pass
            
            # Click on the target day
            day_selectors = [
                f"//a[text()='{day}']",
                f"//td/a[text()='{day}']",
            ]
            
            # Add fallback selector for 2nd row, 3rd column if exact day not found
            day_selectors.append("tr:nth-of-type(2) > td:nth-of-type(3) > a")
            
            for selector in day_selectors:
                try:
                    if selector.startswith("//"):
                        day_link = driver.find_element(By.XPATH, selector)
                    else:
                        day_link = driver.find_element(By.CSS_SELECTOR, selector)
                    
                    if day_link.is_displayed():
                        robust_click(driver, day_link, f"day {day}")
                        self.logger.info(f"Selected day {day} from date picker")
                        time.sleep(0.5)
                        return True
                except NoSuchElementException:
                    continue
            
            self.logger.warning(f"Could not find day {day} in date picker")
            return False
            
        except Exception as e:
            self.logger.error(f"Error navigating date picker: {str(e)}")
            return False
    
    def _set_date_directly(self, driver: webdriver.Chrome, date_field, target_date: str) -> bool:
        """Set date directly in the input field"""
        try:
            # Clear field and set date directly
            date_field.clear()
            date_field.send_keys(target_date)
            
            # Trigger change event
            driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", date_field)
            
            self.logger.info(f"Set cancellation date directly: {target_date}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error setting date directly: {str(e)}")
            return False
    
    def confirm_cancellation(self, driver: webdriver.Chrome) -> bool:
        """Confirm cancellation submission"""
        try:
            # Find and click confirm button
            confirm_button = driver.find_element(By.XPATH, "//input[@value='Confirm Cancellation']")
            
            if not robust_click(driver, confirm_button, "confirm cancellation button"):
                raise Exception("Failed to click confirm cancellation button")
            
            # Wait for redirect back to service info
            WebDriverWait(driver, 15).until(EC.url_contains("/Service/Info/"))
            
            self.logger.info("Cancellation confirmed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to confirm cancellation: {str(e)}")
            return False
        
class EvotelWorkOrderStrategy(IWorkOrderStrategy):
    """Evotel-specific work order management strategy"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def navigate_to_work_orders(self, driver: webdriver.Chrome) -> bool:
        """Navigate to work orders section"""
        try:
            wait = WebDriverWait(driver, 15)
            
            current_url = driver.current_url
            if "/Service/Info/" not in current_url:
                self.logger.error(f"Not on service info page. Current URL: {current_url}")
                return False
            
            # Click work orders menu
            work_orders_menu = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#work-orders > span"))
            )
            
            if not robust_click(driver, work_orders_menu, "work orders menu"):
                raise Exception("Failed to click work orders menu")
            
            time.sleep(2)
            
            # Get work order links and filter out email links
            all_links = driver.find_elements(By.XPATH, "//*[@id='ui-id-3']/dl/dd/a")
            
            work_order_links = []
            for link in all_links:
                try:
                    href = link.get_attribute("href") or ""
                    link_text = link.text.strip()
                    
                    if "mailto:" in href.lower():
                        continue
                    
                    if re.match(r'^\d{8}-\d+$', link_text) or "WorkOrder" in href:
                        work_order_links.append(link)
                    
                except Exception as e:
                    continue
            
            if not work_order_links:
                self.logger.error("No valid work order links found")
                return False
            
            # Click first work order
            first_work_order = work_order_links[0]
            work_order_text = first_work_order.text
            
            if not robust_click(driver, first_work_order, "work order link"):
                raise Exception("Failed to click work order link")
            
            # Wait for work order page
            WebDriverWait(driver, 15).until(EC.url_contains("/WorkOrder/Item/"))
            
            self.logger.info("Successfully navigated to work order page")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to navigate to work orders: {str(e)}")
            return False
    
    def update_work_order_status(self, driver: webdriver.Chrome, comment: str) -> Optional[str]:
        """Update work order status to completed"""
        try:
            wait = WebDriverWait(driver, 15)
            
            # Extract work order reference
            work_order_ref = None
            try:
                ref_element = driver.find_element(By.XPATH, "//span[@class='small' and contains(text(), 'Ref:')]")
                ref_text = ref_element.text
                ref_match = re.search(r'Ref:\s*(\d{8}-\d+)', ref_text)
                if ref_match:
                    work_order_ref = ref_match.group(1)
            except:
                current_url = driver.current_url
                work_order_match = re.search(r'/WorkOrder/Item/([a-f0-9-]+)', current_url)
                work_order_ref = work_order_match.group(1) if work_order_match else "unknown"
            
            # Update status dropdown to completed
            status_dropdown = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#StatusId"))
            )
            
            Select(status_dropdown).select_by_value("c14c051e-d259-426f-a2b1-e869e5300bcc")
            self.logger.info("Updated work order status to completed")
            
            # Fill comments field
            comments_field = driver.find_element(By.CSS_SELECTOR, "#Comments")
            comments_field.clear()
            comments_field.send_keys(comment)
            
            # Check "No user notification" checkbox
            notification_checkbox = driver.find_element(By.CSS_SELECTOR, "#NoUserNotification")
            if not notification_checkbox.is_selected():
                robust_click(driver, notification_checkbox, "no notification checkbox")
            
            # Submit work order update
            submit_button = driver.find_element(By.XPATH, "//input[@value='Submit']")
            
            if not robust_click(driver, submit_button, "submit button"):
                raise Exception("Failed to submit work order update")
            
            # Wait for success confirmation
            WebDriverWait(driver, 15).until(EC.url_contains("success=0"))
            
            self.logger.info(f"Work order {work_order_ref} updated successfully")
            return work_order_ref
            
        except Exception as e:
            self.logger.error(f"Failed to update work order: {str(e)}")
            return None

# ==================== PAGE OBJECTS ====================

class EvotelLoginPage:
    """Page object for Evotel login functionality"""
    
    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver
        self.logger = logging.getLogger(self.__class__.__name__)
        self.wait = WebDriverWait(driver, 30)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        retry=retry_if_exception_type((TimeoutException, WebDriverException))
    )
    def login(self):
        """Perform login to Evotel portal"""
        try:
            self.logger.info("Starting Evotel login process")
            
            # Navigate to login page
            self.driver.get(Config.EVOTEL_URL)
            
            # Wait for page load
            WebDriverWait(self.driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            # Find and fill email field
            email_field = self.wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#Email"))
            )
            
            if not robust_click(self.driver, email_field, "email field"):
                raise Exception("Failed to click email field")
            
            email_field.clear()
            email_field.send_keys(Config.EVOTEL_EMAIL)
            self.logger.info("Email entered successfully")
            
            # Find and fill password field
            password_field = self.wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#Password"))
            )
            
            if not robust_click(self.driver, password_field, "password field"):
                raise Exception("Failed to click password field")
            
            password_field.clear()
            password_field.send_keys(Config.EVOTEL_PASSWORD)
            self.logger.info("Password entered successfully")
            
            # Find and click login button
            login_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='loginForm']/form/div[4]/div/button"))
            )
            
            if not robust_click(self.driver, login_button, "login button"):
                raise Exception("Failed to click login button")
            
            # Wait for successful login
            try:
                WebDriverWait(self.driver, 20).until(EC.url_contains("/Manage/Index"))
                self.logger.info("Login successful")
                return True
                
            except TimeoutException:
                current_url = self.driver.current_url
                page_title = self.driver.title
                
                if "/Manage" in current_url or "manage" in page_title.lower():
                    self.logger.info("Login appears successful based on URL/title")
                    return True
                else:
                    self.logger.error(f"Login failed - still on: {current_url}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Login failed: {str(e)}")
            raise

# ==================== MAIN AUTOMATION CLASS ====================

class EvotelCancellationAutomation:
    """Enhanced Evotel cancellation automation with sophisticated service selection"""
    
    def __init__(self, 
                 config: Config,
                 error_detection_strategy: IErrorDetectionStrategy,
                 service_search_strategy: IServiceSearchStrategy,
                 cancellation_form_strategy: ICancellationFormStrategy,
                 work_order_strategy: IWorkOrderStrategy):
        
        self.config = config
        self.error_detection_strategy = error_detection_strategy
        self.service_search_strategy = service_search_strategy
        self.cancellation_form_strategy = cancellation_form_strategy
        self.work_order_strategy = work_order_strategy
        
        self.logger = logging.getLogger(self.__class__.__name__)
        self.browser_service: Optional[BrowserService] = None
        self.screenshot_service: Optional[ScreenshotService] = None
        self.driver: Optional[webdriver.Chrome] = None
    
    def _setup_services(self, job_id: str):
        """Setup required services"""
        self.browser_service = BrowserService(self.config)
        self.driver = self.browser_service.create_driver(job_id)
        self.screenshot_service = ScreenshotService(job_id)
    
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
        """Main cancellation method with date setting"""
        start_time = time.time()
        
        try:
            self.logger.info(f"=== STARTING EVOTEL CANCELLATION ===")
            self.logger.info(f"Job: {request.job_id}, Circuit: {request.circuit_number}")
            
            # Setup services
            self._setup_services(request.job_id)
            self.screenshot_service.take_screenshot(self.driver, "cancellation_initial_state")
            
            # STEP 1: Login
            self.logger.info("STEP 1: Performing login to Evotel portal")
            login_page = EvotelLoginPage(self.driver)
            login_page.login()
            self.screenshot_service.take_screenshot(self.driver, "cancellation_after_login")
            
            # STEP 2: Search for service
            self.logger.info("STEP 2: Searching for service")
            if not self.service_search_strategy.search_service(self.driver, request.circuit_number):
                self.screenshot_service.take_screenshot(self.driver, "cancellation_service_not_found")
                return self._create_not_found_result(request)
            
            self.screenshot_service.take_screenshot(self.driver, "cancellation_search_results")
            
            # STEP 3: Navigate to service
            self.logger.info("STEP 3: Navigating to service")
            service_uuid = self.service_search_strategy.navigate_to_service(self.driver)
            if not service_uuid:
                return self._create_error_result(request, "Failed to navigate to service")
            
            self.screenshot_service.take_screenshot(self.driver, "cancellation_service_selected")
            self.logger.info(f"Service selected, UUID: {service_uuid}")
            
            # Check for errors
            if self.error_detection_strategy.has_error(self.driver):
                self.screenshot_service.take_screenshot(self.driver, "cancellation_error_detected")
                return self._create_error_result(request, "Error detected on service page")
            
            # STEP 4: Initiate cancellation
            self.logger.info("STEP 4: Initiating cancellation")
            if not self.cancellation_form_strategy.initiate_cancellation(self.driver):
                return self._create_error_result(request, "Failed to initiate cancellation")
            
            self.screenshot_service.take_screenshot(self.driver, "cancellation_form_page")
            
            # STEP 5: Fill cancellation form with date
            self.logger.info("STEP 5: Filling cancellation form with date")
            if not self.cancellation_form_strategy.fill_cancellation_form(
                self.driver, 
                "USING ANOTHER FNO", 
                "Bot cancellation",
                request.requested_date  # Pass the requested date
            ):
                return self._create_error_result(request, "Failed to fill cancellation form")
            
            self.screenshot_service.take_screenshot(self.driver, "cancellation_form_filled")
            
            # STEP 6: Confirm cancellation
            self.logger.info("STEP 6: Confirming cancellation")
            if not self.cancellation_form_strategy.confirm_cancellation(self.driver):
                return self._create_error_result(request, "Failed to confirm cancellation")
            
            self.screenshot_service.take_screenshot(self.driver, "cancellation_confirmed")
            
            # STEP 7: Navigate to work orders
            self.logger.info("STEP 7: Navigating to work orders")
            if not self.work_order_strategy.navigate_to_work_orders(self.driver):
                return self._create_error_result(request, "Failed to navigate to work orders")
            
            self.screenshot_service.take_screenshot(self.driver, "cancellation_work_order_page")
            
            # STEP 8: Update work order status
            self.logger.info("STEP 8: Updating work order status")
            work_order_ref = self.work_order_strategy.update_work_order_status(
                self.driver, "Bot cancellation"
            )
            
            if not work_order_ref:
                return self._create_error_result(request, "Failed to update work order")
            
            self.screenshot_service.take_screenshot(self.driver, "cancellation_work_order_updated")
            
            # Create success result
            execution_time = time.time() - start_time
            self.logger.info(f"=== EVOTEL CANCELLATION COMPLETED SUCCESSFULLY ===")
            self.logger.info(f"Work order reference: {work_order_ref}")
            return self._create_success_result(request, service_uuid, work_order_ref, execution_time)
            
        except Exception as e:
            self.logger.error(f"Cancellation failed: {str(e)}")
            self.logger.error(traceback.format_exc())
            
            if self.screenshot_service and self.driver:
                self.screenshot_service.take_screenshot(self.driver, "error_state")
            
            return self._create_error_result(request, str(e))
            
        finally:
            self._cleanup_services()
    
    def _create_success_result(self, request: CancellationRequest, service_uuid: str, 
                             work_order_ref: str, execution_time: float) -> CancellationResult:
        """Create success result"""
        cancellation_details = CancellationDetails(
            work_order_number=work_order_ref,
            service_uuid=service_uuid,
            external_reference=request.solution_id,
            requested_date=request.requested_date,
            submission_date=datetime.now(),
            status="completed",
            confirmation_received=True,
            work_order_updated=True
        )
        
        return CancellationResult(
            job_id=request.job_id,
            circuit_number=request.circuit_number,
            status=CancellationStatus.SUCCESS,
            message=f"Successfully cancelled service {request.circuit_number} using enhanced selection and updated work order {work_order_ref}",
            result_type=CancellationResultType.SUBMITTED,
            cancellation_details=cancellation_details,
            execution_time=execution_time,
            screenshots=self.screenshot_service.get_all_screenshots() if self.screenshot_service else [],
            evidence_dir=str(self.screenshot_service.evidence_dir) if self.screenshot_service else None
        )
    
    def _create_not_found_result(self, request: CancellationRequest) -> CancellationResult:
        """Create result for service not found"""
        return CancellationResult(
            job_id=request.job_id,
            circuit_number=request.circuit_number,
            status=CancellationStatus.FAILURE,
            message=f"Service {request.circuit_number} not found in Evotel portal",
            result_type=CancellationResultType.NOT_FOUND,
            screenshots=self.screenshot_service.get_all_screenshots() if self.screenshot_service else [],
            evidence_dir=str(self.screenshot_service.evidence_dir) if self.screenshot_service else None
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
            evidence_dir=str(self.screenshot_service.evidence_dir) if self.screenshot_service else None,
            error_details={"error": error_message, "timestamp": datetime.now().isoformat()}
        )

# ==================== FACTORY ====================

class EvotelCancellationFactory:
    """Factory for creating simplified Evotel cancellation automation"""
    
    @staticmethod
    def create_automation(config: Config) -> EvotelCancellationAutomation:
        """Create simplified Evotel cancellation automation"""
        return EvotelCancellationAutomation(
            config=config,
            error_detection_strategy=StandardErrorDetectionStrategy(),
            service_search_strategy=SimplifiedEvotelServiceSearchStrategy(),  # Use simplified strategy
            cancellation_form_strategy=EvotelCancellationFormStrategy(),
            work_order_strategy=EvotelWorkOrderStrategy()
        )

# ==================== MAIN EXECUTION FUNCTION ====================

def execute(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execution function for Evotel cancellation with date setting.
    Includes validation execution at the end for comprehensive data collection.
    """
    
    logger.info("=== EVOTEL CANCELLATION EXECUTE FUNCTION STARTED ===")
    
    # Extract parameters
    job_id = parameters.get("job_id")
    circuit_number = parameters.get("circuit_number")
    solution_id = parameters.get("solution_id")
    requested_date = parameters.get("requested_date")  # Extract requested date
    
    logger.info(f"Parameters: job_id={job_id}, circuit_number={circuit_number}, solution_id={solution_id}, requested_date={requested_date}")
    
    # Initialize results structure
    results = {
        "status": "failure",
        "message": "",
        "evidence": [],
        "screenshot_data": [],
        "details": {}
    }
    
    try:
        logger.info("=== STARTING PARAMETER VALIDATION ===")
        
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
        
        # Generate solution_id if not provided
        if not solution_id:
            solution_id = f"EVOTEL_{job_id}"
            logger.info(f"Generated solution_id: {solution_id}")
        
        # Set date if not provided (exactly 30 days from current date)
        if not requested_date:
            from datetime import date, timedelta
            target_date = date.today() + timedelta(days=30)
            requested_date = target_date.strftime("%d/%m/%Y")
            logger.info(f"Calculated requested_date (30 days from now): {requested_date}")
        
        logger.info("=== PARAMETER VALIDATION PASSED ===")
        
        # Validate configuration
        if not all([Config.EVOTEL_URL, Config.EVOTEL_EMAIL, Config.EVOTEL_PASSWORD]):
            logger.error("Configuration validation failed")
            return {
                "status": "error",
                "message": "Missing required Evotel configuration",
                "details": {"error": "Evotel credentials not configured"},
                "screenshot_data": []
            }
        
        # Create cancellation request
        request = CancellationRequest(
            job_id=job_id,
            circuit_number=circuit_number,
            solution_id=solution_id,
            requested_date=requested_date
        )
        
        # Create simplified automation
        automation = EvotelCancellationFactory.create_automation(Config)
        
        # Execute cancellation
        logger.info("=== STARTING CANCELLATION EXECUTION ===")
        result = automation.cancel_service(request)
        logger.info(f"Cancellation completed with status: {result.status}")
        
        # Convert to dictionary for compatibility
        results = {
            "status": "success" if result.status == CancellationStatus.SUCCESS else "failure",
            "message": result.message,
            "details": {
                "found": result.status in [CancellationStatus.SUCCESS, CancellationStatus.ALREADY_CANCELLED],
                "circuit_number": result.circuit_number,
                "result_type": result.result_type.value,
                "cancellation_status": result.status.value,
                "execution_time": result.execution_time,
                "cancellation_details": result.cancellation_details.dict() if result.cancellation_details else None,
                "error_details": result.error_details,
                "requested_date": requested_date,
                # Add fields for orchestrator
                "cancellation_submitted": result.status == CancellationStatus.SUCCESS,
                "cancellation_captured_id": result.cancellation_details.work_order_number if result.cancellation_details else None,
                "service_found": result.result_type != CancellationResultType.NOT_FOUND,
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
        
        logger.info("=== CANCELLATION MODULE COMPLETED SUCCESSFULLY ===")
        
    except Exception as e:
        logger.error(f"=== CANCELLATION EXECUTION FAILED ===")
        logger.error(f"Exception: {str(e)}")
        logger.error(traceback.format_exc())
        
        results = {
            "status": "error",
            "message": f"Execution error: {str(e)}",
            "details": {
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc()
            },
            "screenshot_data": []
        }
    
    finally:
        # ALWAYS execute validation for data collection
        time.sleep(3)
        
        logger.info(f"=== STARTING POST-CANCELLATION VALIDATION ===")
        
        if validation_execute:
            try:
                # Use validation to get updated data
                validation_result = validation_execute({
                    "job_id": job_id,
                    "circuit_number": circuit_number
                })
                
                # Replace details with validation data
                if "details" in validation_result and validation_result["details"]:
                    results["details"] = validation_result["details"]
                    logger.info(f"Successfully replaced details with post-cancellation validation data")
                    
                    # Merge validation screenshots
                    if "screenshot_data" in validation_result and validation_result["screenshot_data"]:
                        existing_screenshots = results.get("screenshot_data", [])
                        validation_screenshots = validation_result["screenshot_data"]
                        results["screenshot_data"] = existing_screenshots + validation_screenshots
                        
            except Exception as validation_error:
                logger.error(f"Post-cancellation validation failed: {str(validation_error)}")
                if "details" not in results:
                    results["details"] = {}
                results["details"]["validation_error"] = str(validation_error)
        else:
            logger.warning("Validation module not available")
    
    logger.info("=== EVOTEL CANCELLATION EXECUTE FUNCTION COMPLETED ===")
    return results