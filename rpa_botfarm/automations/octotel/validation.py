"""
Octotel Validation Module - Cleaned and Optimized Version
========================================================
Streamlined automation for Octotel service validation
"""

import os
import time
import logging
import traceback
import json
import pyotp
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
    """Input model for validation requests"""
    job_id: str = Field(..., description="Unique job identifier")
    circuit_number: str = Field(..., description="Circuit number to validate")

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
    bitstream_reference: str
    status: ServiceStatus
    customer_name: Optional[str] = None
    service_type: Optional[str] = None
    change_request_available: bool = False
    pending_requests_detected: bool = False
    extraction_timestamp: Optional[str] = None

class ValidationResult(BaseModel):
    """Complete validation result container"""
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
            return True
        except Exception:
            continue
    
    return False

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
            except Exception:
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
                logger.info("Browser closed")
            except Exception as e:
                logger.error(f"Error during cleanup: {str(e)}")

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
            return screenshot
            
        except Exception as e:
            logger.error(f"Failed to take screenshot: {str(e)}")
            return None
    
    def get_all_screenshots(self) -> List[ScreenshotData]:
        """Get all screenshots taken"""
        return self.screenshots

# ==================== LOGIN HANDLER ====================

class OctotelTOTPLogin:
    """TOTP-based authentication handler for Octotel portal"""
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        retry=retry_if_exception_type((TimeoutException, WebDriverException, ElementNotInteractableException))
    )
    def login(self, driver: webdriver.Chrome) -> bool:
        """Execute complete login flow with TOTP authentication"""
        try:
            logger.info("Starting Octotel login")
            driver.get(Config.OCTOTEL_URL)
            
            # Wait for page load
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            # Find and click login button
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
                    break
                except TimeoutException:
                    continue
            
            if not login_btn:
                raise Exception("Could not find login button")
            
            # Click login button
            if not robust_click(driver, login_btn, "login button"):
                raise Exception("Failed to click login button")
            
            # Wait for login form
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "signInFormUsername"))
                )
            except TimeoutException:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//input[@type='email' or @type='text']"))
                )
            
            # Enter credentials
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
                username_field = driver.find_element(By.ID, "signInFormUsername")
                password_field = driver.find_element(By.ID, "signInFormPassword")
                
                username_field.clear()
                username_field.send_keys(Config.OCTOTEL_USERNAME)
                password_field.clear()
                password_field.send_keys(Config.OCTOTEL_PASSWORD)
            
            # Submit login form
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
                        break
                except:
                    continue
            
            if not submit_btn:
                raise Exception("Could not find submit button")
            
            # Submit login
            if not robust_click(driver, submit_btn, "submit button"):
                raise Exception("Failed to click submit button")
            
            # Handle TOTP authentication
            if not self.handle_totp(driver):
                raise Exception("TOTP authentication failed")
            
            # Wait for successful login indicators
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
                        login_success = True
                        break
                    except TimeoutException:
                        continue
                
                if not login_success:
                    current_url = driver.current_url
                    page_source = driver.page_source.lower()
                    if "sign in" in page_source or "login" in page_source:
                        return False
                    elif "/start" in current_url or "dashboard" in page_source:
                        return True
                    else:
                        return True
                else:
                    logger.info("Login successful")
                    return True
                    
            except Exception as e:
                logger.error(f"Login verification failed: {str(e)}")
                return False
                
        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            raise
    
    def handle_totp(self, driver: webdriver.Chrome) -> bool:
        """Handle TOTP two-factor authentication"""
        try:
            # Generate TOTP code
            totp = pyotp.TOTP(Config.OCTOTEL_TOTP_SECRET)
            totp_code = totp.now()
            
            # Wait for TOTP input field
            wait = WebDriverWait(driver, 12)
            totp_element = wait.until(
                EC.presence_of_element_located((By.ID, "totpCodeInput"))
            )
            
            # Enter TOTP code
            totp_element.clear()
            totp_element.send_keys(totp_code)
            
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
                    
                    break
                except TimeoutException:
                    continue
            
            if not submit_btn:
                raise Exception("Could not find TOTP submit button")
            
            if not robust_click(driver, submit_btn, "TOTP submit button"):
                raise Exception("Failed to click TOTP submit button")
            
            time.sleep(3)
            return True
            
        except Exception as e:
            logger.error(f"TOTP authentication failed: {e}")
            return False

# ==================== STREAMLINED DATA PROCESSING ====================

class StreamlinedDataProcessor:
    """Streamlined processor that creates clean final data + raw audit trail"""
    
    def __init__(self, logger):
        self.logger = logger
    
    def create_streamlined_service_data(self, raw_table_data: Dict, raw_sidebar_data: Dict) -> Dict:
        """
        Create clean structured service data from raw extractions
        Enhanced to include change requests
        """
        try:
            # Extract core identifiers
            service_id = self._get_best_value(raw_table_data, ["service_id", "column_0"])
            line_reference = self._get_best_value(raw_table_data, ["line_reference", "column_1"])
        
            # Build structured service data
            structured_service = {
                "service_identifiers": {
                    "primary_id": service_id,
                    "line_reference": line_reference,
                    "service_uuid": self._extract_uuids(raw_sidebar_data, "service_uuid"),
                    "line_uuid": self._extract_uuids(raw_sidebar_data, "line_uuid")
                },
            
                "customer_information": self._extract_customer_info(raw_table_data, raw_sidebar_data),
                "service_details": self._extract_service_details(raw_table_data, raw_sidebar_data),
                "technical_details": self._extract_technical_details(raw_table_data, raw_sidebar_data),
                "location_information": self._extract_location_info(raw_table_data, raw_sidebar_data),
                "status_information": self._extract_status_info(raw_table_data, raw_sidebar_data),
            
                # Add change requests information
                "change_requests": self.extract_change_requests_info(raw_sidebar_data),
            
                "data_completeness": {
                    "has_table_data": bool(raw_table_data.get("full_row_text")),
                    "has_sidebar_data": bool(raw_sidebar_data.get("raw_sidebar_text")),
                    "has_customer_contact": bool(raw_sidebar_data.get("customer_email")),
                    "has_technical_uuids": bool(raw_sidebar_data.get("service_uuid")),
                    "has_change_requests": bool(raw_sidebar_data.get("change_requests_data", {}).get("table_rows"))
                }
            }
        
            # Calculate completeness score
            completeness_fields = structured_service["data_completeness"]
            structured_service["data_completeness"]["overall_score"] = sum(completeness_fields.values()) / len(completeness_fields)
        
            return structured_service
        
        except Exception as e:
            self.logger.error(f"Error creating streamlined service data: {str(e)}")
            return {"processing_error": str(e)}
    
    def _extract_customer_info(self, table_data: Dict, sidebar_data: Dict) -> Dict:
        """Extract customer information from raw data"""
        customer_info = {}
        
        # Name - prefer actual name from table over ID codes
        name_candidates = ["column_6", "customer_name"]
        customer_name = self._get_best_value(table_data, name_candidates)
        if customer_name and not customer_name.startswith("S2"):
            customer_info["name"] = customer_name
        
        # Contact info from sidebar
        if sidebar_data.get("customer_email"):
            customer_info["email"] = sidebar_data["customer_email"]
        if sidebar_data.get("customer_phone"):
            customer_info["phone"] = sidebar_data["customer_phone"]
            
        return customer_info
    
    def _extract_service_details(self, table_data: Dict, sidebar_data: Dict) -> Dict:
        """Extract service details from raw data"""
        service_details = {}
        
        # Map table columns to service fields
        field_mapping = {
            "type": ["column_2", "service_type"],
            "speed_profile": ["column_8", "speed_profile"],
            "start_date": ["column_4", "start_date"],
            "isp_order_number": ["column_5", "isp_order_number"]
        }
        
        for field_name, candidates in field_mapping.items():
            value = self._get_best_value(table_data, candidates)
            if value:
                service_details[field_name] = value
        
        return service_details
    
    def _extract_technical_details(self, table_data: Dict, sidebar_data: Dict) -> Dict:
        """Extract technical details from raw data"""
        technical_details = {}
        
        # Network infrastructure from table
        network_node = self._get_best_value(table_data, ["column_9", "network_node"])
        ont_device = self._get_best_value(table_data, ["column_10", "ont_device"])
        
        if network_node:
            technical_details["network_node"] = network_node
        if ont_device:
            technical_details["ont_device"] = ont_device
            
        # UUIDs from sidebar
        service_uuids = self._extract_uuids(sidebar_data, "service_uuid")
        line_uuids = self._extract_uuids(sidebar_data, "line_uuid")
        
        if service_uuids:
            technical_details["service_uuid"] = service_uuids
        if line_uuids:
            technical_details["line_uuid"] = line_uuids
            
        return technical_details
    
    def _extract_location_info(self, table_data: Dict, sidebar_data: Dict) -> Dict:
        """Extract location information from raw data"""
        location_info = {}
        
        # Address from table
        address = self._get_best_value(table_data, ["column_7", "service_address"])
        if address:
            location_info["address"] = address
            
        return location_info
    
    def _extract_status_info(self, table_data: Dict, sidebar_data: Dict) -> Dict:
        """Extract status information from raw data"""
        status_info = {}
        
        # Status from table
        table_status = self._get_best_value(table_data, ["column_11", "table_status", "status"])
        if table_status:
            status_info["current_status"] = table_status
            
        # Additional status indicators from sidebar text analysis
        sidebar_text = sidebar_data.get("raw_sidebar_text", "").lower()
        status_info["has_pending_cancellation"] = "pending cancellation" in sidebar_text
        status_info["has_change_requests"] = "change request" in sidebar_text
        
        return status_info
    
    def _extract_uuids(self, sidebar_data: Dict, uuid_type: str) -> List[str]:
        """Extract UUIDs from sidebar data"""
        uuids = sidebar_data.get(uuid_type, [])
        if isinstance(uuids, str):
            return [uuids]
        elif isinstance(uuids, list):
            return list(set(uuids))
        return []
    
    def _get_best_value(self, data: Dict, candidates: List[str]) -> str:
        """Get first non-empty value from candidate fields"""
        for candidate in candidates:
            value = data.get(candidate, "")
            if value and str(value).strip():
                return str(value).strip()
        return ""
    
    def organize_raw_extraction_data(self, all_services: List[Dict], matching_services: List[Dict], 
                                   service_details: Dict) -> Dict:
        """Organize raw data for audit trail"""
        
        # Clean table data
        table_data = []
        for service in matching_services:
            raw_entry = {
                "row_text": service.get("full_row_text", ""),
                "extraction_timestamp": service.get("extraction_timestamp"),
                "table_row_index": service.get("table_row_index")
            }
            table_data.append(raw_entry)
        
        # Clean sidebar data
        sidebar_data = {}
        if service_details and not service_details.get("error"):
            sidebar_data = {
                "raw_text": service_details.get("raw_sidebar_text", ""),
                "extraction_timestamp": service_details.get("extraction_timestamp"),
                "text_length": service_details.get("sidebar_text_length", 0)
            }
        
        return {
            "table_data": table_data,
            "sidebar_data": sidebar_data,
            "total_services_scanned": len(all_services),
            "matching_services_found": len(matching_services)
        }
    
    def extract_change_requests_info(self, service_details: Dict) -> Dict:
        """Extract change request information for streamlined output"""
        change_requests_data = service_details.get("change_requests_data", {})
    
        if not change_requests_data or change_requests_data.get("extraction_error"):
            return {
                "change_requests_found": False,
                "total_change_requests": 0,
                "first_change_request": {},
                "extraction_successful": False
            }
    
        table_rows = change_requests_data.get("table_rows", [])
    
        change_request_info = {
            "change_requests_found": len(table_rows) > 0,
            "total_change_requests": len(table_rows),
            "table_headers": change_requests_data.get("table_headers", []),
            "extraction_successful": True,
            "extraction_timestamp": change_requests_data.get("extraction_timestamp"),
            "raw_table_text": change_requests_data.get("raw_table_text", "")
        }
    
        # Add first change request if available
        if table_rows:
            first_row = table_rows[0]
            change_request_info["first_change_request"] = {
                "id": first_row.get("change_request_id", ""),
                "type": first_row.get("change_request_type", ""),
                "status": first_row.get("change_request_status", ""),
                "due_date": first_row.get("change_request_due_date", ""),
                "requested_by": first_row.get("change_request_requested_by", ""),
                "full_row_text": first_row.get("full_row_text", "")
            }
        else:
            change_request_info["first_change_request"] = {}
    
        # Add all change requests in clean format
        change_request_info["all_change_requests"] = []
        for row in table_rows:
            clean_row = {
                "id": row.get("change_request_id", ""),
                "type": row.get("change_request_type", ""),
                "status": row.get("change_request_status", ""),
                "due_date": row.get("change_request_due_date", ""),
                "requested_by": row.get("change_request_requested_by", ""),
                "full_row_text": row.get("full_row_text", ""),
                "row_index": row.get("row_index", 0)
            }
            change_request_info["all_change_requests"].append(clean_row)
    
        return change_request_info

# ==================== ROBUST DATA EXTRACTION ====================

class RobustDataExtractor:
    """Extract data faithfully with minimal interpretation"""
    
    def __init__(self, driver: webdriver.Chrome, logger):
        self.driver = driver
        self.logger = logger
    
    def extract_all_services(self) -> List[Dict]:
        """Extract all services from the current table view"""
        try:
            # Find the table
            table_selectors = [
                "div.app-body table",
                "table",
                ".table",
                "//table"
            ]
            
            table = None
            for selector in table_selectors:
                try:
                    if selector.startswith("//"):
                        table = self.driver.find_element(By.XPATH, selector)
                    else:
                        table = self.driver.find_element(By.CSS_SELECTOR, selector)
                    
                    if table.is_displayed():
                        break
                except:
                    continue
            
            if not table:
                return []
            
            # Extract headers
            headers = []
            try:
                header_rows = table.find_elements(By.TAG_NAME, "th")
                headers = [th.text.strip() for th in header_rows if th.text.strip()]
            except:
                pass
            
            # Extract all rows
            services = []
            try:
                rows = table.find_elements(By.TAG_NAME, "tr")
                
                for i, row in enumerate(rows):
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if not cells:
                            continue
                        
                        cell_texts = [cell.text.strip() for cell in cells]
                        
                        if not any(cell_texts):
                            continue
                        
                        # Build service data
                        service_data = {
                            "table_row_index": i,
                            "full_row_text": " | ".join(cell_texts),
                            "headers_found": headers,
                            "extraction_timestamp": datetime.now().isoformat(),
                            "extraction_source": "table_extraction"
                        }
                        
                        # Map cells to column positions
                        for j, cell_text in enumerate(cell_texts):
                            service_data[f"column_{j}"] = cell_text
                        
                        # Map to semantic fields if possible
                        if len(cell_texts) > 0:
                            service_data["service_id"] = cell_texts[0]
                        if len(cell_texts) > 1:
                            service_data["line_reference"] = cell_texts[1]
                        if len(cell_texts) > 2:
                            service_data["service_type"] = cell_texts[2]
                        if len(cell_texts) > 3:
                            service_data["start_date"] = cell_texts[3]
                        if len(cell_texts) > 4:
                            service_data["isp_order_number"] = cell_texts[4]
                        if len(cell_texts) > 5:
                            service_data["customer_name"] = cell_texts[5]
                        
                        services.append(service_data)
                        
                    except Exception:
                        continue
                
                return services
                
            except Exception:
                return []
                
        except Exception:
            return []
    
    def extract_service_details(self, service_id: str) -> Dict:
        """Extract detailed service information including change requests"""
        try:
            # Wait for detail view to load
            time.sleep(2)
        
            # Try to find sidebar or detail panel
            detail_selectors = [
                ".sidebar",
                ".detail-panel", 
                ".service-details",
                "//div[contains(@class, 'sidebar')]",
                "//div[contains(@class, 'detail')]"
            ]
        
            detail_element = None
            for selector in detail_selectors:
                try:
                    if selector.startswith("//"):
                        detail_element = self.driver.find_element(By.XPATH, selector)
                    else:
                        detail_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                
                    if detail_element.is_displayed():
                        break
                except:
                    continue
        
            if not detail_element:
                return {"error": "no_detail_element_found"}
        
            # Extract text content
            detail_text = detail_element.text
        
            service_details = {
                "extraction_timestamp": datetime.now().isoformat(),
                "extraction_source": "sidebar_extraction",
                "raw_sidebar_text": detail_text,
                "sidebar_text_length": len(detail_text),
                "service_id": service_id
            }
        
            # Extract structured information using patterns
            patterns = {
                "customer_email": r"[\w\.-]+@[\w\.-]+\.\w+",
                "customer_phone": r"[\+]?[1-9]?[0-9]{7,14}",
                "service_uuid": r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                "line_uuid": r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
            }
        
            for field_name, pattern in patterns.items():
                matches = re.findall(pattern, detail_text, re.IGNORECASE)
                if matches:
                    service_details[field_name] = matches[0] if len(matches) == 1 else matches
        
            # Extract simple key-value pairs
            lines = detail_text.split('\n')
            for line in lines:
                if ':' in line:
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        key = parts[0].strip().lower().replace(' ', '_')
                        value = parts[1].strip()
                        if value:
                            service_details[f"extracted_{key}"] = value
        
            # Extract change requests data
            change_requests_data = self.extract_change_requests_data(self.driver)
            service_details["change_requests_data"] = change_requests_data
        
            return service_details
        
        except Exception as e:
            return {"error": str(e)}
    
    def extract_change_requests_data(self, driver: webdriver.Chrome) -> Dict[str, Any]:
        """Extract change requests from sidebar table"""
        try:
            logger.info("Extracting change requests data")

            # Initialize result structure
            change_request_data = {
                "extraction_timestamp": datetime.now().isoformat(),
                "extraction_source": "change_requests_table",
                "raw_table_text": "",
                "table_headers": [],
                "table_rows": [],
                "total_rows": 0
            }
    
            # Wait for page to settle
            time.sleep(2)
    
            # Find sidebar element
            sidebar_element = None
            sidebar_selectors = [
                ".sidebar",
                "//div[contains(@class, 'sidebar')]",
                ".scrollable-content",
                "//div[contains(@class, 'scrollable-content')]",
                "div[ui-yield-to='sidebarRight']",
                "//div[@ui-yield-to='sidebarRight']",
                ".sidebar-right",
                "//div[contains(@class, 'sidebar-right')]",
                "//div[contains(@class, 'scrollable')]",
                "//div[contains(text(), 'Change Requests')]/ancestor::div[contains(@class, 'scrollable')]",
                "//div[.//table[.//th[contains(text(), 'ID')] and .//td[contains(text(), 'VOD')]]]"
            ]
    
            for selector in sidebar_selectors:
                try:
                    if selector.startswith("//"):
                        sidebar_element = driver.find_element(By.XPATH, selector)
                    else:
                        sidebar_element = driver.find_element(By.CSS_SELECTOR, selector)
            
                    if sidebar_element.is_displayed():
                        break
                except Exception:
                    continue
    
            if not sidebar_element:
                return self._fallback_change_request_extraction(driver, change_request_data)
    
            # Find tables within sidebar
            sidebar_tables = []
            table_selectors = [
                ".//table",
                ".//table[contains(@class, 'table')]",
                ".//table[contains(@class, 'properties')]",
                ".//table[.//th[contains(text(), 'ID')]]",
            ]
        
            for selector in table_selectors:
                try:
                    tables = sidebar_element.find_elements(By.XPATH, selector)
                    sidebar_tables.extend(tables)
                except Exception:
                    continue
        
            # Remove duplicates
            sidebar_tables = list(set(sidebar_tables))
    
            if not sidebar_tables:
                return self._fallback_change_request_extraction(driver, change_request_data)
    
            # Select best table
            target_table = None
            best_score = 0
        
            for i, table in enumerate(sidebar_tables):
                try:
                    table_text = table.text.strip()
                    table_classes = table.get_attribute('class') or ""
            
                    text_sample = table_text[:200].lower()
                    score = 0
                
                    # Score based on content
                    rows = table.find_elements(By.XPATH, ".//tr")
                    key_value_rows = 0
                    has_id_row = False
                    has_type_row = False
                    has_status_row = False
                
                    for row in rows[:10]:
                        th_elements = row.find_elements(By.TAG_NAME, "th")
                        td_elements = row.find_elements(By.TAG_NAME, "td")
                    
                        if len(th_elements) == 1 and len(td_elements) == 1:
                            key_value_rows += 1
                        
                            th_text = th_elements[0].text.strip().lower()
                            td_text = td_elements[0].text.strip()
                        
                            if th_text == 'id' and ('vod' in td_text.lower() or 'cr' in td_text.lower()):
                                has_id_row = True
                                score += 20
                            
                            elif th_text == 'type' and 'cancellation' in td_text.lower():
                                has_type_row = True
                                score += 15
                            
                            elif th_text == 'status' and td_text.lower() in ['pending', 'completed', 'cancelled']:
                                has_status_row = True
                                score += 10
                
                    # Additional scoring
                    if key_value_rows >= 3:
                        score += 10
                    
                    change_request_keywords = ['change request', 'cancellation', 'pending', 'due date', 'vod', 'cr0']
                    keyword_matches = sum(1 for keyword in change_request_keywords if keyword in text_sample)
                    score += keyword_matches * 2
                
                    if 'properties' in table_classes:
                        score += 5
                
                    if has_id_row and has_type_row:
                        score += 25
            
                    if score > best_score:
                        best_score = score
                        target_table = table
                        change_request_data["target_table_index"] = i
                        change_request_data["target_table_classes"] = table_classes
                    
                except Exception:
                    continue
        
            if not target_table or best_score < 15:
                return self._fallback_change_request_extraction(driver, change_request_data)
        
            logger.info(f"Selected change requests table with score: {best_score}")
    
            # Extract table data
            raw_table_text = target_table.text.strip()
            change_request_data["raw_table_text"] = raw_table_text
    
            # Parse key-value pairs
            rows = target_table.find_elements(By.XPATH, ".//tbody/tr")
            if not rows:
                rows = target_table.find_elements(By.XPATH, ".//tr")
    
            key_value_pairs = []
    
            for i, row in enumerate(rows):
                try:
                    th_elements = row.find_elements(By.TAG_NAME, "th")
                    td_elements = row.find_elements(By.TAG_NAME, "td")
            
                    if len(th_elements) == 1 and len(td_elements) == 1:
                        key = th_elements[0].text.strip()
                        value = td_elements[0].text.strip()
                
                        if key and value:
                            key_value_pairs.append({
                                "key": key, 
                                "value": value, 
                                "row_index": i
                            })
                
                except Exception:
                    continue
    
            # Build change request
            if key_value_pairs:
                change_request = self._build_change_request_from_pairs_fixed(key_value_pairs)
                if change_request:
                    change_request_data["table_rows"] = [change_request]
                    change_request_data["total_rows"] = 1
                    change_request_data["table_headers"] = ["ID", "Type", "Status", "Due Date", "Requested"]
                    
                    logger.info(f"Successfully extracted change request: {change_request.get('change_request_id', 'N/A')}")
    
            return change_request_data
    
        except Exception as e:
            logger.error(f"Error in change requests extraction: {str(e)}")
            return {
                "extraction_timestamp": datetime.now().isoformat(),
                "extraction_source": "change_requests_table",
                "extraction_error": str(e),
                "raw_table_text": "",
                "table_headers": [],
                "table_rows": [],
                "total_rows": 0
            }
    
    def _build_change_request_from_pairs_fixed(self, key_value_pairs: List[Dict]) -> Dict:
        """Build change request from key-value pairs with improved field mapping"""
        try:
            change_request = {
                "row_index": 0,
                "extraction_timestamp": datetime.now().isoformat(),
                "extraction_method": "key_value_pairs_fixed"
            }
    
            # Field mappings with better fuzzy matching
            field_mappings = {
                "change_request_id": ["id", "change request", "change request id", "cr", "cr id", "request id"],
                "change_request_type": ["type", "request type", "change type", "cr type"],
                "change_request_status": ["status", "request status", "cr status", "state"],
                "change_request_due_date": ["due date", "date", "due", "target date", "completion date", "scheduled date"],
                "change_request_requested_by": ["requested", "requested by", "requester", "created by", "user", "by"]
            }
    
            # Process each key-value pair with fuzzy matching
            mapped_fields = {}
            unmapped_fields = {}
    
            for pair in key_value_pairs:
                key_original = pair["key"].strip()
                key_normalized = key_original.lower().strip()
                value = pair["value"].strip()
        
                # Try to find best matching field
                best_match = None
                best_match_field = None
            
                for field_name, possible_keys in field_mappings.items():
                    for possible_key in possible_keys:
                        # Exact match
                        if key_normalized == possible_key:
                            best_match = possible_key
                            best_match_field = field_name
                            break
                        # Partial match
                        elif possible_key in key_normalized or key_normalized in possible_key:
                            if not best_match or len(possible_key) > len(best_match):
                                best_match = possible_key
                                best_match_field = field_name
                
                    if best_match and key_normalized == best_match:
                        break
        
                if best_match_field:
                    mapped_fields[best_match_field] = value
                else:
                    unmapped_fields[key_original] = value
    
            # Add mapped fields to change request
            change_request.update(mapped_fields)
    
            # Add column data for compatibility
            change_request["column_0"] = mapped_fields.get("change_request_id", "")
            change_request["column_1"] = mapped_fields.get("change_request_type", "")
            change_request["column_2"] = mapped_fields.get("change_request_status", "")
            change_request["column_3"] = mapped_fields.get("change_request_due_date", "")
            change_request["column_4"] = mapped_fields.get("change_request_requested_by", "")
    
            # Build full row text
            row_parts = [
                mapped_fields.get("change_request_id", ""),
                mapped_fields.get("change_request_type", ""),
                mapped_fields.get("change_request_status", ""),
                mapped_fields.get("change_request_due_date", ""),
                mapped_fields.get("change_request_requested_by", "")
            ]   
            change_request["full_row_text"] = " | ".join([part for part in row_parts if part])
    
            # Add unmapped fields for debugging
            if unmapped_fields:
                change_request["unmapped_fields"] = unmapped_fields
    
            return change_request
    
        except Exception as e:
            logger.error(f"Error building change request: {str(e)}")
            return {}

    def _fallback_change_request_extraction(self, driver: webdriver.Chrome, change_request_data: Dict) -> Dict:
        """Fallback method to search entire page for change request data"""
        try:
            # Look for any table that contains change request data
            fallback_selectors = [
                "//table[.//th[contains(text(), 'ID')] and .//td[contains(text(), 'VOD')]]",
                "//table[.//th[contains(text(), 'Type')] and .//td[contains(text(), 'Cancellation')]]",
                "//table[contains(@class, 'properties')]",
                "//div[contains(text(), 'Change Request')]//following::table[1]",
                "//h5[contains(text(), 'Change Request')]//following::table[1]"
            ]
        
            for selector in fallback_selectors:
                try:
                    tables = driver.find_elements(By.XPATH, selector)
                    if tables:
                        table = tables[0]
                    
                        # Try to extract key-value pairs
                        rows = table.find_elements(By.XPATH, ".//tr")
                        key_value_pairs = []
                    
                        for i, row in enumerate(rows):
                            try:
                                th_elements = row.find_elements(By.TAG_NAME, "th")
                                td_elements = row.find_elements(By.TAG_NAME, "td")
                        
                                if len(th_elements) == 1 and len(td_elements) == 1:
                                    key = th_elements[0].text.strip()
                                    value = td_elements[0].text.strip()
                            
                                    if key and value:
                                        key_value_pairs.append({
                                            "key": key, 
                                            "value": value, 
                                            "row_index": i
                                        })
                            except:
                                continue
                    
                        if key_value_pairs:
                            change_request = self._build_change_request_from_pairs_fixed(key_value_pairs)
                            if change_request:
                                change_request_data["table_rows"] = [change_request]
                                change_request_data["total_rows"] = 1
                                change_request_data["extraction_source"] = "fallback_extraction"
                                change_request_data["raw_table_text"] = table.text.strip()
                            
                                return change_request_data
                            
                except Exception:
                    continue
        
            return change_request_data
        
        except Exception:
            return change_request_data

# ==================== MAIN AUTOMATION CLASS ====================

class OctotelValidationAutomation:
    """Main automation class for Octotel validation"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.browser_service: Optional[BrowserService] = None
        self.screenshot_service: Optional[ScreenshotService] = None
        self.driver: Optional[webdriver.Chrome] = None
        self.input_handler: Optional[RobustInputHandler] = None
        self.data_extractor: Optional[RobustDataExtractor] = None
        self.screenshots: List[ScreenshotData] = []
    
    def _setup_services(self, job_id: str):
        """Setup required services"""
        self.browser_service = BrowserService()
        self.driver = self.browser_service.create_driver(job_id)
        self.screenshot_service = ScreenshotService(job_id)
        self.input_handler = RobustInputHandler(self.logger)
        self.data_extractor = RobustDataExtractor(self.driver, self.logger)
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
            return None
            
        try:
            screenshot = self.screenshot_service.take_screenshot(self.driver, name)
            if screenshot:
                self.screenshots.append(screenshot)
            return screenshot
        except Exception:
            return None

    def get_all_screenshots(self) -> List[ScreenshotData]:
        """Get all screenshots taken"""
        if self.screenshot_service:
            return self.screenshot_service.get_all_screenshots()
        return self.screenshots

    def navigate_to_services(self) -> bool:
        """Navigate to Services page"""
        try:
            logger.info("Navigating to Services page")
            
            services_selectors = [
                "div.navbar li:nth-of-type(2) > a",
                "//div[contains(@class, 'navbar')]//a[contains(text(), 'Services')]",
                "//a[contains(text(), 'Services')]",
                "//a[@aria-label='Services']"
            ]
            
            services_link = None
            wait = WebDriverWait(self.driver, 15)
            
            for selector in services_selectors:
                try:
                    if selector.startswith("//"):
                        services_link = wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                    else:
                        services_link = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                    break
                except TimeoutException:
                    continue
            
            if not services_link:
                raise Exception("Services navigation link not found")
            
            if not robust_click(self.driver, services_link, "Services link"):
                raise Exception("Failed to click Services link")
            
            logger.info("Successfully navigated to Services")
            time.sleep(3)
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to navigate to services: {str(e)}")
            return False

    def _create_streamlined_success_result(self, request: ValidationRequest, all_services: List[Dict], 
                                        matching_services: List[Dict], service_details: Dict, 
                                        execution_time: float) -> ValidationResult:
        """Create streamlined success result with clean structure"""
        
        # Initialize streamlined processor
        processor = StreamlinedDataProcessor(self.logger)
        
        # Process each matching service into clean structured data
        structured_services = []
        for raw_service in matching_services:
            structured_service = processor.create_streamlined_service_data(raw_service, service_details)
            structured_services.append(structured_service)
        
        # Organize raw data for audit trail
        raw_extraction = processor.organize_raw_extraction_data(
            all_services, matching_services, service_details
        )
        
        # Calculate overall completeness
        overall_completeness = 0.0
        if structured_services:
            completeness_scores = [
                service.get("data_completeness", {}).get("overall_score", 0.0) 
                for service in structured_services
            ]
            overall_completeness = sum(completeness_scores) / len(completeness_scores)
        
        # Build streamlined details
        details = {
            # FINAL STRUCTURED DATA (for consumption)
            "services": structured_services,
            
            # RAW SCRAPED DATA (for auditing/debugging)  
            "raw_extraction": raw_extraction,
            
            # METADATA
            "extraction_metadata": {
                "total_services_found": len(matching_services),
                "total_services_scanned": len(all_services),
                "search_term": request.circuit_number,
                "extraction_timestamp": datetime.now().isoformat(),
                "completeness_score": overall_completeness,
                "processing_approach": "streamlined_v1.0"
            }
        }
        
        # Add backward compatibility fields from primary service
        if structured_services:
            primary_service = structured_services[0]
            details.update({
                "found": True,
                "circuit_number": primary_service["service_identifiers"]["primary_id"],
                "customer_name": primary_service["customer_information"].get("name", ""),
                "service_type": primary_service["service_details"].get("type", ""),
                "service_address": primary_service["location_information"].get("address", ""),
                "current_status": primary_service["status_information"].get("current_status", ""),
            })
        
        return ValidationResult(
            job_id=request.job_id,
            circuit_number=request.circuit_number,
            status=ValidationStatus.SUCCESS,
            message=f"Successfully extracted {len(matching_services)} services. "
                f"Completeness: {overall_completeness:.1%}",
            found=True,
            search_result=SearchResult.FOUND,
            execution_time=execution_time,
            screenshots=self.get_all_screenshots(),
            evidence_dir=str(self.screenshot_service.evidence_dir) if self.screenshot_service else None,
            details=details
        )

    def search_for_circuit(self, circuit_number: str) -> SearchResult:
        """Search for specific circuit with proper status filter configuration"""
        try:
            logger.info(f"Searching for circuit: {circuit_number}")
            
            # Configure status filters
            self._configure_status_filters()
            
            # Find search field
            search_selectors = [
                "#search",
                "input[ng-model='filter.search']",
                "input[placeholder='Search...']",
                "//input[@id='search']",
                "//input[@ng-model='filter.search']"
            ]
            
            search_field = None
            for selector in search_selectors:
                try:
                    if selector.startswith("//"):
                        search_field = self.driver.find_element(By.XPATH, selector)
                    else:
                        search_field = self.driver.find_element(By.CSS_SELECTOR, selector)
                    
                    if search_field.is_displayed() and search_field.is_enabled():
                        break
                except:
                    continue
            
            if not search_field:
                return SearchResult.ERROR
            
            # Fill search field
            search_success = self.input_handler.fill_input_robustly(search_field, circuit_number)
            
            if not search_success:
                try:
                    search_field.clear()
                    search_field.send_keys(circuit_number)
                    search_success = True
                except Exception:
                    return SearchResult.ERROR
            
            # Submit search
            search_field.send_keys(Keys.RETURN)
            logger.info(f"Search submitted for '{circuit_number}'")
            
            # Wait for results
            time.sleep(5)
            
            # Extract all services and check for matches
            all_services = self.data_extractor.extract_all_services()
            
            # Filter matching services
            matching_services = []
            for service in all_services:
                fields_to_check = [
                    service.get("full_row_text", ""),
                    service.get("service_id", ""),
                    service.get("line_reference", ""),
                    service.get("column_1", ""),
                    service.get("column_2", ""),
                ]
                
                search_term_lower = circuit_number.lower()
                for field_value in fields_to_check:
                    if field_value and search_term_lower in str(field_value).lower():
                        matching_services.append(service)
                        break
            
            # Store results
            self._search_results = {
                'all_services': all_services,
                'matching_services': matching_services,
                'search_term': circuit_number
            }
            
            logger.info(f"Found {len(matching_services)} matching services out of {len(all_services)} total")
            
            if matching_services:
                return SearchResult.FOUND
            else:
                return SearchResult.NOT_FOUND
                
        except Exception as e:
            self.logger.error(f"Search failed: {str(e)}")
            return SearchResult.ERROR
        
    def _configure_status_filters(self):
        """Configure status filters for comprehensive search"""
        try:
            wait = WebDriverWait(self.driver, 15)
        
            # First dropdown (row filter)
            try:
                first_select = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.row > div:nth-of-type(1) select")
                ))
                select_obj = Select(first_select)
                select_obj.select_by_value("")  # Set to "All"
                time.sleep(1)
            except Exception:
                pass
        
            # Third dropdown (status filter) 
            try:
                third_select = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div:nth-of-type(3) select")
                ))
                select_obj = Select(third_select)
                select_obj.select_by_value("1")  # Set to show active services
                time.sleep(1)
            except Exception:
                pass
            
        except Exception:
            pass

    def click_service_row(self, service_id: str) -> bool:
        """Click on specific service row to open details"""
        try:
            table_selectors = [
                "div.app-body table",
                "//table"
            ]
            
            table = None
            for selector in table_selectors:
                try:
                    if selector.startswith("//"):
                        table = self.driver.find_element(By.XPATH, selector)
                    else:
                        table = self.driver.find_element(By.CSS_SELECTOR, selector)
                    break
                except:
                    continue
            
            if not table:
                return False
            
            service_rows = table.find_elements(By.XPATH, f".//tr[contains(., '{service_id}')]")
            
            if service_rows:
                service_rows[0].click()
                time.sleep(2)
                logger.info(f"Clicked service row for {service_id}")
                return True
            else:
                return False
                
        except Exception:
            return False

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

    def _create_not_found_result(self, request: ValidationRequest, all_services: List[Dict], execution_time: float) -> ValidationResult:
        """Create not found result"""
        return ValidationResult(
            job_id=request.job_id,
            circuit_number=request.circuit_number,
            status=ValidationStatus.SUCCESS,
            message=f"Circuit {request.circuit_number} not found. Searched {len(all_services)} services.",
            found=False,
            search_result=SearchResult.NOT_FOUND,
            execution_time=execution_time,
            screenshots=self.get_all_screenshots(),
            evidence_dir=str(self.screenshot_service.evidence_dir) if self.screenshot_service else None,
            details={
                "found": False,
                "total_services_searched": len(all_services),
                "search_term": request.circuit_number,
                "all_services": all_services
            }
        )

    def validate_circuit(self, request: ValidationRequest) -> ValidationResult:
        """Main validation method"""
        start_time = time.time()
        
        try:
            logger.info(f"Starting validation for circuit {request.circuit_number}")
            
            # Setup services
            self._setup_services(request.job_id)
            self.take_screenshot("initial_state")
            
            # Login
            login_handler = OctotelTOTPLogin()
            login_success = login_handler.login(self.driver)
            
            if not login_success:
                raise Exception("Login failed")
            
            self.take_screenshot("after_login")
            
            # Navigate to services
            if not self.navigate_to_services():
                raise Exception("Failed to navigate to services")
            
            # Search for circuit
            search_result = self.search_for_circuit(request.circuit_number)
            self.take_screenshot("search_completed")
            
            if search_result == SearchResult.ERROR:
                return self._create_error_result(request, "Search operation failed")
            
            # Get search results
            search_data = getattr(self, '_search_results', {})
            all_services = search_data.get('all_services', [])
            matching_services = search_data.get('matching_services', [])
            
            if search_result == SearchResult.NOT_FOUND:
                return self._create_not_found_result(request, all_services, time.time() - start_time)
            
            # Extract detailed info for first matching service
            service_details = {}
            if matching_services:
                primary_service = matching_services[0]
                service_id = primary_service.get('service_id', '')
                
                # Click on service to get details
                if self.click_service_row(service_id):
                    service_details = self.data_extractor.extract_service_details(service_id)
                    self.take_screenshot("service_details_extracted")
                    
                    # Log change requests if found
                    change_requests_data = service_details.get("change_requests_data", {})
                    if change_requests_data.get("table_rows"):
                        logger.info(f"Found {len(change_requests_data['table_rows'])} change requests")
                        for cr in change_requests_data["table_rows"]:
                            logger.info(f"Change Request: {cr.get('change_request_id', 'N/A')} - {cr.get('change_request_type', 'N/A')} - {cr.get('change_request_status', 'N/A')}")
            
            # Calculate execution time
            execution_time = time.time() - start_time
            
            # Create success result
            result = self._create_streamlined_success_result(
                request, all_services, matching_services, service_details, execution_time
            )
            
            logger.info(f"Validation completed successfully in {execution_time:.2f}s")
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

# ==================== MAIN EXECUTION ====================

def execute(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Main execution function for external API calls"""
    try:
        # Validate configuration
        if not all([Config.OCTOTEL_USERNAME, Config.OCTOTEL_PASSWORD, Config.OCTOTEL_TOTP_SECRET]):
            logger.error("Missing required Octotel configuration")
            return {
                "status": "error",
                "message": "Missing required Octotel configuration",
                "details": {"error": "configuration_missing"},
                "screenshot_data": []
            }
        
        # Create validation request
        request = ValidationRequest(
            job_id=parameters.get("job_id"),
            circuit_number=parameters.get("circuit_number")
        )
        
        logger.info(f"Starting validation for circuit: {request.circuit_number}")
        
        # Execute validation
        automation = OctotelValidationAutomation()
        result = automation.validate_circuit(request)
        
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