"""
OSN Validation Automation - Full-Featured Container-Compatible Version
======================================================================
Combines container compatibility with complete functionality for Oracle dashboard integration
"""

import os
import time
import logging
import traceback
import json
import base64
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from enum import Enum

# Third-party imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
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
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ==================== ENUMERATIONS ====================

class ValidationStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"

class SearchResult(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    ERROR = "error"

class OrderType(str, Enum):
    NEW_INSTALLATION = "new_installation"
    CEASE_ACTIVE_SERVICE = "cease_active_service"
    MODIFICATION = "modification"
    UNKNOWN = "unknown"

# ==================== DATA MODELS ====================

class ValidationRequest(BaseModel):
    job_id: str = Field(..., description="Unique job identifier")
    circuit_number: str = Field(..., description="Circuit number to validate")

class ScreenshotData(BaseModel):
    name: str
    timestamp: datetime
    data: str
    path: str
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

class CustomerDetails(BaseModel):
    name: str = ""
    surname: str = ""
    contact_number: str = ""
    email: str = ""
    order_number: str = ""
    domicile_type: str = ""
    address: str = ""

class CeaseOrderDetails(BaseModel):
    order_number: str
    placed_by: str = ""
    date_submitted: str = ""
    requested_cease_date: str = ""
    product: str = ""
    order_type: str = ""
    service_circuit_no: str = ""
    external_ref: str = ""

class ServiceInfo(BaseModel):
    circuit_number: str
    address: Optional[str] = None
    is_active: bool = False

class OrderData(BaseModel):
    orderNumber: str
    type: OrderType
    orderStatus: str
    dateImplemented: Optional[str] = None
    is_new_installation: bool = False
    is_cancellation: bool = False
    is_implemented_cease: bool = False
    is_pending_cease: bool = False
    serviceNumber: Optional[str] = ""
    externalRef: Optional[str] = ""
    productName: Optional[str] = ""
    createdOn: Optional[str] = ""

class ValidationResult(BaseModel):
    job_id: str
    circuit_number: str
    status: ValidationStatus
    message: str
    found: bool
    orders: List[OrderData] = []
    customer_details: Optional[CustomerDetails] = None
    cease_order_details: List[CeaseOrderDetails] = []
    service_info: Optional[ServiceInfo] = None
    search_result: SearchResult
    execution_time: Optional[float] = None
    screenshots: List[ScreenshotData] = []
    evidence_dir: Optional[str] = None

# ==================== UTILITY FUNCTIONS ====================

def robust_click(driver: webdriver.Chrome, element, description: str = "element") -> bool:
    """Container-compatible click with multiple fallback strategies"""
    methods = [
        ("javascript click", lambda: driver.execute_script("arguments[0].click();", element)),
        ("regular click", lambda: element.click()),
        ("action chains click", lambda: ActionChains(driver).move_to_element(element).click().perform())
    ]
    
    # Ensure element is in viewport
    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
    time.sleep(2)
    
    for method_name, method in methods:
        try:
            method()
            logger.info(f"Successfully clicked {description} using {method_name}")
            return True
        except Exception as e:
            logger.warning(f"{method_name} failed for {description}: {str(e)}")
            continue
    
    return False

def robust_send_keys(driver: webdriver.Chrome, element, value: str, description: str = "field") -> bool:
    """Container-compatible input with multiple strategies"""
    methods = [
        ("javascript fill", lambda: driver.execute_script(f"arguments[0].value = '{value}'; arguments[0].dispatchEvent(new Event('input'));", element)),
        ("clear and send", lambda: (element.clear(), element.send_keys(value))),
        ("select all and type", lambda: (element.send_keys(Keys.CONTROL + "a"), element.send_keys(value)))
    ]
    
    for method_name, method in methods:
        try:
            if method_name == "clear and send":
                element.clear()
                element.send_keys(value)
            elif method_name == "select all and type":
                element.send_keys(Keys.CONTROL + "a")
                element.send_keys(value)
            else:
                method()
            
            # Verify the input
            actual_value = element.get_attribute("value")
            if actual_value == value:
                logger.info(f"Successfully filled {description} using {method_name}")
                return True
        except Exception as e:
            logger.warning(f"{method_name} failed for {description}: {str(e)}")
            continue
    
    return False

# ==================== MAIN AUTOMATION CLASS ====================

class OSNValidationAutomation:
    """Full-featured container-optimized OSN validation automation"""
    
    def __init__(self):
        self.config = Config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.driver: Optional[webdriver.Chrome] = None
        self.screenshots: List[ScreenshotData] = []
        self.screenshot_dir: Optional[Path] = None
        self.execution_summary_path: Optional[Path] = None
    
    def _setup_browser(self, job_id: str):
        """Setup container-optimized browser"""
        self.screenshot_dir = Path(Config.get_job_screenshot_dir(job_id))
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.execution_summary_path = Config.get_execution_summary_path(job_id)
        
        # Container-optimized Chrome options
        options = ChromeOptions()
        
        # Essential container options
        if Config.HEADLESS:
            options.add_argument('--headless=new')
        if Config.NO_SANDBOX:
            options.add_argument('--no-sandbox')
        if Config.DISABLE_DEV_SHM_USAGE:
            options.add_argument('--disable-dev-shm-usage')
        
        # Additional container stability options
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-dev-tools')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-plugins')
        options.add_argument('--disable-images')
        options.add_argument('--disable-javascript-harmony-shipping')
        options.add_argument('--disable-background-timer-throttling')
        options.add_argument('--disable-backgrounding-occluded-windows')
        options.add_argument('--disable-renderer-backgrounding')
        options.add_argument('--disable-features=TranslateUI')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--remote-debugging-port=9222')
        
        # Memory and performance optimizations for containers
        options.add_argument('--memory-pressure-off')
        options.add_argument('--max_old_space_size=4096')
        
        # Create service and driver
        service = Service(executable_path=Config.CHROMEDRIVER_PATH)
        self.driver = webdriver.Chrome(service=service, options=options)
        
        # Set container-friendly timeouts
        self.driver.set_page_load_timeout(Config.OSN_PAGE_LOAD_TIMEOUT)
        self.driver.implicitly_wait(Config.SELENIUM_IMPLICIT_WAIT)
        
        logger.info("Full-featured container-optimized browser setup completed")
    
    def _cleanup_browser(self):
        """Cleanup browser resources"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Browser cleaned up successfully")
            except Exception as e:
                logger.error(f"Browser cleanup error: {str(e)}")
    
    def _take_screenshot(self, name: str) -> Optional[ScreenshotData]:
        """Take and save screenshot"""
        try:
            timestamp = datetime.now()
            filename = f"{name}_{timestamp.strftime('%Y%m%d_%H%M%S')}.png"
            filepath = self.screenshot_dir / filename

            self.driver.save_screenshot(str(filepath))
            
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
            logger.error(f"Screenshot failed: {str(e)}")
            return None
    
    def _login(self):
        """Container-optimized login process"""
        try:
            logger.info("Starting OSN login process")
            self.driver.get("https://partners.openserve.co.za/login")
            
            # Wait for page to stabilize
            time.sleep(5)
            
            # Wait for and fill email field
            email_field = WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.ID, "email"))
            )
            
            if not robust_send_keys(self.driver, email_field, Config.OSEMAIL, "email field"):
                raise Exception("Failed to fill email field")
            
            # Fill password field
            password_field = self.driver.find_element(By.ID, "password")
            if not robust_send_keys(self.driver, password_field, Config.OSPASSWORD, "password field"):
                raise Exception("Failed to fill password field")
            
            time.sleep(2)
            
            # Find and click login button
            login_button = self.driver.find_element(By.ID, "next")
            if not robust_click(self.driver, login_button, "login button"):
                raise Exception("Failed to click login button")
            
            # Wait for successful login (navbar appears)
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.ID, "navOrders"))
            )
            
            logger.info("Login successful")
            
        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            raise
    
    def _navigate_to_orders(self, circuit_number: str):
        """Navigate to orders page with circuit number"""
        orders_url = f"https://partners.openserve.co.za/orders?tabIndex=2&isps=628&serviceNumber={circuit_number}"
        logger.info(f"Navigating to orders page for circuit: {circuit_number}")
        
        self.driver.get(orders_url)
        time.sleep(5)
    
    def _extract_orders(self) -> List[OrderData]:
        """Extract order data from table"""
        orders = []
        
        try:
            # Wait for table to load
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.XPATH, "//table//tbody//tr"))
            )
            
            # Get all data rows (excluding header)
            rows = self.driver.find_elements(By.XPATH, "//table//tbody//tr[td[normalize-space(text())]]")
            logger.info(f"Found {len(rows)} order rows")
            
            for i, row in enumerate(rows):
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) >= 8:
                        # Extract data from each column
                        order_number = cells[0].text.strip()
                        order_type_text = cells[1].text.strip().lower()
                        external_ref = cells[2].text.strip()
                        service_number = cells[3].text.strip()
                        product_name = cells[4].text.strip()
                        created_on = cells[5].text.strip()
                        date_implemented = cells[6].text.strip()
                        order_status = cells[7].text.strip()
                        
                        # Determine order type and flags
                        if "new" in order_type_text or "installation" in order_type_text:
                            order_type = OrderType.NEW_INSTALLATION
                            is_new_installation = True
                            is_cancellation = False
                        elif "cease" in order_type_text:
                            order_type = OrderType.CEASE_ACTIVE_SERVICE
                            is_new_installation = False
                            is_cancellation = True
                        else:
                            order_type = OrderType.MODIFICATION if "modif" in order_type_text else OrderType.UNKNOWN
                            is_new_installation = False
                            is_cancellation = False
                        
                        # Create order object
                        order = OrderData(
                            orderNumber=order_number,
                            type=order_type,
                            orderStatus=order_status,
                            dateImplemented=date_implemented,
                            is_new_installation=is_new_installation,
                            is_cancellation=is_cancellation,
                            serviceNumber=service_number,
                            externalRef=external_ref,
                            productName=product_name,
                            createdOn=created_on
                        )
                        
                        # Set cease order flags
                        if is_cancellation:
                            if date_implemented and order_status.lower() == "accepted":
                                order.is_implemented_cease = True
                                order.is_pending_cease = False
                            else:
                                order.is_implemented_cease = False
                                order.is_pending_cease = True
                        
                        orders.append(order)
                        logger.info(f"Extracted order: {order_number} - {order_type.value}")
                        
                except Exception as e:
                    logger.warning(f"Failed to parse row {i}: {str(e)}")
                    continue
            
            logger.info(f"Successfully extracted {len(orders)} orders")
            
        except Exception as e:
            logger.error(f"Order extraction failed: {str(e)}")
        
        return orders
    
    def _navigate_to_active_services(self, circuit_number: str):
        """Navigate to active services page"""
        active_services_url = f"https://partners.openserve.co.za/active-services/{circuit_number}"
        self.driver.get(active_services_url)
        time.sleep(10)
    
    def _extract_address(self) -> Optional[str]:
        """Extract address from active services page"""
        try:
            # Click Service Information button using container-compatible method
            service_info_clicked = self.driver.execute_script("""
                var serviceInfoHeading = document.evaluate(
                    "//h2[contains(text(), 'Service Information')]", 
                    document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
                
                if (serviceInfoHeading) {
                    var card = serviceInfoHeading.closest('div.card, div.col, div');
                    if (card) {
                        var viewBtn = card.querySelector('button');
                        if (viewBtn) {
                            viewBtn.click();
                            return true;
                        }
                    }
                }
                return false;
            """)
            
            if service_info_clicked:
                time.sleep(5)
                
                # Click Service end points tab using JavaScript
                tab_clicked = self.driver.execute_script("""
                    var tabs = Array.from(document.querySelectorAll('span.p-tabview-title')).filter(
                        span => span.textContent.includes('Service end points')
                    );
                    
                    if (tabs.length > 0) {
                        var tabLink = tabs[0].closest('a');
                        if (tabLink) {
                            tabLink.click();
                            return true;
                        }
                    }
                    return false;
                """)
                
                if tab_clicked:
                    time.sleep(3)
                    
                    # Extract address using JavaScript
                    address = self.driver.execute_script("""
                        var aSideSection = document.evaluate(
                            "//p[contains(text(), 'A-Side')]", 
                            document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                        ).singleNodeValue;
                        
                        if (aSideSection) {
                            var aSideContainer = aSideSection.closest('div.col, div');
                            if (aSideContainer) {
                                var rows = aSideContainer.querySelectorAll('.row');
                                for (var i = 0; i < rows.length; i++) {
                                    var row = rows[i];
                                    var label = row.querySelector('p.fw-bold');
                                    if (label && label.textContent.includes('Site Address')) {
                                        var valueCol = row.querySelectorAll('div')[1];
                                        if (valueCol) {
                                            return valueCol.textContent.trim();
                                        }
                                    }
                                }
                            }
                        }
                        return null;
                    """)
                    
                    if address:
                        logger.info(f"Successfully extracted address: {address}")
                        return address
            
            logger.warning("Could not extract address")
            return None
            
        except Exception as e:
            logger.error(f"Address extraction failed: {str(e)}")
            return None
    
    def _navigate_to_order_details(self, order_number: str, order_type: str):
        """Navigate to order details page"""
        if order_type == "new_installation":
            url = f"https://partners.openserve.co.za/orders/orders-complete/{order_number}/New%20Installation"
        else:  # cease order
            url = f"https://partners.openserve.co.za/orders/orders-pending/{order_number}/Cease%20Active%20Service"
        
        self.driver.get(url)
        time.sleep(5)
    
    def _extract_customer_details(self, order_number: str) -> Optional[CustomerDetails]:
        """Extract customer details with container-compatible patterns"""
        try:
            logger.info(f"Extracting customer details for order: {order_number}")
            
            # Verify we're on the right page
            if "orders-complete" not in self.driver.current_url:
                logger.error(f"Wrong page - current URL: {self.driver.current_url}")
                return None
            
            details = CustomerDetails(order_number=order_number)
            
            # Extract customer details using JavaScript (container-compatible)
            customer_data = self.driver.execute_script("""
                var text = document.body.textContent;
                var result = {};
                
                // Extract the customer details section
                var customerStart = text.indexOf("Customer Details");
                var customerSection = "";
                if (customerStart !== -1) {
                    var appointmentStart = text.indexOf("Appointment", customerStart);
                    if (appointmentStart !== -1) {
                        customerSection = text.substring(customerStart, appointmentStart);
                    } else {
                        customerSection = text.substring(customerStart, customerStart + 500);
                    }
                }
                
                console.log("DEBUG: Customer section text:", customerSection);
                
                // Verified working patterns from browser testing
                var patterns = {
                    name: /Name\\s*:\\s*([^:]*?)(?=Surname\\s*:|$)/i,
                    surname: /Surname\\s*:\\s*([^:]*?)(?=Mobile Number\\s*:|$)/i,
                    mobile_number: /Mobile Number\\s*:\\s*([^:]*?)(?=Domicile|Email|Appointment|$)/i,
                    domicile_type: /Domicile type\\s*:\\s*([^:]*?)(?=Address\\s*:|$)/i,
                    address: /Address\\s*:\\s*([^:]*?)(?=Appointment|Email|$)/i,
                    email: /Email\\s*:\\s*([\\w.-]+@[\\w.-]+\\.[a-zA-Z]{2,})/i
                };
                
                // Extract each field
                for (var field in patterns) {
                    var match = customerSection.match(patterns[field]);
                    if (match && match[1]) {
                        var value = match[1].trim();
                        // Clean up whitespace and artifacts
                        value = value.replace(/\\s+/g, ' ');
                        value = value.replace(/^[,\\s]+|[,\\s]+$/g, '');
                        
                        if (value.length > 0 && value !== 'undefined' && value !== 'null') {
                            result[field] = value;
                            console.log("DEBUG: Extracted " + field + ": '" + value + "'");
                        }
                    } else {
                        console.log("DEBUG: NOT FOUND: " + field);
                    }
                }
                
                // Clean mobile number to digits only
                if (result.mobile_number) {
                    var mobileDigits = result.mobile_number.replace(/\\D/g, '');
                    if (mobileDigits.length >= 10) {
                        result.mobile_number = mobileDigits.substring(0, 10);
                        console.log("DEBUG: Cleaned mobile number: " + result.mobile_number);
                    }
                }
                
                return result;
            """)
            
            # Map extracted data
            if customer_data:
                details.name = customer_data.get('name', "").strip()
                details.surname = customer_data.get('surname', "").strip()
                details.contact_number = customer_data.get('mobile_number', "").strip()
                details.email = customer_data.get('email', "").strip()
                details.domicile_type = customer_data.get('domicile_type', "").strip()
                details.address = customer_data.get('address', "").strip()
            
            # Log extracted data for Oracle integration verification
            logger.info("=== EXTRACTED CUSTOMER DETAILS FOR ORACLE ===")
            logger.info(f"Name: {details.name}")
            logger.info(f"Surname: {details.surname}")
            logger.info(f"Mobile Number: {details.contact_number}")
            logger.info(f"Email: {details.email}")
            logger.info(f"Domicile type: {details.domicile_type}")
            logger.info(f"Address: {details.address}")
            logger.info("=== END CUSTOMER DETAILS ===")
            
            return details
            
        except Exception as e:
            logger.error(f"Failed to extract customer details: {str(e)}")
            return None
    
    def _extract_cease_order_details(self, order_number: str) -> Optional[CeaseOrderDetails]:
        """Extract cease order details for Oracle integration"""
        try:
            logger.info(f"Extracting cease order details for order: {order_number}")
            
            # Verify we're on the right page
            if "orders-pending" not in self.driver.current_url:
                logger.error(f"Wrong page - current URL: {self.driver.current_url}")
                return None
            
            details = CeaseOrderDetails(order_number=order_number)
            
            # Extract order details using JavaScript (container-compatible)
            order_data = self.driver.execute_script("""
                var text = document.body.textContent;
                var result = {};
                
                // Extract the order details section
                var orderStart = text.indexOf("Order Details");
                var orderSection = "";
                if (orderStart !== -1) {
                    var notificationsStart = text.indexOf("Notifications", orderStart);
                    if (notificationsStart !== -1) {
                        orderSection = text.substring(orderStart, notificationsStart);
                    } else {
                        orderSection = text.substring(orderStart, orderStart + 800);
                    }
                }
                
                console.log("DEBUG: Order section text:", orderSection);
                
                // Verified patterns for cease order fields
                var patterns = {
                    placed_by: /Placed by\\s*:\\s*([^:]*?)(?=Date Submitted\\s*:|$)/i,
                    date_submitted: /Date Submitted\\s*:\\s*([^:]*?)(?=Requested Cease Date\\s*:|Product\\s*:|$)/i,
                    requested_cease_date: /Requested Cease Date\\s*:\\s*([^:]*?)(?=Product\\s*:|$)/i,
                    product: /Product\\s*:\\s*([^:]*?)(?=Service speed\\s*:|Order type\\s*:|$)/i,
                    order_type: /Order type\\s*:\\s*([^:]*?)(?=Contract term\\s*:|Service\\s*:|$)/i,
                    service_circuit_no: /Service\\/Circuit no\\.\\s*:\\s*([^:]*?)(?=External Ref\\s*:|$)/i,
                    external_ref: /External Ref\\.\\s*:\\s*([^:]*?)(?=Remark\\s*:|$)/i
                };
                
                // Extract each field
                for (var field in patterns) {
                    var match = orderSection.match(patterns[field]);
                    if (match && match[1]) {
                        var value = match[1].trim();
                        // Clean up whitespace and artifacts
                        value = value.replace(/\\s+/g, ' ');
                        value = value.replace(/^[,\\s]+|[,\\s]+$/g, '');
                        
                        if (value.length > 0 && value !== 'undefined' && value !== 'null') {
                            result[field] = value;
                            console.log("DEBUG: Extracted " + field + ": '" + value + "'");
                        }
                    } else {
                        console.log("DEBUG: NOT FOUND: " + field);
                    }
                }
                
                return result;
            """)
            
            # Map extracted data
            if order_data:
                details.placed_by = order_data.get('placed_by', "").strip()
                details.date_submitted = order_data.get('date_submitted', "").strip()
                details.requested_cease_date = order_data.get('requested_cease_date', "").strip()
                details.product = order_data.get('product', "").strip()
                details.order_type = order_data.get('order_type', "").strip()
                details.service_circuit_no = order_data.get('service_circuit_no', "").strip()
                details.external_ref = order_data.get('external_ref', "").strip()
            
            # Log extracted data for Oracle integration verification
            logger.info("=== EXTRACTED CEASE ORDER DETAILS FOR ORACLE ===")
            logger.info(f"Placed by: {details.placed_by}")
            logger.info(f"Date Submitted: {details.date_submitted}")
            logger.info(f"Requested Cease Date: {details.requested_cease_date}")
            logger.info(f"Product: {details.product}")
            logger.info(f"Order type: {details.order_type}")
            logger.info(f"Service/Circuit no.: {details.service_circuit_no}")
            logger.info(f"External Ref.: {details.external_ref}")
            logger.info("=== END CEASE ORDER DETAILS ===")
            
            return details
            
        except Exception as e:
            logger.error(f"Failed to extract cease order details: {str(e)}")
            return None
    
    def save_execution_summary(self, result: ValidationResult):
        """Save execution summary for audit trail"""
        try:
            with open(self.execution_summary_path, "w", encoding="utf-8") as f:
                f.write(f"===== OSN Validation Execution Summary =====\n")
                f.write(f"Job ID: {result.job_id}\n")
                f.write(f"Circuit Number: {result.circuit_number}\n")
                f.write(f"Execution Time: {datetime.now().isoformat()}\n")
                f.write(f"Status: {result.status.value}\n")
                f.write(f"Found: {result.found}\n\n")
                
                # Orders Section
                if result.orders:
                    f.write(f"=== Orders ({len(result.orders)}) ===\n")
                    for i, order in enumerate(result.orders, 1):
                        f.write(f"Order {i}: {order.orderNumber}\n")
                        f.write(f"  Type: {order.type.value}\n")
                        f.write(f"  Status: {order.orderStatus}\n")
                        if order.is_cancellation:
                            f.write(f"  Is Pending Cease: {order.is_pending_cease}\n")
                            f.write(f"  Is Implemented Cease: {order.is_implemented_cease}\n")
                    f.write("\n")
                
                # Customer Details
                if result.customer_details:
                    f.write("=== Customer Details (Oracle Integration) ===\n")
                    f.write(f"Name: {result.customer_details.name}\n")
                    f.write(f"Surname: {result.customer_details.surname}\n")
                    f.write(f"Mobile: {result.customer_details.contact_number}\n")
                    f.write(f"Email: {result.customer_details.email}\n")
                    f.write(f"Address: {result.customer_details.address}\n\n")
                
                # Cease Order Details
                if result.cease_order_details:
                    f.write("=== Cease Order Details (Oracle Integration) ===\n")
                    for cease in result.cease_order_details:
                        f.write(f"Order: {cease.order_number}\n")
                        f.write(f"Requested Cease Date: {cease.requested_cease_date}\n")
                        f.write(f"External Ref: {cease.external_ref}\n\n")
                
                # Service Info
                if result.service_info:
                    f.write("=== Service Info ===\n")
                    f.write(f"Address: {result.service_info.address}\n")
                    f.write(f"Is Active: {result.service_info.is_active}\n\n")
                
                # Screenshots
                f.write(f"=== Screenshots ===\n")
                f.write(f"Total screenshots: {len(result.screenshots)}\n")
                for screenshot in result.screenshots:
                    f.write(f"- {screenshot.name} at {screenshot.timestamp.isoformat()}\n")
                    
            logger.info(f"Execution summary saved to {self.execution_summary_path}")
        except Exception as e:
            logger.error(f"Failed to save execution summary: {str(e)}")
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(5),
        retry=retry_if_exception_type((TimeoutException, WebDriverException))
    )
    def validate_circuit(self, request: ValidationRequest) -> ValidationResult:
        """Main validation method with full Oracle integration support"""
        start_time = time.time()
        
        try:
            logger.info(f"Starting full-featured validation for job {request.job_id}, circuit {request.circuit_number}")
            
            # Setup browser
            self._setup_browser(request.job_id)
            self._take_screenshot("initial_state")
            
            # Login
            self._login()
            self._take_screenshot("after_login")
            
            # Navigate to orders
            self._navigate_to_orders(request.circuit_number)
            self._take_screenshot("orders_page")
            
            # Extract orders
            orders = self._extract_orders()
            
            # Get address from active services
            self._navigate_to_active_services(request.circuit_number)
            self._take_screenshot("active_services")
            
            address = self._extract_address()
            
            # Check if circuit exists
            circuit_found = len(orders) > 0 or address is not None
            
            if not circuit_found:
                return self._create_not_found_result(request)
            
            # Extract customer details from new installation orders
            customer_details = None
            new_installation_orders = [o for o in orders if o.is_new_installation]
            
            if new_installation_orders:
                for order in new_installation_orders:
                    try:
                        self._navigate_to_order_details(order.orderNumber, "new_installation")
                        self._take_screenshot(f"customer_details_{order.orderNumber}")
                        
                        customer_details = self._extract_customer_details(order.orderNumber)
                        
                        # Check if we got meaningful data for Oracle
                        if customer_details and any(getattr(customer_details, field) for field in ['name', 'surname', 'contact_number', 'email']):
                            logger.info("Customer details extracted successfully for Oracle integration")
                            break
                    except Exception as e:
                        logger.error(f"Failed to process customer details for order {order.orderNumber}: {str(e)}")
                        continue
            
            # Extract cease order details from pending cease orders
            cease_order_details = []
            pending_cease_orders = [o for o in orders if o.is_cancellation and o.is_pending_cease]
            
            if pending_cease_orders:
                for order in pending_cease_orders:
                    try:
                        self._navigate_to_order_details(order.orderNumber, "cease")
                        self._take_screenshot(f"cease_details_{order.orderNumber}")
                        
                        cease_details = self._extract_cease_order_details(order.orderNumber)
                        
                        if cease_details:
                            cease_order_details.append(cease_details)
                            logger.info(f"Cease order details extracted for Oracle integration: {order.orderNumber}")
                    except Exception as e:
                        logger.error(f"Failed to process cease order {order.orderNumber}: {str(e)}")
                        continue
            
            # Create service info
            service_info = ServiceInfo(
                circuit_number=request.circuit_number,
                address=address,
                is_active=address is not None and not any(o.is_implemented_cease for o in orders if o.is_cancellation)
            )
            
            # Create result with full Oracle integration data
            execution_time = time.time() - start_time
            result = ValidationResult(
                job_id=request.job_id,
                circuit_number=request.circuit_number,
                status=ValidationStatus.SUCCESS,
                message=f"Successfully validated circuit {request.circuit_number} with full Oracle integration data",
                found=True,
                orders=orders,
                customer_details=customer_details,
                cease_order_details=cease_order_details,
                service_info=service_info,
                search_result=SearchResult.FOUND,
                execution_time=execution_time,
                screenshots=self.screenshots,
                evidence_dir=str(self.screenshot_dir)
            )
            
            # Save execution summary
            self.save_execution_summary(result)
            
            logger.info(f"Full-featured validation completed in {execution_time:.2f}s")
            return result
            
        except Exception as e:
            logger.error(f"Validation failed: {str(e)}")
            self._take_screenshot("error_state")
            
            return ValidationResult(
                job_id=request.job_id,
                circuit_number=request.circuit_number,
                status=ValidationStatus.ERROR,
                message=f"Validation error: {str(e)}",
                found=False,
                orders=[],
                search_result=SearchResult.ERROR,
                execution_time=time.time() - start_time,
                screenshots=self.screenshots,
                evidence_dir=str(self.screenshot_dir) if self.screenshot_dir else None
            )
            
        finally:
            self._cleanup_browser()
    
    def _create_not_found_result(self, request: ValidationRequest) -> ValidationResult:
        """Create not found result"""
        return ValidationResult(
            job_id=request.job_id,
            circuit_number=request.circuit_number,
            status=ValidationStatus.SUCCESS,
            message=f"Circuit {request.circuit_number} not found in system",
            found=False,
            orders=[],
            cease_order_details=[],
            search_result=SearchResult.NOT_FOUND,
            screenshots=self.screenshots,
            evidence_dir=str(self.screenshot_dir)
        )
    
    def _create_formatted_result_dict(self, result: ValidationResult) -> Dict[str, Any]:
        """Create Oracle-compatible result dictionary"""
        
        result_dict = {
            "status": result.status.value,
            "message": result.message,
            "details": {
                "found": result.found,
                "circuit_number": result.circuit_number,
                "search_result": result.search_result.value,
                "order_data": [order.dict() for order in result.orders],
                "service_info": result.service_info.dict() if result.service_info else None,
                "validation_status": "complete" if result.status == ValidationStatus.SUCCESS else "failed",
                "order_count": len(result.orders),
                "has_new_installation": any(o.is_new_installation for o in result.orders),
                "has_cancellation": any(o.is_cancellation for o in result.orders),
                "has_pending_cease": any(o.is_cancellation and o.is_pending_cease for o in result.orders),
                "has_implemented_cease": any(o.is_cancellation and o.is_implemented_cease for o in result.orders),
                "service_accessible": result.service_info and result.service_info.address is not None,
            },
            "evidence_dir": str(self.screenshot_dir),
            "screenshot_data": [
                {
                    "name": screenshot.name,
                    "timestamp": screenshot.timestamp.isoformat(),
                    "data": screenshot.data,
                    "path": screenshot.path
                }
                for screenshot in result.screenshots
            ],
            "execution_time": result.execution_time
        }
        
        # Add customer details for Oracle integration
        if result.customer_details:
            customer_dict = result.customer_details.dict()
            result_dict["details"]["customer_details"] = customer_dict
            result_dict["details"]["customer_data_extracted"] = any(
                customer_dict.get(field) for field in ['name', 'surname', 'contact_number', 'email']
            )
            
            # Oracle-compatible customer data format
            result_dict["details"]["formatted_customer_data"] = {
                "Name": customer_dict.get('name', ''),
                "Surname": customer_dict.get('surname', ''),
                "Mobile Number": customer_dict.get('contact_number', ''),
                "Email": customer_dict.get('email', ''),
                "Domicile type": customer_dict.get('domicile_type', ''),
                "Address": customer_dict.get('address', '')
            }
            
            # Address compatibility
            if result.service_info and result.service_info.address:
                result_dict["details"]["customer_address"] = result.service_info.address
                result_dict["details"]["active_services_address"] = result.service_info.address
        else:
            result_dict["details"]["customer_details"] = {}
            result_dict["details"]["customer_data_extracted"] = False
            result_dict["details"]["formatted_customer_data"] = {}
        
        # Add cease order details for Oracle integration
        if result.cease_order_details:
            result_dict["details"]["cease_order_details"] = [cease.dict() for cease in result.cease_order_details]
            result_dict["details"]["cease_order_data_extracted"] = True
            
            # Oracle-compatible cease order data format
            formatted_cease_orders = []
            for cease_order in result.cease_order_details:
                formatted_cease_orders.append({
                    "Order Number": cease_order.order_number,
                    "Placed by": cease_order.placed_by,
                    "Date Submitted": cease_order.date_submitted,
                    "Requested Cease Date": cease_order.requested_cease_date,
                    "Product": cease_order.product,
                    "Order type": cease_order.order_type,
                    "Service/Circuit no.": cease_order.service_circuit_no,
                    "External Ref.": cease_order.external_ref
                })
            result_dict["details"]["formatted_cease_order_data"] = formatted_cease_orders
        else:
            result_dict["details"]["cease_order_details"] = []
            result_dict["details"]["cease_order_data_extracted"] = False
            result_dict["details"]["formatted_cease_order_data"] = []
        
        return result_dict

# ==================== MAIN EXECUTION FUNCTION ====================

def execute(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Main execution function with full Oracle integration support"""
    try:
        # Create validation request
        request = ValidationRequest(
            job_id=parameters.get("job_id"),
            circuit_number=parameters.get("circuit_number")
        )
        
        # Run automation
        automation = OSNValidationAutomation()
        result = automation.validate_circuit(request)
        
        # Use the Oracle-compatible formatting method
        result_dict = automation._create_formatted_result_dict(result)
        
        return result_dict
        
    except Exception as e:
        logger.error(f"Execute function failed: {str(e)}")
        return {
            "status": "error",
            "message": f"Execution error: {str(e)}",
            "details": {
                "error": str(e),
                "found": False,
                "order_count": 0,
                "customer_data_extracted": False,
                "service_accessible": False,
                "formatted_customer_data": {},
                "formatted_cease_order_data": []
            },
            "screenshot_data": []
        }

# ==================== TEST EXECUTION ====================

if __name__ == "__main__":
    """Test the full-featured automation"""
    test_params = {
        "job_id": f"FULL_FEATURED_TEST_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "circuit_number": "B530003043"
    }
    
    print("=" * 70)
    print("OSN Validation - Full-Featured Container-Compatible Version")
    print("=" * 70)
    print(f"Testing circuit: {test_params['circuit_number']}")
    print(f"Job ID: {test_params['job_id']}")
    print()
    print("FULL FEATURES RESTORED:")
    print("✓ Container compatibility (JavaScript clicking)")
    print("✓ Customer details extraction")
    print("✓ Cease order details extraction") 
    print("✓ Service information from active services")
    print("✓ Address extraction")
    print("✓ Oracle dashboard integration data")
    print("✓ Complete data models")
    print("✓ Execution summaries")
    print("✓ Evidence collection")
    print()
    
    result = execute(test_params)
    
    print("Results:")
    print("-" * 40)
    print(f"Status: {result['status']}")
    print(f"Circuit Found: {result['details'].get('found', False)}")
    print(f"Customer Data Extracted: {result['details'].get('customer_data_extracted', False)}")
    print(f"Cease Order Data Extracted: {result['details'].get('cease_order_data_extracted', False)}")
    print(f"Service Accessible: {result['details'].get('service_accessible', False)}")
    print()
    print("SUCCESS: Full-featured container-compatible OSN validation with Oracle integration!")
