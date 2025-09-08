"""
Evotel Validation Module - Enhanced with Comprehensive Data Extraction
=====================================================================
Streamlined automation for Evotel service validation with complete data capture
Based on the Octotel validation architecture with comprehensive extraction
Updated to use circuit_number for uniformity across all FNO providers
"""

import os
import time
import logging
import traceback
import json
import base64
import re
from datetime import datetime
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

class ValidationStatus(str, Enum):
    """Job execution status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"

class SearchResult(str, Enum):
    """Service search result"""
    FOUND = "found"
    NOT_FOUND = "not_found"
    ERROR = "error"

class ServiceStatus(str, Enum):
    """Service operational status"""
    ACTIVE = "active"
    CANCELLED = "cancelled"
    PENDING = "pending"
    UNKNOWN = "unknown"

# ==================== DATA MODELS ====================

class ValidationRequest(BaseModel):
    """Input model for validation requests - Updated to use circuit_number"""
    job_id: str = Field(..., description="Unique job identifier")
    circuit_number: str = Field(..., description="Circuit number to validate (maps to Evotel serial number)")

class ScreenshotData(BaseModel):
    """Screenshot metadata and data container"""
    name: str
    timestamp: datetime
    data: str  # Base64 encoded image
    path: str
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

class ServiceData(BaseModel):
    """Service information container"""
    service_id: str
    service_type: Optional[str] = None
    customer_name: Optional[str] = None
    status: ServiceStatus
    work_orders: List[Dict] = []
    service_details: Optional[Dict] = None
    extraction_timestamp: Optional[str] = None

class ValidationResult(BaseModel):
    """Complete validation result container - Updated to use circuit_number"""
    job_id: str
    circuit_number: str
    status: ValidationStatus
    message: str
    found: bool
    service_data: Optional[ServiceData] = None
    search_result: SearchResult
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

# ==================== INPUT HANDLER ====================

class RobustInputHandler:
    """Robust input handling for form fields"""
    
    def __init__(self, logger):
        self.logger = logger
    
    def fill_input_robustly(self, element, value: str) -> bool:
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
    
    def _method_clear_and_send_keys(self, element, value: str) -> bool:
        """Standard clear and send keys method"""
        element.clear()
        element.send_keys(value)
        return True
    
    def _method_javascript_fill(self, element, value: str) -> bool:
        """JavaScript fill method"""
        driver = element._parent
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

# ==================== BROWSER SERVICE ====================

class BrowserService:
    """Browser service with local chromedriver"""
    
    def __init__(self):
        self.driver: Optional[webdriver.Chrome] = None
    
    def create_driver(self, job_id: str) -> webdriver.Chrome:
        """Create Chrome driver with debug-proven stable options"""
        options = ChromeOptions()
    
        # Use the same options that worked in debug
        headless_env = os.getenv("HEADLESS", "true").lower()
        should_be_headless = headless_env != "false"
    
        if should_be_headless:
            options.add_argument('--headless=new')
            logger.info("Running Chrome in HEADLESS mode")
        else:
            logger.info("Running Chrome in VISIBLE mode")
    
        # PROVEN STABLE OPTIONS (from debug script)
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--start-maximized')
    
        # CRASH PREVENTION
        options.add_argument('--disable-crash-reporter')
        options.add_argument('--disable-logging')
        options.add_argument('--log-level=3')
    
        # STABILITY IMPROVEMENTS
        options.add_argument('--disable-background-timer-throttling')
        options.add_argument('--disable-backgrounding-occluded-windows')
        options.add_argument('--disable-renderer-backgrounding')
        options.add_argument('--disable-features=TranslateUI')
        options.add_argument('--disable-extensions')
    
        service = Service(executable_path=Config.CHROMEDRIVER_PATH)
        self.driver = webdriver.Chrome(service=service, options=options)
    
        # CONSERVATIVE TIMEOUTS (matching debug script)
        self.driver.set_page_load_timeout(30)
        self.driver.implicitly_wait(5)
    
        if not should_be_headless:
            self.driver.maximize_window()
        
        logger.info("Browser setup complete with debug-proven options")
        return self.driver
    
    def cleanup(self):
        """Enhanced cleanup with better error handling"""
        if self.driver:
            try:
                # First try graceful shutdown
                self.driver.quit()
                logger.info("Browser cleaned up successfully")
            except Exception as e:
                logger.warning(f"Graceful browser cleanup failed: {str(e)}")
                
                # Force cleanup if graceful fails
                try:
                    import psutil
                    import os
                    
                    # Kill any remaining Chrome processes
                    for proc in psutil.process_iter(['pid', 'name']):
                        if 'chrome' in proc.info['name'].lower():
                            try:
                                proc.kill()
                                logger.info(f"Force killed Chrome process: {proc.info['pid']}")
                            except:
                                pass
                                
                except ImportError:
                    logger.warning("psutil not available for force cleanup")
                except Exception as cleanup_error:
                    logger.error(f"Force cleanup failed: {str(cleanup_error)}")
                    
            finally:
                self.driver = None

# ==================== SCREENSHOT SERVICE ====================

class ScreenshotService:
    """Screenshot service for evidence collection"""
    
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.evidence_dir = Path(Config.get_job_screenshot_dir(job_id))
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots: List[ScreenshotData] = []
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def take_screenshot(self, driver: webdriver.Chrome, name: str) -> Optional[ScreenshotData]:
        """Capture and encode screenshot for evidence"""
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
            self.logger.info(f"Screenshot saved: {filename}")
            return screenshot
            
        except Exception as e:
            self.logger.error(f"Failed to take screenshot: {str(e)}")
            return None
    
    def get_all_screenshots(self) -> List[ScreenshotData]:
        """Get all screenshots taken"""
        return self.screenshots

# ==================== LOGIN HANDLER ====================

class EvotelLogin:
    """Email/password authentication handler for Evotel portal"""
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        retry=retry_if_exception_type((TimeoutException, WebDriverException, ElementNotInteractableException))
    )
    def login(self, driver: webdriver.Chrome) -> bool:
        """Execute complete login flow with email/password authentication"""
        try:
            logger.info("Starting Evotel login process")
            
            # Navigate to login page
            driver.get(Config.EVOTEL_URL)
            
            # Wait for page load
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            logger.info("Login page loaded successfully")
            
            # Find and fill email field
            logger.info("Locating email field")
            wait = WebDriverWait(driver, 15)
            
            email_field = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#Email"))
            )
            
            if not robust_click(driver, email_field, "email field"):
                raise Exception("Failed to click email field")
            
            # Enter email
            email_field.clear()
            email_field.send_keys(Config.EVOTEL_EMAIL)
            logger.info("Email entered successfully")
            
            # Find and fill password field
            logger.info("Locating password field")
            password_field = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#Password"))
            )
            
            if not robust_click(driver, password_field, "password field"):
                raise Exception("Failed to click password field")
            
            # Enter password
            password_field.clear()
            password_field.send_keys(Config.EVOTEL_PASSWORD)
            logger.info("Password entered successfully")
            
            # Find and click login button
            logger.info("Locating login button")
            login_button = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='loginForm']/form/div[4]/div/button"))
            )
            
            if not robust_click(driver, login_button, "login button"):
                raise Exception("Failed to click login button")
            
            logger.info("Login form submitted")
            
            # Wait for successful login - should redirect to Manage page
            logger.info("Waiting for login success")
            try:
                WebDriverWait(driver, 20).until(
                    EC.url_contains("/Manage/Index")
                )
                logger.info("Login successful - redirected to Manage page")
                return True
                
            except TimeoutException:
                # Check for other success indicators
                current_url = driver.current_url
                page_title = driver.title
                
                if "/Manage" in current_url or "manage" in page_title.lower():
                    logger.info("Login appears successful based on URL/title")
                    return True
                else:
                    logger.error(f"Login failed - still on: {current_url}")
                    logger.error(f"Page title: {page_title}")
                    return False
                    
        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            raise

# ==================== COMPREHENSIVE DATA EXTRACTOR ====================

class ComprehensiveEvotelDataExtractor:
    """Enhanced data extractor that captures ALL information from Evotel pages"""
    
    def __init__(self, driver, logger):
        self.driver = driver
        self.logger = logger
    
    def extract_complete_work_order_data(self) -> Dict[str, Any]:
        """
        Extract ALL data from the work order page - comprehensive extraction
        following the same thorough approach as Octotel validation
        """
        try:
            self.logger.info("Starting comprehensive work order data extraction")
            
            # Get complete page text for backup
            full_page_text = self.driver.find_element(By.TAG_NAME, "body").text
            
            # Extract structured data sections
            extraction_result = {
                "extraction_metadata": {
                    "extraction_timestamp": datetime.now().isoformat(),
                    "page_url": self.driver.current_url,
                    "page_title": self.driver.title,
                    "full_page_text": full_page_text,
                    "text_length": len(full_page_text)
                },
                
                # Main sections
                "work_order_header": self._extract_work_order_header(),
                "client_details": self._extract_client_details(),
                "service_details": self._extract_service_details(),
                "work_order_details": self._extract_work_order_details(),
                "isp_details": self._extract_isp_details(),
                "ont_number_details": self._extract_ont_number_details(),
                
                # Additional data
                "all_references": self._extract_all_references(full_page_text),
                "all_dates": self._extract_all_dates(full_page_text),
                "all_status_indicators": self._extract_all_status_indicators(full_page_text),
                "technical_identifiers": self._extract_technical_identifiers(full_page_text)
            }
            
            # Calculate data completeness
            extraction_result["data_completeness"] = self._assess_extraction_completeness(extraction_result)
            
            self.logger.info("Comprehensive work order extraction completed")
            return extraction_result
            
        except Exception as e:
            self.logger.error(f"Error in comprehensive extraction: {str(e)}")
            return {
                "extraction_error": str(e),
                "partial_data": self._emergency_text_extraction()
            }
    
    def _extract_work_order_header(self) -> Dict[str, Any]:
        """Extract work order header information"""
        try:
            header_data = {}
            
            # Look for main heading
            try:
                main_heading = self.driver.find_element(By.XPATH, "//h1 | //h2[contains(@class, 'title')] | //*[contains(text(), 'Provisioning Work Order')]").text
                header_data["main_heading"] = main_heading
            except:
                pass
            
            # Extract reference number from header
            try:
                ref_element = self.driver.find_element(By.XPATH, "//*[contains(text(), 'Ref:')]/following-sibling::* | //*[contains(text(), 'Ref:')]")
                header_data["reference_number"] = self._clean_text(ref_element.text)
            except:
                # Fallback - extract from text
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
                ref_match = re.search(r"Ref:\s*(\d{8}-\d+)", page_text)
                if ref_match:
                    header_data["reference_number"] = ref_match.group(1)
            
            # Extract creation info
            try:
                created_element = self.driver.find_element(By.XPATH, "//*[contains(text(), 'Created by')]")
                header_data["created_by"] = self._clean_text(created_element.text)
            except:
                pass
            
            return header_data
            
        except Exception as e:
            self.logger.error(f"Error extracting work order header: {str(e)}")
            return {"error": str(e)}
    
    def _extract_client_details(self) -> Dict[str, Any]:
        """Extract comprehensive client information"""
        try:
            client_data = {}
            
            # Define field mappings for client section
            client_fields = {
                "client_name": ["Client", "client"],
                "area": ["Area", "area"],
                "address": ["Address", "address"],
                "email": ["E-Mail", "email", "e-mail"],
                "mobile": ["Mobile", "mobile", "phone", "cell"]
            }
            
            # Extract each field
            for field_name, field_labels in client_fields.items():
                value = self._extract_field_value(field_labels)
                if value:
                    client_data[field_name] = value
            
            # Try to extract address components
            if "address" in client_data:
                address_components = self._parse_address(client_data["address"])
                client_data["address_components"] = address_components
            
            # Extract email as clickable link
            try:
                email_link = self.driver.find_element(By.XPATH, "//a[contains(@href, 'mailto:')]")
                client_data["email_link"] = email_link.get_attribute("href")
                if not client_data.get("email"):
                    client_data["email"] = email_link.text
            except:
                pass
            
            return client_data
            
        except Exception as e:
            self.logger.error(f"Error extracting client details: {str(e)}")
            return {"error": str(e)}
    
    def _extract_service_details(self) -> Dict[str, Any]:
        """Extract comprehensive service information"""
        try:
            service_data = {}
            
            # Define service field mappings
            service_fields = {
                "service_provider": ["Service Provider", "provider"],
                "product": ["Product", "product"],
                "contract": ["Contract", "contract"],
                "parent_product": ["Parent Product", "parent product"],
                "service_status": ["Service Status", "status"],
                "application_date": ["Application Date", "application date"],
                "effective_date": ["Effective Date", "effective date"],
                "isp_effective_date": ["ISP Effective Date", "isp effective date"]
            }
            
            # Extract each field
            for field_name, field_labels in service_fields.items():
                value = self._extract_field_value(field_labels)
                if value:
                    service_data[field_name] = value
            
            # Parse specific service information
            if "product" in service_data:
                service_data["product_details"] = self._parse_product_details(service_data["product"])
            
            # Extract parent product link if available
            try:
                parent_product_link = self.driver.find_element(By.XPATH, "//*[contains(text(), 'Parent Product')]/following-sibling::*//a")
                service_data["parent_product_link"] = parent_product_link.get_attribute("href")
            except:
                pass
            
            return service_data
            
        except Exception as e:
            self.logger.error(f"Error extracting service details: {str(e)}")
            return {"error": str(e)}
    
    def _extract_work_order_details(self) -> Dict[str, Any]:
        """Extract work order specific details"""
        try:
            wo_data = {}
            
            # Work order field mappings
            wo_fields = {
                "reference": ["Reference", "reference"],
                "status": ["Status", "status"],
                "isp_provisioned": ["ISP Provisioned", "isp provisioned"],
                "scheduled_time": ["Scheduled Time", "scheduled time"],
                "last_comment": ["Last Comment", "last comment"]
            }
            
            # Extract each field
            for field_name, field_labels in wo_fields.items():
                value = self._extract_field_value(field_labels)
                if value:
                    wo_data[field_name] = value
            
            return wo_data
            
        except Exception as e:
            self.logger.error(f"Error extracting work order details: {str(e)}")
            return {"error": str(e)}
    
    def _extract_isp_details(self) -> Dict[str, Any]:
        """Extract ISP specific information"""
        try:
            isp_data = {}
            
            # ISP field mappings
            isp_fields = {
                "reference": ["Reference", "reference"],
                "isp_reference": ["ISP Reference", "isp reference"]
            }
            
            # Look specifically in ISP Details section
            try:
                isp_section = self.driver.find_element(By.XPATH, "//*[contains(text(), 'ISP Details')]/following-sibling::*")
                isp_section_text = isp_section.text
                
                # Extract reference number from ISP section
                ref_match = re.search(r"Reference\s*([A-Z0-9\-]+)", isp_section_text)
                if ref_match:
                    isp_data["reference"] = ref_match.group(1)
                
                # Look for update links
                try:
                    update_link = isp_section.find_element(By.XPATH, ".//a[contains(text(), 'Update')]")
                    isp_data["update_link"] = update_link.get_attribute("href")
                except:
                    pass
                    
            except:
                # Fallback to general extraction
                for field_name, field_labels in isp_fields.items():
                    value = self._extract_field_value(field_labels)
                    if value:
                        isp_data[field_name] = value
            
            return isp_data
            
        except Exception as e:
            self.logger.error(f"Error extracting ISP details: {str(e)}")
            return {"error": str(e)}
    
    def _extract_ont_number_details(self) -> Dict[str, Any]:
        """Extract ONT (Optical Network Terminal) information"""
        try:
            ont_data = {}
            
            # ONT field mappings
            ont_fields = {
                "verification": ["Verification", "verification"],
                "fsan_number": ["FSAN Number", "fsan number"],
                "port_number": ["Port Number", "port number"],
                "ports_available": ["Ports Available", "ports available"],
                "active_services": ["Active Services", "active services"]
            }
            
            # Extract each field
            for field_name, field_labels in ont_fields.items():
                value = self._extract_field_value(field_labels)
                if value:
                    ont_data[field_name] = value
            
            # Parse FSAN number specifically
            if "fsan_number" in ont_data:
                fsan_details = self._parse_fsan_number(ont_data["fsan_number"])
                ont_data["fsan_details"] = fsan_details
            
            # Parse ports information
            if "ports_available" in ont_data:
                ports_info = self._parse_ports_information(ont_data["ports_available"])
                ont_data["ports_info"] = ports_info
            
            # Parse active services
            if "active_services" in ont_data:
                services_info = self._parse_active_services(ont_data["active_services"])
                ont_data["services_info"] = services_info
            
            return ont_data
            
        except Exception as e:
            self.logger.error(f"Error extracting ONT details: {str(e)}")
            return {"error": str(e)}
    
    def _extract_field_value(self, field_labels: List[str]) -> str:
        """Extract value for a field using multiple label variants"""
        for label in field_labels:
            try:
                # Try different XPath patterns
                patterns = [
                    f"//*[contains(text(), '{label}')]/following-sibling::*[1]",
                    f"//*[contains(text(), '{label}')]/parent::*/following-sibling::*[1]",
                    f"//td[contains(text(), '{label}')]/following-sibling::td[1]",
                    f"//th[contains(text(), '{label}')]/following-sibling::td[1]"
                ]
                
                for pattern in patterns:
                    try:
                        element = self.driver.find_element(By.XPATH, pattern)
                        value = self._clean_text(element.text)
                        if value:
                            return value
                    except:
                        continue
                        
                # Try extracting from same element that contains the label
                try:
                    element = self.driver.find_element(By.XPATH, f"//*[contains(text(), '{label}')]")
                    full_text = element.text
                    # Extract value after the label
                    value = full_text.split(label)[-1].strip()
                    if value and value != full_text:
                        return self._clean_text(value)
                except:
                    pass
                    
            except:
                continue
        
        return ""
    
    def _extract_all_references(self, page_text: str) -> Dict[str, List[str]]:
        """Extract all reference numbers from page"""
        references = {
            "work_order_refs": re.findall(r"\b\d{8}-\d+\b", page_text),
            "service_refs": re.findall(r"\b[A-Z]{2,3}\d{6}-\d+\b", page_text),
            "uuids": re.findall(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", page_text, re.IGNORECASE),
            "fsan_numbers": re.findall(r"\b[A-Z0-9]{12,16}\b", page_text),
            "port_numbers": re.findall(r"Port[:\s]+(\d+)", page_text, re.IGNORECASE)
        }
        return references
    
    def _extract_all_dates(self, page_text: str) -> Dict[str, List[str]]:
        """Extract all dates from page"""
        date_patterns = {
            "iso_dates": re.findall(r"\b\d{4}-\d{2}-\d{2}\b", page_text),
            "formatted_dates": re.findall(r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b", page_text),
            "short_dates": re.findall(r"\b\d{2}/\d{2}/\d{4}\b", page_text),
            "timestamps": re.findall(r"\b\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}\b", page_text)
        }
        return date_patterns
    
    def _extract_all_status_indicators(self, page_text: str) -> List[str]:
        """Extract all status-related keywords"""
        status_keywords = [
            "Active", "Inactive", "Pending", "Provisioned", "Cancelled", 
            "Completed", "In Progress", "Failed", "Verified", "Unverified"
        ]
        
        found_statuses = []
        for status in status_keywords:
            if status in page_text:
                found_statuses.append(status)
        
        return found_statuses
    
    def _extract_technical_identifiers(self, page_text: str) -> Dict[str, Any]:
        """Extract technical identifiers and numbers"""
        return {
            "mac_addresses": re.findall(r"\b[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}\b", page_text, re.IGNORECASE),
            "ip_addresses": re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", page_text),
            "circuit_numbers": re.findall(r"\b[A-Z0-9]{8,20}\b", page_text),  # Changed from serial_numbers to circuit_numbers
            "service_ids": re.findall(r"\b[A-F0-9]{32}\b", page_text, re.IGNORECASE)
        }
    
    def _parse_address(self, address_text: str) -> Dict[str, str]:
        """Parse address into components"""
        components = {}
        
        # Split address by commas
        parts = [part.strip() for part in address_text.split(',')]
        
        if len(parts) >= 1:
            components["street"] = parts[0]
        if len(parts) >= 2:
            components["area"] = parts[1]
        if len(parts) >= 3:
            components["city"] = parts[2]
        if len(parts) >= 4:
            components["province"] = parts[3]
        if len(parts) >= 5:
            components["postal_code"] = parts[4]
        if len(parts) >= 6:
            components["country"] = parts[5]
        
        return components
    
    def _parse_product_details(self, product_text: str) -> Dict[str, str]:
        """Parse product information"""
        details = {"full_product_name": product_text}
        
        # Extract speed information
        speed_match = re.search(r"(\d+)Mbps", product_text)
        if speed_match:
            details["speed_mbps"] = speed_match.group(1)
        
        # Extract service type
        if "Fibre" in product_text:
            details["connection_type"] = "Fibre"
        elif "ADSL" in product_text:
            details["connection_type"] = "ADSL"
        
        # Extract capping information
        if "Uncapped" in product_text:
            details["data_capping"] = "Uncapped"
        elif "Capped" in product_text:
            details["data_capping"] = "Capped"
        
        return details
    
    def _parse_fsan_number(self, fsan_text: str) -> Dict[str, str]:
        """Parse FSAN number information"""
        # Remove any extra text and extract the actual FSAN
        fsan_match = re.search(r"([A-Z0-9]{12,16})", fsan_text)
        if fsan_match:
            return {
                "fsan_number": fsan_match.group(1),
                "raw_text": fsan_text
            }
        return {"raw_text": fsan_text}
    
    def _parse_ports_information(self, ports_text: str) -> Dict[str, Any]:
        """Parse ports information"""
        return {
            "raw_text": ports_text,
            "available_ports": re.findall(r"\d+", ports_text),
            "port_range": ports_text if "1-" in ports_text else None
        }
    
    def _parse_active_services(self, services_text: str) -> Dict[str, str]:
        """Parse active services information"""
        return {
            "raw_text": services_text,
            "service_ids": re.findall(r"[A-F0-9]{32}", services_text, re.IGNORECASE)
        }
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        if not text:
            return ""
        
        # Remove extra whitespace and newlines
        cleaned = re.sub(r'\s+', ' ', text.strip())
        
        # Remove common prefixes
        cleaned = re.sub(r'^(:|-)?\s*', '', cleaned)
        
        return cleaned
    
    def _assess_extraction_completeness(self, extraction_result: Dict) -> Dict[str, Any]:
        """Assess how complete the data extraction was"""
        sections = ["client_details", "service_details", "work_order_details", "isp_details", "ont_number_details"]
        
        completeness = {}
        for section in sections:
            section_data = extraction_result.get(section, {})
            if section_data and not section_data.get("error"):
                completeness[f"has_{section}"] = True
                completeness[f"{section}_field_count"] = len([k for k in section_data.keys() if not k.endswith("_error")])
            else:
                completeness[f"has_{section}"] = False
                completeness[f"{section}_field_count"] = 0
        
        # Calculate overall score
        total_sections = len(sections)
        successful_sections = sum(1 for section in sections if completeness.get(f"has_{section}", False))
        
        completeness["overall_completeness_score"] = successful_sections / total_sections
        completeness["total_sections"] = total_sections
        completeness["successful_sections"] = successful_sections
        
        return completeness
    
    def _emergency_text_extraction(self) -> Dict[str, str]:
        """Emergency fallback - just grab all text"""
        try:
            return {
                "emergency_extraction": True,
                "full_page_text": self.driver.find_element(By.TAG_NAME, "body").text,
                "page_url": self.driver.current_url,
                "page_title": self.driver.title
            }
        except:
            return {"emergency_extraction_failed": True}

# ==================== DATA EXTRACTOR ====================

class EvotelDataExtractor:
    """Extract data from Evotel portal with comprehensive capabilities"""
    
    def __init__(self, driver: webdriver.Chrome, logger):
        self.driver = driver
        self.logger = logger
    
    def search_circuit_number(self, circuit_number: str) -> SearchResult:
        """Search for circuit number in Evotel portal (maps to Evotel's serial number field)"""
        try:
            self.logger.info(f"Searching for circuit number: {circuit_number} (will be used as Evotel serial number)")
        
            # Find the search field (Evotel calls it "Serial Number Search" but we use it for circuit numbers)
            wait = WebDriverWait(self.driver, 15)
            search_field = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#SearchString"))
            )
        
            if not robust_click(self.driver, search_field, "search field"):
                raise Exception("Failed to click search field")
        
            # CRITICAL FIX: Use circuit_number directly without tab character
            search_field.clear()
            time.sleep(0.5)  # Conservative timing
            search_field.send_keys(circuit_number)  # Use circuit_number as the search value
        
            self.logger.info(f"Circuit number entered successfully: {circuit_number}")
        
            # Verify the value was entered
            field_value = search_field.get_attribute("value")
            if field_value != circuit_number:
                self.logger.warning(f"Field value mismatch: expected '{circuit_number}', got '{field_value}'")
        
            # Find and click search button
            search_button = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='btnSearch']"))
            )
        
            if not robust_click(self.driver, search_button, "search button"):
                raise Exception("Failed to click search button")
        
            self.logger.info("Search button clicked successfully")
        
            # IMPROVED: Wait for navigation with better condition
            try:
                WebDriverWait(self.driver, 20).until(
                    lambda driver: (
                        "/Search" in driver.current_url or
                        driver.find_elements(By.ID, "WebGrid")
                    )
                )
                self.logger.info("Search completed - navigated to results page")
            
                # Additional wait for dynamic content to load
                time.sleep(2)
            
                return self._check_search_results()
            
            except TimeoutException:
                self.logger.error("Search navigation timeout")
                current_url = self.driver.current_url
                self.logger.error(f"Current URL: {current_url}")
                return SearchResult.ERROR
            
        except Exception as e:
            self.logger.error(f"Circuit number search failed: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return SearchResult.ERROR
    
    def _check_search_results(self) -> SearchResult:
        """Check if search returned results"""
        try:
            # Look for results table
            wait = WebDriverWait(self.driver, 10)
            
            # Check for service links in the WebGrid
            service_links = self.driver.find_elements(By.XPATH, "//*[@id='WebGrid']/tbody/tr/td[3]/a")
            
            if service_links:
                self.logger.info(f"Found {len(service_links)} service results")
                return SearchResult.FOUND
            else:
                # Check for "no results" indicators
                page_source = self.driver.page_source.lower()
                if "no results" in page_source or "not found" in page_source:
                    self.logger.info("No search results found")
                    return SearchResult.NOT_FOUND
                else:
                    self.logger.warning("Unknown search result state")
                    return SearchResult.ERROR
                    
        except Exception as e:
            self.logger.error(f"Error checking search results: {str(e)}")
            return SearchResult.ERROR
    
    def extract_service_info(self) -> Dict[str, Any]:
        """Extract service information from search results - UPDATED TO SKIP GREYED OUT LINKS"""
        try:
            self.logger.info("Extracting active service information")
        
            wait = WebDriverWait(self.driver, 15)
        
            # Wait for service links to be present
            wait.until(
                EC.presence_of_element_located((By.XPATH, "//*[@id='WebGrid']/tbody/tr/td[3]/a"))
            )
        
            # Use the new enhanced active service extraction
            return extract_active_service_info(self.driver, self.logger)
        
        except Exception as e:
            self.logger.error(f"Error extracting active service info: {str(e)}")
            return {"error": str(e)}
    
    def extract_work_orders(self) -> List[Dict[str, Any]]:
        """Navigate to work orders and extract data from the FIRST (most recent) work order only - FIXED FILTERING"""
        try:
            self.logger.info("Extracting data from the first (most recent) work order")

            wait = WebDriverWait(self.driver, 15)

            # Click on Work Orders menu
            work_orders_menu = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#work-orders > span"))
            )

            if not robust_click(self.driver, work_orders_menu, "work orders menu"):
                raise Exception("Failed to click work orders menu")

            time.sleep(2)  # Wait for menu to expand

            # FIXED: Correct XPath for the actual HTML structure
            # Work orders are in <dl class="dl-horizontal dl-horizontal-service"><dd><a>
            all_links = self.driver.find_elements(By.XPATH, "//dl[@class='dl-horizontal dl-horizontal-service']/dd/a")
        
            # Fallback: Try alternative selector if primary doesn't work
            if not all_links:
                self.logger.info("Primary selector found no links, trying fallback selectors")
                fallback_selectors = [
                    "//dl[contains(@class, 'dl-horizontal')]/dd/a",
                    "//*[@id='ui-id-3']//dd/a", 
                    "//*[@id='ui-id-3']/dl/dd/a",
                    "//div[contains(@class, 'work-order')]//a"
                ]
            
                for selector in fallback_selectors:
                    all_links = self.driver.find_elements(By.XPATH, selector)
                    if all_links:
                        self.logger.info(f"Found {len(all_links)} links using fallback selector: {selector}")
                        break
        
            if not all_links:
                self.logger.error("No work order links found with any selector")
                return []
        
            self.logger.info(f"Found {len(all_links)} total links in work order section")
        
            # SIMPLIFIED: Just take the first non-email link (most recent work order)
            first_work_order_link = None
        
            # # Debug: Log all found links
            # self.logger.info("=== ALL WORK ORDER LINKS FOUND ===")
            # for i, link in enumerate(all_links):
            #     try:
            #         href = link.get_attribute("href") or ""
            #         link_text = link.text.strip()
            #         self.logger.info(f"Link {i+1}: '{link_text}' -> {href}")
            #     except Exception as e:
            #         self.logger.info(f"Link {i+1}: Error reading link - {str(e)}")
            # self.logger.info("=== END LINK DEBUG ===")
        
            for link in all_links:
                try:
                    href = link.get_attribute("href") or ""
                    link_text = link.text.strip()
                
                    # Skip email links (contain mailto:)
                    if "mailto:" in href.lower():
                        self.logger.info(f"Skipping email link: {link_text} ({href})")
                        continue
                
                    # Skip empty links
                    if not link_text:
                        self.logger.info("Skipping empty link")
                        continue
                
                    # Take the first valid link (most recent work order)
                    first_work_order_link = link
                    self.logger.info(f"Selected most recent work order: {link_text}")
                    break
                
                except Exception as e:
                    self.logger.debug(f"Error checking link: {str(e)}")
                    continue
        
            if not first_work_order_link:
                self.logger.error("No work order links found in dropdown")
                return []

            # Process the first work order (most recent)
            work_order_text = first_work_order_link.text
            work_order_url = first_work_order_link.get_attribute("href") or ""

            self.logger.info(f"Processing most recent work order: {work_order_text}")
            self.logger.info(f"Work order URL: {work_order_url}")

            # SAFETY CHECK: Verify this is not an email link before clicking
            if "mailto:" in work_order_url.lower():
                raise Exception(f"Safety check failed: Detected email link {work_order_url}")

            # Click on the first work order
            if not robust_click(self.driver, first_work_order_link, "first work order"):
                raise Exception("Failed to click first work order")

            # Wait for work order page with better error handling
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.url_contains("/WorkOrder/Item/")
                )   
                self.logger.info("Successfully navigated to work order page")
            except TimeoutException:
                current_url = self.driver.current_url
                self.logger.error(f"Failed to navigate to work order page. Current URL: {current_url}")
                raise Exception("Work order page navigation timeout")

            # COMPREHENSIVE EXTRACTION from the first work order
            comprehensive_details = self._extract_comprehensive_work_order_details()

            # Build work order info
            work_order_info = {
                "work_order_index": 1,
                "work_order_text": work_order_text,
                "work_order_url": work_order_url,
                "comprehensive_details": comprehensive_details,
                "extraction_timestamp": datetime.now().isoformat(),
                "is_most_recent": True,
                "total_links_in_dropdown": len(all_links),
                "processing_approach": "first_non_email_link"
            }

            self.logger.info("Successfully extracted comprehensive data from the first work order")
            return [work_order_info]

        except Exception as e:
            self.logger.error(f"Error extracting first work order: {str(e)}")
            self.logger.error(traceback.format_exc())
            return []
        
    def _extract_comprehensive_work_order_details(self) -> Dict[str, Any]:
        """Extract comprehensive work order details using the enhanced extractor"""
        try:
            comprehensive_extractor = ComprehensiveEvotelDataExtractor(self.driver, self.logger)
            return comprehensive_extractor.extract_complete_work_order_data()
        except Exception as e:
            self.logger.error(f"Comprehensive extraction failed: {str(e)}")
            return {"extraction_error": str(e)}

# ==================== MAIN AUTOMATION CLASS ====================

class EvotelValidationAutomation:
    """Main automation class for Evotel validation with comprehensive extraction"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.browser_service: Optional[BrowserService] = None
        self.screenshot_service: Optional[ScreenshotService] = None
        self.driver: Optional[webdriver.Chrome] = None
        self.input_handler: Optional[RobustInputHandler] = None
        self.data_extractor: Optional[EvotelDataExtractor] = None
        self.screenshots: List[ScreenshotData] = []
    
    def _setup_services(self, job_id: str):
        """Setup required services"""
        self.browser_service = BrowserService()
        self.driver = self.browser_service.create_driver(job_id)
        self.screenshot_service = ScreenshotService(job_id)
        self.input_handler = RobustInputHandler(self.logger)
        self.data_extractor = EvotelDataExtractor(self.driver, self.logger)
        self.screenshots = []
    
    def _cleanup_services(self):
        """Cleanup services"""
        if self.browser_service:
            try:
                self.browser_service.cleanup() 
            except Exception as e:
                self.logger.error(f"Error during cleanup: {str(e)}")

    def take_screenshot(self, name: str) -> Optional[ScreenshotData]:
        """Take screenshot using the ScreenshotService"""
        if not self.screenshot_service or not self.driver:
            self.logger.warning(f"Cannot take screenshot {name} - services not initialized")
            return None
            
        try:
            screenshot = self.screenshot_service.take_screenshot(self.driver, name)
            if screenshot:
                self.screenshots.append(screenshot)
            return screenshot
        except Exception as e:
            self.logger.error(f"Failed to take screenshot {name}: {str(e)}")
            return None

    def get_all_screenshots(self) -> List[ScreenshotData]:
        """Get all screenshots taken"""
        if self.screenshot_service:
            return self.screenshot_service.get_all_screenshots()
        return self.screenshots

    def validate_circuit_number(self, request: ValidationRequest) -> ValidationResult:
        """Main validation method with comprehensive extraction - Updated to use circuit_number"""
        start_time = time.time()
        
        try:
            self.logger.info(f"Starting validation for {request.job_id}, circuit number {request.circuit_number}")
            
            # Setup services
            self._setup_services(request.job_id)
            self.take_screenshot("initial_state")
            
            # Login
            login_handler = EvotelLogin()
            login_success = login_handler.login(self.driver)
            
            if not login_success:
                raise Exception("Login failed")
            
            self.take_screenshot("after_login")
            
            # Search for circuit number (which maps to Evotel's serial number field)
            search_result = self.data_extractor.search_circuit_number(request.circuit_number)
            self.take_screenshot("search_completed")
            
            if search_result == SearchResult.ERROR:
                return self._create_error_result(request, "Search operation failed")
            
            if search_result == SearchResult.NOT_FOUND:
                return self._create_not_found_result(request, time.time() - start_time)
            
            # Extract service information
            service_info = self.data_extractor.extract_service_info()
            self.take_screenshot("service_info_extracted")
            
            if service_info.get("error"):
                return self._create_error_result(request, f"Service extraction failed: {service_info['error']}")
            
            # Extract work orders with comprehensive data
            work_orders = self.data_extractor.extract_work_orders()
            self.take_screenshot("work_orders_extracted")
            
            # Calculate execution time
            execution_time = time.time() - start_time
            
            # Create comprehensive success result
            result = self._create_comprehensive_success_result(
                request, service_info, work_orders, execution_time
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Validation failed: {str(e)}")
            
            try:
                if self.driver and self.screenshot_service:
                    self.take_screenshot("error_state")
            except:
                pass
            
            return ValidationResult(
                job_id=request.job_id,
                circuit_number=request.circuit_number,
                status=ValidationStatus.ERROR,
                message=str(e),
                found=False,
                search_result=SearchResult.ERROR,
                screenshots=self.get_all_screenshots(),
                evidence_dir=str(self.screenshot_service.evidence_dir) if self.screenshot_service else None
            )
            
        finally:
            try:
                self._cleanup_services()
            except Exception as cleanup_error:
                self.logger.error(f"Cleanup failed: {str(cleanup_error)}")

    def _create_comprehensive_success_result(self, request: ValidationRequest, service_info: Dict, 
                                           work_orders: List[Dict], execution_time: float) -> ValidationResult:
        """Create comprehensive success result with all extracted data"""
        
        # Extract the comprehensive data from the first work order
        primary_work_order = work_orders[0] if work_orders else {}
        comprehensive_data = primary_work_order.get("comprehensive_details", {})
        
        # Create enhanced service data
        service_data = ServiceData(
            service_id=service_info.get("service_uuid", ""),
            service_type=service_info.get("service_name", ""),
            customer_name=comprehensive_data.get("client_details", {}).get("client_name", ""),
            status=self._determine_service_status(comprehensive_data),
            work_orders=work_orders,
            service_details=service_info,
            extraction_timestamp=datetime.now().isoformat()
        )
        
        # Create comprehensive details structure (like Octotel)
        details = {
            "found": True,
            "circuit_number": request.circuit_number,  # Updated from serial_number
            
            # STRUCTURED DATA (for consumption)
            "service_summary": {
                "service_provider": comprehensive_data.get("service_details", {}).get("service_provider", ""),
                "product": comprehensive_data.get("service_details", {}).get("product", ""),
                "status": comprehensive_data.get("service_details", {}).get("service_status", ""),
                "customer": comprehensive_data.get("client_details", {}).get("client_name", ""),
                "email": comprehensive_data.get("client_details", {}).get("email", ""),
                "mobile": comprehensive_data.get("client_details", {}).get("mobile", ""),
                "address": comprehensive_data.get("client_details", {}).get("address", ""),
                "area": comprehensive_data.get("client_details", {}).get("area", "")
            },
            
            "technical_details": {
                "ont_details": comprehensive_data.get("ont_number_details", {}),
                "isp_details": comprehensive_data.get("isp_details", {}),
                "all_references": comprehensive_data.get("all_references", {}),
                "technical_identifiers": comprehensive_data.get("technical_identifiers", {}),
                "fsan_number": comprehensive_data.get("ont_number_details", {}).get("fsan_number", ""),
                "verification_status": comprehensive_data.get("ont_number_details", {}).get("verification", "")
            },
            
            "work_order_summary": {
                "total_work_orders": len(work_orders),
                "primary_work_order": comprehensive_data.get("work_order_details", {}),
                "primary_work_order_reference": comprehensive_data.get("work_order_details", {}).get("reference", ""),
                "primary_work_order_status": comprehensive_data.get("work_order_details", {}).get("status", ""),
                "all_work_orders": work_orders
            },
            
            # RAW EXTRACTED DATA (for auditing/debugging)
            "raw_extraction": {
                "comprehensive_extraction": comprehensive_data,
                "service_info": service_info,
                "extraction_metadata": comprehensive_data.get("extraction_metadata", {})
            },
            
            # COMPLETENESS ASSESSMENT
            "data_completeness": comprehensive_data.get("data_completeness", {}),
            
            # PROCESSING METADATA
            "extraction_metadata": {
                "extraction_timestamp": datetime.now().isoformat(),
                "processing_approach": "evotel_comprehensive_v1.0",
                "completeness_score": comprehensive_data.get("data_completeness", {}).get("overall_completeness_score", 0.0),
                "total_sections_extracted": comprehensive_data.get("data_completeness", {}).get("successful_sections", 0),
                "total_sections_available": comprehensive_data.get("data_completeness", {}).get("total_sections", 0)
            }
        }
        
        # Calculate overall completeness score
        completeness_score = details["extraction_metadata"]["completeness_score"]
        
        return ValidationResult(
            job_id=request.job_id,
            circuit_number=request.circuit_number,
            status=ValidationStatus.SUCCESS,
            message=f"Successfully validated circuit number {request.circuit_number}. "
                   f"Found comprehensive service data with {len(work_orders)} work orders. "
                   f"Data completeness: {completeness_score:.1%}",
            found=True,
            service_data=service_data,
            search_result=SearchResult.FOUND,
            execution_time=execution_time,
            screenshots=self.get_all_screenshots(),
            evidence_dir=str(self.screenshot_service.evidence_dir) if self.screenshot_service else None,
            details=details
        )

    def _determine_service_status(self, comprehensive_data: Dict) -> ServiceStatus:
        """Determine service status from comprehensive data"""
        service_status = comprehensive_data.get("service_details", {}).get("service_status", "").lower()
        work_order_status = comprehensive_data.get("work_order_details", {}).get("status", "").lower()
        
        if "active" in service_status:
            return ServiceStatus.ACTIVE
        elif "cancelled" in service_status or "cancelled" in work_order_status:
            return ServiceStatus.CANCELLED
        elif "pending" in service_status or "pending" in work_order_status or "provisioned" in work_order_status:
            return ServiceStatus.PENDING
        else:
            return ServiceStatus.UNKNOWN

    def _create_error_result(self, request: ValidationRequest, message: str) -> ValidationResult:
        """Create error result"""
        return ValidationResult(
            job_id=request.job_id,
            circuit_number=request.circuit_number,
            status=ValidationStatus.ERROR,
            message=message,
            found=False,
            search_result=SearchResult.ERROR,
            screenshots=self.get_all_screenshots(),
            evidence_dir=str(self.screenshot_service.evidence_dir) if self.screenshot_service else None
        )

    def _create_not_found_result(self, request: ValidationRequest, execution_time: float) -> ValidationResult:
        """Create not found result"""
        return ValidationResult(
            job_id=request.job_id,
            circuit_number=request.circuit_number,
            status=ValidationStatus.SUCCESS,
            message=f"Circuit number {request.circuit_number} not found in Evotel portal.",
            found=False,
            search_result=SearchResult.NOT_FOUND,
            execution_time=execution_time,
            screenshots=self.get_all_screenshots(),
            evidence_dir=str(self.screenshot_service.evidence_dir) if self.screenshot_service else None,
            details={
                "found": False,
                "search_term": request.circuit_number
            }
        )

# ==================== MAIN EXECUTION ====================

def execute(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Main execution function for external API calls - Updated to use circuit_number"""
    try:
        # Validate configuration
        if not all([Config.EVOTEL_URL, Config.EVOTEL_EMAIL, Config.EVOTEL_PASSWORD]):
            logger.error("Missing required Evotel configuration")
            return {
                "status": "error",
                "message": "Missing required Evotel configuration",
                "details": {"error": "configuration_missing"},
                "screenshot_data": []
            }
        
        # Create validation request - Updated to use circuit_number
        request = ValidationRequest(
            job_id=parameters.get("job_id"),
            circuit_number=parameters.get("circuit_number")  # Changed from serial_number
        )
        
        logger.info(f"Starting comprehensive validation for circuit number: {request.circuit_number}")
        
        # Execute validation
        automation = EvotelValidationAutomation()
        result = automation.validate_circuit_number(request)
        
        # Convert result to dictionary
        result_dict = {
            "status": result.status.value,
            "message": result.message,
            "details": result.details or {"found": result.found},
            "evidence_dir": result.evidence_dir,
            "screenshot_data": [
                {
                    "name": screenshot.name,
                    "timestamp": screenshot.timestamp.isoformat(),
                    "base64_data": screenshot.data,
                    "path": screenshot.path
                }
                for screenshot in result.screenshots
            ],
            "execution_time": result.execution_time
        }
        
        return result_dict
        
    except Exception as e:
        logger.error(f"Execute function failed: {str(e)}")
        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Execution error: {str(e)}",
            "details": {"error": str(e)},
            "screenshot_data": []
        }

# ==================== EXAMPLE USAGE ====================

if __name__ == "__main__":
    # Example usage with comprehensive extraction - Updated to use circuit_number
    test_parameters = {
        "job_id": "test_comprehensive_001",
        "circuit_number": "48575443D9B290B1"  # Changed from serial_number
    }
    
    result = execute(test_parameters)
    print(json.dumps(result, indent=2))
    
    # Print completeness metrics
    if result.get("status") == "success" and result.get("details"):
        completeness = result["details"].get("data_completeness", {})
        print(f"\nExtraction Completeness Report:")
        print(f"Overall Score: {completeness.get('overall_completeness_score', 0):.1%}")
        print(f"Sections Extracted: {completeness.get('successful_sections', 0)}/{completeness.get('total_sections', 0)}")
        
        # Print sample extracted data
        service_summary = result["details"].get("service_summary", {})
        print(f"\nSample Extracted Data:")
        print(f"Customer: {service_summary.get('customer', 'N/A')}")
        print(f"Product: {service_summary.get('product', 'N/A')}")
        print(f"Status: {service_summary.get('status', 'N/A')}")
                       