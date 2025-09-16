# MetroFiber RPA Automation Documentation

## Overview

This documentation covers the Robotic Process Automation (RPA) system for the MetroFiber portal, consisting of two primary automation scripts that work in sequence:

1. **Validation Script** (`validation.py`) - Service validation and status checking
2. **Cancellation Script** (`cancellation.py`) - Service cancellation processing

The system uses Selenium WebDriver for browser automation and implements a job-based architecture with comprehensive evidence collection and error handling.

---

## System Architecture

### Architectural Patterns Used

1. **Monolithic Class Design** - Single automation class handles all portal interactions
2. **Inheritance Pattern** - Cancellation class inherits from validation class for code reuse
3. **Multiple Strategy Methods** - Different fallback approaches within methods (not formal Strategy pattern)
4. **Retry Pattern** - Built-in resilience with configurable retry logic using tenacity decorators
5. **Template Method Pattern** - Main workflow methods coordinate sequence of smaller operations

### Key Components

- **Job-based execution** with unique job IDs for tracking and evidence collection
- **Centralized configuration** via Config class for credentials and settings  
- **Monolithic automation classes** - MetroFiberAutomation handles all operations
- **Multiple fallback strategies** - Different approaches within methods for robustness
- **Direct portal interaction** - Methods interact directly with web elements
- **Evidence collection system** - Screenshots and data files for audit trails
- **Retry mechanisms** with exponential backoff using tenacity
- **Comprehensive error handling** with graceful degradation
- **Status determination logic** with granular service state analysis

### Code Organization

```python
# Main Classes
class MetroFiberAutomation:           # Base validation functionality
class MetroFiberAutomation(inherited): # Cancellation extends validation

# Configuration
class Config:                         # Centralized settings and paths

# Execution Interface  
def execute(parameters):              # Standard job execution entry point
```

**Note**: The code uses a practical, monolithic approach rather than formal design patterns. This provides simplicity and maintainability for RPA automation scenarios where the primary concern is reliable portal interaction rather than complex software architecture.

---

## Configuration Requirements

### Environment Variables

```python
# Required configuration
METROFIBER_URL = "https://portal.metrofibre.co.za"
EMAIL = "automation@company.com"
PASSWORD = "secure_password"
CHROMEDRIVER_PATH = "/path/to/chromedriver"
EVIDENCE_DIR = "/path/to/evidence/storage"

# Optional settings
HEADLESS = "true"  # Run in headless mode
WAIT_TIMEOUT = "15"  # Element wait timeout
PAGE_LOAD_TIMEOUT = 15
SELENIUM_IMPLICIT_WAIT = 3
```

### Chrome Driver Requirements

- **Chrome Browser** - Latest stable version recommended
- **ChromeDriver** - Compatible version with installed Chrome
- **System Resources** - Minimum 2GB RAM for browser operations
- **Network Access** - Unrestricted access to portal URLs

### Dependencies

```python
# Core automation
selenium>=4.0.0
tenacity>=8.0.0
pydantic>=1.8.0

# Data processing  
pandas>=1.3.0
python-dateutil>=2.8.0

# Utilities
pathlib
base64
json
logging
traceback
```

---

## Validation Automation (`validation.py`)

### Purpose
The validation script is the **first step** in the workflow that:
- Searches for services in the MetroFiber portal
- Extracts customer and service data
- Determines current service status
- Provides foundation data for cancellation decisions

### Validation Workflow

```mermaid
graph TD
    A[Start Validation] --> B[Login to MetroFiber Portal]
    B --> C[Search in Active Services]
    C --> D{Service Found?}
    D -->|Yes| E[Set location = 'active']
    D -->|No| F[Search in Deactivated Services]
    F --> G{Service Found?}
    G -->|Yes| H[Set location = 'inactive']
    G -->|No| I[Return 'not_found']
    E --> J[Extract Customer Data]
    H --> J
    J --> K[Extract Service Information]
    K --> L[Extract Cancellation Data]
    L --> M[Determine Service Status]
    M --> N{Has Pending Cease?}
    N -->|Yes| O[Set pending_cease_order = True]
    N -->|No| P[Set pending_cease_order = False]
    O --> Q[Generate Validation Results]
    P --> Q
    Q --> R[Collect Evidence]
    R --> S[Take Screenshots]
    S --> T[Return Results]
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `job_id` | string | Yes | Unique job identifier |
| `circuit_number` | string | Yes | Primary identifier for the service (e.g., FTTX047648) |
| `customer_name` | string | No | Customer name for additional search criteria |
| `customer_id` | string | No | Customer ID for search |
| `fsan` | string | No | FSAN identifier for search |

### Class: `MetroFiberAutomation`

#### **Workflow Phases:**

##### **Phase 1: Setup**
Browser initialization and evidence directory creation

`initialize_driver()`
```python
def initialize_driver(self):
```
Chrome WebDriver setup with MetroFiber-optimized configuration:
* **Headless Mode**: Configurable for production vs. debug environments
* **Chrome Options**: Maximized window, no-sandbox, disable dev-shm-usage
* **Service Configuration**: Uses ChromeDriver path from Config
* **Platform Detection**: Handles different OS-specific driver requirements

`take_screenshot(name)`
```python
def take_screenshot(self, name):
```
Evidence collection system initialization:
* **Base64 Encoding**: Screenshots encoded for transmission
* **Job-specific Naming**: Files prefixed with job ID and timestamp
* **Directory Structure**: Evidence stored in centralized job directories
* **Metadata Capture**: Screenshot descriptions and timestamps

##### **Phase 2: Authentication**
Login to MetroFiber portal with retry mechanisms

`login()`
```python
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def login(self):
```
Robust authentication process:
* **Portal Navigation**: Navigate to MetroFiber portal URL
* **Credential Entry**: Fill username and password fields
* **Login Verification**: Wait for post-login elements to confirm success
* **Evidence Capture**: Screenshots before and after login
* **Retry Logic**: Automatic retry on authentication failures

##### **Phase 3: Service Discovery** 
Search in active and deactivated services with fallback strategy

`search_customer(circuit_number, customer_name, customer_id, fsan)`
```python
def search_customer(self, circuit_number="", customer_name="", customer_id="", fsan=""):
```
Multi-stage search implementation:
* **Active Services Search**: Navigate to `/customers.php` and fill search form
* **Search Form Population**: Circuit number, customer name, ID, and FSAN fields
* **Results Validation**: Verify search results contain data
* **Deactivated Fallback**: If not found, search `/inactive_customers.php`
* **Advanced Filtering**: SearchBuilder conditions for deactivated services
* **Location Tracking**: Sets `self.service_location` for status determination

`select_first_result()`
```python
def select_first_result(self):
```
Sophisticated result selection with multiple strategies:
* **Table Detection**: Find results in `#example` table
* **Row Selection**: ActionChains double-click on first result row
* **JavaScript Fallback**: Direct JavaScript click if ActionChains fails
* **Circuit Cell Targeting**: Click specific circuit number cell
* **Nuclear Navigation**: Direct URL navigation as last resort

##### **Phase 4: Data Extraction**
Extract customer and service information using multiple methods

`extract_customer_data()`
```python
def extract_customer_data(self):
```
Multi-strategy data extraction:
* **Form Elements**: Extract from input, select, and textarea elements by ID
* **Table Parsing**: Process table-based layouts for read-only views
* **Text Pattern Matching**: Regex extraction from page source
* **Expiry Date Handling**: Special processing with multiple fallback methods
* **Data Validation**: Verify critical fields (customer, circuit_number) extracted

**Extracted Fields Include:**
```python
{
    "customer": "Customer name", "circuit_number": "Service circuit ID", 
    "area": "Service location", "originalbw": "Bandwidth package",
    "activation": "Activation date", "expiry_date": "Service expiry date",
    "status": "Current status", "fsan": "FSAN identifier",
    "price_mrc": "Monthly recurring charges"
    # ... additional fields
}
```

`extract_deactivated_cancellation_data()` *(for inactive services)*
```python
def extract_deactivated_cancellation_data(self):
```
Specialized deactivated services processing:
* **Table Row Processing**: Extract all rows from deactivated services table
* **Circuit Identification**: Find rows containing circuit numbers
* **Row Highlighting**: Visual identification for screenshots
* **Comprehensive Data Capture**: Store all row data for audit trail
* **Primary Row Selection**: Identify main service record

##### **Phase 5: Status Analysis**
Determine detailed service status for orchestrator decision-making

`extract_detailed_service_status(customer_data, cancellation_data, service_location)`
```python
def extract_detailed_service_status(self, customer_data, cancellation_data, service_location):
```
Advanced status determination logic:
* **Active Service Detection**: Identify fully operational services
* **Pending Cancellation Analysis**: Detect active services with cancellation requests
* **Implemented Cancellation Recognition**: Identify completed cancellations
* **Status Flag Generation**: Set granular flags for orchestrator consumption
* **Date Analysis**: Process expiry dates and cancellation timestamps

**Key Status Flags:**
```python
{
    "service_found": bool, "is_active": bool, "pending_cease_order": bool,
    "cancellation_implementation_date": str, "service_status_type": str
}
```

##### **Phase 6: Evidence Collection**
Screenshots and data file generation

`_collect_evidence(results)`
```python
def _collect_evidence(self, results):
```
Comprehensive evidence compilation:
* **Screenshot Collection**: Gather all job-specific screenshots
* **Data File Assembly**: Compile customer data, history, and cancellation files
* **Base64 Encoding**: Convert screenshots for transmission
* **File Path Management**: Organize evidence in structured directories
* **Results Integration**: Add evidence metadata to job results

**Main Entry Point:**

`validate_service(circuit_number, customer_name="", customer_id="", fsan="")`
```python
def validate_service(self, circuit_number, customer_name="", customer_id="", fsan=""):
```
Orchestrates all validation phases:
* **Phase Coordination**: Execute phases 1-6 in sequence
* **Error Handling**: Continue processing on non-critical failures
* **Results Compilation**: Build comprehensive results structure
* **Cleanup Management**: Ensure browser resources are properly released

**Returns:**
```python
{
    "status": "success|failure|error",
    "message": "Descriptive message",
    "details": {
        "found": bool, "circuit_number": str, "service_location": "active|inactive|not_found",
        "customer_data": {}, "cancellation_data": {}, "pending_cease_order": bool,
        "service_status_type": "active_validated|cancelled_implemented|etc"
    },
    "evidence_dir": str, "evidence": [], "screenshot_data": []
}
```

### Usage Example

```python
from validation import execute

# Define job parameters
parameters = {
    "job_id": "VAL_20250121_001",
    "circuit_number": "FTTX047648", 
    "customer_name": "JAN HARM JANSE VAN RENSBURG",
    "customer_id": "",
    "fsan": ""
}

# Execute validation
result = execute(parameters)

# Check results
if result["status"] == "success":
    details = result["details"]
    if details["found"]:
        print(f"Service found in {details['service_location']} services")
        if details["pending_cease_order"]:
            print("Service has pending cancellation")
    else:
        print("Service not found")
```

---

## Cancellation Automation (`cancellation.py`)

### Purpose
The cancellation script is the **second step** in the workflow that:
- Performs service cancellation operations in MetroFiber portal
- Navigates through the cancellation workflow
- Approves cancellation requests in the orders system
- Updates service status through validation integration

### Cancellation Workflow

```mermaid
graph TD
    A[Start Cancellation] --> B[Login to MetroFiber Portal]
    B --> C[Search Customer]
    C --> D{Customer Found?}
    D -->|No| E[Return Error]
    D -->|Yes| F[Navigate to Service Details]
    F --> G[Click Cancellation Button]
    G --> H[Select Cancellation Reason]
    H --> I{Date Provided?}
    I -->|Yes| J[Set Cancellation Date]
    I -->|No| K[Use Default Date +30 days]
    J --> L[Save Cancellation Request]
    K --> L
    L --> M[Navigate to Orders Page]
    M --> N[Search for Cancellation Request]
    N --> O{Request Found?}
    O -->|No| P[Return Submission Error]
    O -->|Yes| Q[Double-click Cancellation Row]
    Q --> R[Click Accept Button]
    R --> S{Confirmation Dialog?}
    S -->|Yes| T[Handle Dialog/Alert]
    S -->|No| U[Check Success Message]
    T --> U
    U --> V[Run Validation Script]
    V --> W[Return Final Results]
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `job_id` | string | Yes | Unique job identifier for tracking |
| `circuit_number` | string | Yes | Circuit number to be cancelled (e.g., FTTX047648) |
| `customer_name` | string | No | Customer name for search |
| `customer_id` | string | No | Customer ID for search |
| `fsan` | string | No | FSAN identifier |
| `effective_cancellation_date` | string | No | Cancellation date (YYYY-MM-DD format) |

### Class: `MetroFiberAutomation` (inherits from validation)

#### **Workflow Phases:**

##### **Phase 1: Setup**
Browser initialization and evidence directory creation

`initialize_driver()`
```python
def initialize_driver(self):
```
Chrome WebDriver setup with MetroFiber-optimized configuration:
* **Headless Mode**: Configurable for production vs. debug environments
* **Chrome Options**: Maximized window, no-sandbox, disable dev-shm-usage
* **Service Configuration**: Uses ChromeDriver path from Config
* **Platform Detection**: Handles different OS-specific driver requirements

##### **Phase 2: Authentication**
Login to MetroFiber portal

`login()`
```python
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def login(self):
```
Robust authentication process:
* **Portal Navigation**: Navigate to MetroFiber portal URL
* **Credential Entry**: Fill username and password fields  
* **Login Verification**: Wait for post-login elements to confirm success
* **Evidence Capture**: Screenshots before and after login
* **Retry Logic**: Automatic retry on authentication failures

##### **Phase 3: Customer Discovery**
Search and select customer service

`search_customer(circuit_number, customer_name, customer_id, fsan)`
```python
def search_customer(self, circuit_number="", customer_name="", customer_id="", fsan=""):
```
Customer location and selection:
* **Active Services Navigation**: Navigate to `/customers.php`
* **Search Form Population**: Fill circuit number, customer name, ID, and FSAN
* **Search Execution**: Submit search and wait for results
* **Results Validation**: Verify customer found in search results

`select_first_result()`
```python
def select_first_result(self):
```
Customer service selection:
* **Table Row Identification**: Locate first result in `#example` table
* **Double-click Selection**: ActionChains double-click to open customer details
* **JavaScript Fallback**: Direct JavaScript click if ActionChains fails
* **Navigation Verification**: Confirm successful navigation to customer details page

`extract_customer_data()`
```python
def extract_customer_data(self):
```
Extract customer information for cancellation processing:
* **Customer Name Extraction**: Get customer name for later order search
* **Circuit Validation**: Confirm circuit number matches search
* **Service Details**: Extract current service configuration
* **Evidence Creation**: Save customer data to evidence files

##### **Phase 4: Cancellation Request**
Submit cancellation with date and reason

`perform_cancellation(effective_cancellation_date)`
```python
def perform_cancellation(self, effective_cancellation_date=None):
```
Orchestrates core cancellation workflow:
* **Button Detection**: Locate and click cancellation button
* **Reason Selection**: Select cancellation reason from dropdown
* **Date Configuration**: Set cancellation date (default +30 days)
* **Form Submission**: Save cancellation request

`_find_and_click_cancellation_button()`
```python
def _find_and_click_cancellation_button(self):
```
Multi-strategy cancellation button interaction:
* **JavaScript Search**: DOM-based button detection by text content "cancel"
* **XPath Fallback**: Traditional element location methods
* **Click Execution**: JavaScript and Selenium click attempts
* **Evidence Capture**: Screenshots before and after button interaction

`_select_cancellation_reason()`
```python
def _select_cancellation_reason(self):
```
Automated reason selection:
* **Dropdown Detection**: Locate cancellation reason dropdown
* **JavaScript Selection**: Bypass dropdown search with direct JavaScript
* **Event Triggering**: Dispatch change events for form validation
* **Fallback Handling**: Continue processing if dropdown interaction fails

`_set_cancellation_date(effective_date, future_days=30)`
```python
def _set_cancellation_date(self, effective_date=None, future_days=30):
```
Intelligent date field handling:
* **Date Calculation**: Default to 30 days in future if no date provided
* **Readonly Detection**: JavaScript-based readonly field detection  
* **Input Methods**: sendKeys for editable fields, JavaScript for readonly
* **Value Verification**: Confirm date was set correctly

`_save_cancellation_request()`
```python
def _save_cancellation_request(self):
```
Form submission with confirmation handling:
* **Save Button Click**: Locate and click form save button
* **Alert Handling**: Process JavaScript confirmation alerts
* **Success Verification**: Check for successful form submission
* **Error Recovery**: Continue workflow even if confirmation unclear

##### **Phase 5: Order Processing**
Navigate to orders system for approval

`_navigate_to_orders_page()`
```python
def _navigate_to_orders_page(self):
```
Orders system navigation:
* **Direct URL Navigation**: Navigate to `/customer_requests.php`
* **Dynamic Content Wait**: Wait for TableFilter search input to load
* **Search Field Verification**: Confirm `#flt0_example` search input available
* **Page Load Confirmation**: Verify orders page fully loaded

`_search_for_customer_in_orders()`
```python
def _search_for_customer_in_orders(self):
```
Customer search within orders system:
* **Search Input Location**: Find dynamic TableFilter input `#flt0_example`
* **Customer Name Entry**: Type customer name extracted from Phase 3
* **Search Execution**: Submit search with Enter key
* **Results Verification**: Confirm filtered results contain customer

##### **Phase 6: Request Approval**
Approve the cancellation request

`_approve_cancellation_request()`
```python
def _approve_cancellation_request(self):
```
Multi-step approval process:
* **Row Identification**: Find cancellation request row by customer name and type
* **Row Selection**: Scroll to and double-click cancellation request row
* **Detail View**: Navigate to cancellation request detail view
* **Approval Execution**: Click accept/approve button

`_click_accept_cancellation_button()`
```python
def _click_accept_cancellation_button(self):
```
**Nuclear option** for difficult button interactions:
* **Visibility Force**: JavaScript manipulation of element display properties
* **Overlay Removal**: Remove interfering page elements with pointer-events
* **Triple-click Strategy**: JavaScript click, mouse events, and form submission
* **Success Verification**: Check for success messages after interaction

**Nuclear Option Implementation:**
```python
# 1. Force element visibility
self.driver.execute_script("""
    document.getElementById('acceptOrder').style.display = 'block';
    document.getElementById('acceptOrder').style.visibility = 'visible';
    document.getElementById('acceptOrder').style.opacity = '1';
""")

# 2. Remove overlay elements
self.driver.execute_script("""
    [].forEach.call(document.querySelectorAll('div'), function(el) {
        if (window.getComputedStyle(el).pointerEvents === 'none') {
            el.style.pointerEvents = 'auto';
        }
    });
""")

# 3. Multiple click attempts with fallbacks
```

##### **Phase 7: Confirmation Handling**
Process confirmation dialogs and success messages

`_handle_confirmation_dialog()`
```python
def _handle_confirmation_dialog(self):
```
Comprehensive confirmation dialog management:
* **JavaScript Alerts**: Browser alert detection and acceptance
* **HTML Modals**: Modal dialog button clicking with multiple selectors
* **Success Messages**: Text-based confirmation detection in page content
* **Timeout Handling**: Continue processing if no confirmation found

**Dialog Strategies:**
* **Alert Detection**: `EC.alert_is_present()` for JavaScript alerts
* **Modal Buttons**: Multiple XPath selectors for OK/Accept buttons
* **Success Text**: Search for "success", "accepted", "confirmed" messages

##### **Phase 8: Validation Integration**
Execute validation to get updated service status

`validation_execute(parameters)`
```python
# Integration with validation script
validation_result = validation_execute({
    "job_id": self.job_id,
    "circuit_number": circuit_number,
    "customer_name": customer_name,
    "customer_id": customer_id,
    "fsan": fsan
})
```
Post-cancellation validation:
* **Fresh Validation**: Execute complete validation workflow
* **Status Update**: Get current service status after cancellation
* **Data Replacement**: Replace cancellation details with validation data
* **Evidence Integration**: Combine cancellation and validation evidence

**Data Integration:**
```python
# COMPLETELY REPLACE details with validation data
if "details" in validation_result and validation_result["details"]:
    results["details"] = validation_result["details"]
```

##### **Phase 9: Cleanup**
Browser cleanup and evidence collection

`cleanup()`
```python
def cleanup(self):
```
Resource management and evidence compilation:
* **Browser Termination**: Properly close WebDriver instance
* **Temporary File Cleanup**: Remove job-specific temporary files
* **Evidence Organization**: Compile screenshots and data files
* **Memory Release**: Free browser and automation resources

**Main Entry Point:**

`cancel_service(circuit_number, customer_name, customer_id, fsan, effective_cancellation_date)`
```python
def cancel_service(self, circuit_number, customer_name="", customer_id="", fsan="", effective_cancellation_date=None):
```
Orchestrates all cancellation phases:
* **Phase Coordination**: Execute phases 1-9 in sequence
* **Error Recovery**: Continue processing on non-critical failures  
* **Always Execute Validation**: Ensure validation runs regardless of cancellation outcome
* **Results Compilation**: Build comprehensive results with validation data
* **Evidence Management**: Ensure evidence collection in finally block

**Returns:**
```python
{
    "status": "success|failure|error",
    "message": "Descriptive status message", 
    "details": {
        # Validation data replaces cancellation details
        "found": bool, "circuit_number": str, "service_location": str,
        "cancellation_captured_id": str, "pending_cease_order": bool,
        "is_active": bool, "service_status_type": str,
        "customer_data": {}, "cancellation_data": {}
    },
    "evidence_dir": str, "evidence": [], "screenshot_data": []
}
```

### Advanced Features

#### Nuclear Option Button Clicking
For difficult-to-interact elements, the script implements a "nuclear option":

```python
def _click_accept_cancellation_button(self):
    # 1. Force element visibility
    self.driver.execute_script("""
        document.getElementById('acceptOrder').style.display = 'block';
        document.getElementById('acceptOrder').style.visibility = 'visible';
        document.getElementById('acceptOrder').style.opacity = '1';
    """)
    
    # 2. Remove overlay elements that block interaction
    self.driver.execute_script("""
        [].forEach.call(document.querySelectorAll('div'), function(el) {
            if (window.getComputedStyle(el).pointerEvents === 'none') {
                el.style.pointerEvents = 'auto';
            }
        });
    """)
    
    # 3. Triple-click strategy with fallbacks
    # JavaScript click, mouse events, form submission
```

#### Integration with Validation
The cancellation script **always calls validation** at the end:

```python
# At the end of cancel_service method
validation_result = validation_execute({
    "job_id": self.job_id,
    "circuit_number": circuit_number,
    "customer_name": customer_name,
    "customer_id": customer_id,
    "fsan": fsan
})

# COMPLETELY REPLACE details with validation data
if "details" in validation_result and validation_result["details"]:
    results["details"] = validation_result["details"]
```

### Result Structure

```python
{
    "status": "success|failure|error",
    "message": "Descriptive status message",
    "details": {
        # Validation data replaces cancellation details
        "found": bool,
        "circuit_number": str,
        "service_location": str,
        "cancellation_captured_id": str,
        "pending_cease_order": bool,
        "is_active": bool,
        "service_status_type": str,
        "customer_data": {},
        "cancellation_data": {}
    },
    "evidence_dir": str,
    "evidence": [],
    "screenshot_data": []
}
```

### Usage Example

```python
from cancellation import execute

# Define cancellation parameters  
parameters = {
    "job_id": "CXL_20250121_001",
    "circuit_number": "FTTX047648",
    "customer_name": "JAN HARM JANSE VAN RENSBURG", 
    "effective_cancellation_date": "2025-02-15"
}

# Execute cancellation
result = execute(parameters)

# Check results
if result["status"] == "success":
    print("Cancellation completed successfully")
    # Details will contain updated validation data
    details = result["details"]
    if details.get("cancellation_captured_id"):
        print(f"Cancellation ID: {details['cancellation_captured_id']}")
```

---

## Evidence Collection System

Both scripts implement comprehensive evidence collection:

### Screenshot Management
- **Automatic screenshots** at key workflow points
- **Base64 encoding** for easy transmission
- **Timestamped filenames** with job ID prefixes
- **Error state capture** for debugging

### Data Files
Evidence files are stored in job-specific directories:

```
/evidence/
├── JOB_20250121_001/
│   ├── screenshots/
│   │   ├── JOB_20250121_001_pre_login_20250121_143022.png
│   │   ├── JOB_20250121_001_search_results_20250121_143045.png
│   │   ├── JOB_20250121_001_cancellation_complete_20250121_143125.png
│   │   └── JOB_20250121_001_deactivated_row_1_20250121_143150.png
│   ├── customer_data.txt
│   ├── deactivated_data.txt
│   ├── history_data.txt  
│   └── cancellation_captured_id.txt
```

### Evidence Data Structure
```python
{
    "evidence": [
        "/path/to/evidence/customer_data.txt",
        "/path/to/evidence/cancellation_captured_id.txt"
    ],
    "screenshot_data": [
        {
            "name": "active_services_search_results",
            "timestamp": "20250121_143045", 
            "base64_data": "iVBORw0KGgoAAAANSUhEUgAA...",
            "mime_type": "image/png",
            "description": "Screenshot: active_services_search_results"
        }
    ]
}
```

---

## Error Handling & Retry Logic

### Retry Decorators
Both scripts use `tenacity` for robust retry mechanisms:

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((TimeoutException, WebDriverException)),
    before_sleep=before_sleep_log(logger, logging.INFO)
)
def login(self):
    # Login implementation with automatic retry
```

### Error Categories
1. **Authentication Errors** - Invalid credentials, portal access issues
2. **Navigation Errors** - Page not found, access denied
3. **Element Interaction Errors** - Elements not found, not clickable
4. **Data Extraction Errors** - Missing fields, format changes
5. **Network Errors** - Connection timeouts, DNS resolution
6. **TimeoutException**: Element not found within timeout
7. **ElementClickInterceptedException**: Element not clickable due to overlays
8. **WebDriverException**: Browser/driver issues
9. **NoSuchElementException**: Missing page elements

### Graceful Degradation
- Scripts continue processing even if non-critical steps fail
- **Always attempt validation** at the end of cancellation
- Comprehensive error logging with stack traces
- Evidence collection continues regardless of operation success/failure

---

## Status Determination Logic

### Service Status Types

| Status Type | Description | Validation Flags |
|------------|-------------|------------------|
| `active_validated` | Service fully active, no issues | `is_active=True`, `pending_cease_order=False` |
| `active_with_pending_cancellation` | Active but cancellation pending | `is_active=True`, `pending_cease_order=True` |
| `cancelled_implemented` | Cancellation completed | `is_active=False`, `has_cancellation_data=True` |
| `not_found` | Service not found anywhere | `service_found=False` |

### Key Decision Flags

#### `pending_cease_order`
**Critical flag** that indicates cancellation is pending:
- Set when service found in active services AND has expiry date
- Set when service found in active services AND has cancellation data
- Used by orchestrator to determine "Cancellation Pending" status

#### `cancellation_implementation_date`
When cancellation was actually implemented:
- Extracted from deactivated services data
- Used to determine "Already Cancelled" status

#### `service_location`
Where the service was found:
- `"active"`: Found in active services
- `"inactive"`: Found in deactivated services only  
- `"not_found"`: Not found in either location

---

## Integration Patterns

### Job Queue System
Both scripts are designed for integration with job queue systems:

```python
# Execute function interface
def execute(parameters):
    job_id = parameters.get("job_id")
    circuit_number = parameters.get("circuit_number") or parameters.get("order_id")
    # ... process job
    return results
```

### Orchestrator Integration
Results are structured for orchestrator consumption:

```python
# Orchestrator can determine status from validation results
details = validation_result["details"]

if not details["found"]:
    status = "Service Not Found"
elif details["service_location"] == "inactive":
    status = "Already Cancelled" 
elif details["pending_cease_order"]:
    status = "Cancellation Pending"
else:
    status = "Active Service"
```

### Data Pipeline Integration

```python
# Example data processing pipeline
def validate_and_process_circuit(circuit_number):
    # Step 1: Validate circuit
    validation_result = validation.execute({
        "job_id": generate_job_id(),
        "circuit_number": circuit_number
    })
    
    if validation_result["details"]["found"]:
        # Step 2: Process customer data
        customer_data = validation_result["details"]["customer_data"]
        update_customer_database(customer_data)
        
        # Step 3: Check for pending cancellations
        if validation_result["details"]["pending_cease_order"]:
            # Handle pending cancellation logic
            process_pending_cancellation(circuit_number)
    
    return validation_result
```

---

## Performance Considerations

### Optimization Strategies

1. **Browser Reuse** - Maintain browser sessions for batch processing
2. **Parallel Processing** - Multiple circuits with separate browser instances
3. **Caching** - Cache frequently accessed data to reduce portal queries
4. **Resource Management** - Proper cleanup of browser resources

### Scalability Notes

- **Memory Usage** - ~200-300MB per browser instance
- **Processing Time** - 45-90 seconds per circuit (network dependent)
- **Concurrent Limit** - Recommended max 3-4 concurrent browsers for MetroFiber
- **Rate Limiting** - Respect portal rate limits to avoid blocking

---

## Security & Compliance

### Data Protection

- **Credential Security** - Environment-based credential storage
- **Evidence Encryption** - Encrypt screenshot and log data
- **PII Handling** - Secure processing of customer personal information
- **Audit Trails** - Complete operation logging for compliance

### Best Practices

- **Access Control** - Restricted access to automation credentials
- **Evidence Retention** - Configurable retention periods for screenshots
- **Error Logging** - Sanitized logs without sensitive information
- **Compliance Monitoring** - Regular audits of automation activities

---

## Troubleshooting

### Common Issues

#### Element Not Found
- **Symptoms**: `TimeoutException` or `NoSuchElementException`
- **Solutions**: Check selectors, increase timeouts, verify page loading
- **MetroFiber Specific**: Search input `#flt0_example` may load dynamically

#### Click Intercepted  
- **Symptoms**: `ElementClickInterceptedException`
- **Solutions**: Use JavaScript clicks, scroll to element, wait for overlays
- **MetroFiber Specific**: Accept button often blocked by modal overlays

#### Login Failures
- **Symptoms**: Authentication errors
- **Solutions**: Verify credentials, check for CAPTCHA, clear browser data

#### Missing ChromeDriver
- **Symptoms**: `WebDriverException` on initialization
- **Solutions**: Verify ChromeDriver path, check permissions, update driver version

#### Cancellation Button Not Found
```
Error: Could not find cancellation button
Solution: Service may already be cancelled or button text changed
```

#### Orders Page Loading Issues
```
Error: Search field not found in orders page  
Solution: TableFilter JavaScript may not have loaded, increase wait time
```

### Debug Mode
Enable debug mode by setting:
```python
HEADLESS = "false"  # Show browser
logging.basicConfig(level=logging.DEBUG)
```

### Evidence Review
Always review evidence files after job completion:
- Check screenshots for unexpected states
- Verify data extraction accuracy
- Confirm cancellation completion in deactivated services

---

## Best Practices

### Job Execution
1. **Always run validation first** to understand current state
2. **Only run cancellation** if validation indicates service is active
3. **Check validation results** after cancellation for status updates

### Error Handling
1. **Capture screenshots** on errors for debugging
2. **Log comprehensive error details** including stack traces
3. **Continue processing** where possible rather than failing completely

### Evidence Collection
1. **Collect evidence** regardless of success/failure
2. **Use descriptive screenshot names** for easy identification
3. **Store structured data** in text files for analysis

### Browser Management
1. **Use headless mode** for production environments
2. **Configure appropriate timeouts** for MetroFiber's slower page loads
3. **Clean up resources** in finally blocks

---

## MetroFiber-Specific Considerations

### Portal Characteristics
- **Slower Loading**: MetroFiber portal has slower page load times, requiring increased timeouts
- **Dynamic Content**: Uses TableFilter for search functionality that loads asynchronously
- **Modal Dialogs**: Confirmation dialogs may appear as JavaScript alerts or HTML modals
- **Two-Phase Cancellation**: Requires both submission and approval steps

### Search Behavior
- **Active Services**: Standard form-based search with immediate results
- **Deactivated Services**: Advanced SearchBuilder with condition-based filtering
- **Circuit Format**: Uses FTTX prefix followed by numbers (e.g., FTTX047648)

### UI Interactions
- **Cancellation Flow**: Customer details → Cancellation button → Date/Reason → Save → Orders → Approve
- **Evidence Requirements**: Screenshots at each major step for audit compliance
- **Fallback Strategies**: Multiple approaches for clicking difficult elements

---

## Future Enhancements

### Planned Improvements

1. **AI-Powered Element Detection** - Machine learning for dynamic UI changes
2. **Advanced Analytics** - Processing time optimization and success rate tracking
3. **Real-time Monitoring** - Dashboard for automation health and performance
4. **API Integration** - Direct API calls where available to reduce browser automation

### Extension Points

- **Custom Strategy Implementations** - Plugin architecture for specialized handling
- **Additional Portals** - Framework extension for other service provider portals
- **Workflow Integration** - Enhanced orchestration with business process management
- **Reporting Enhancement** - Advanced analytics and business intelligence integration

---

## Support & Maintenance

For technical support, configuration assistance, or reporting issues with the MetroFiber automation scripts, please refer to your internal RPA team documentation or contact your system administrator.

The MetroFiber automation system provides robust service validation and cancellation workflows with:

- **Comprehensive service discovery** across active and deactivated states
- **Reliable cancellation processing** with multiple fallback strategies  
- **Detailed status reporting** for orchestrator decision-making
- **Complete evidence collection** for audit and debugging purposes
- **MetroFiber-specific optimizations** for portal characteristics

The system's retry mechanisms, error handling, and evidence collection make it suitable for production use in enterprise environments.

**Last Updated**: January 2025  
**Version**: 2.0 (MetroFiber Implementation)