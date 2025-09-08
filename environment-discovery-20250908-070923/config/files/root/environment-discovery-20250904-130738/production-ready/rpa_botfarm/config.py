"""
Updates for config.py to add Openserve support
Updated comments to reflect circuit_number uniformity across all FNO providers
"""
import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
import platform

# Load environment variables
load_dotenv()

class Config:
    """Configuration settings for the RPA orchestration system."""
    
    # Base data directory
    BASE_DATA_DIR = os.getenv("BASE_DATA_DIR", "./data")
    
    # Server settings
    ORCHESTRATOR_HOST = os.getenv("ORCHESTRATOR_HOST", "127.0.0.1")
    ORCHESTRATOR_PORT = int(os.getenv("ORCHESTRATOR_PORT", "8620"))
    WORKER_HOST = os.getenv("WORKER_HOST", "127.0.0.1")
    WORKER_PORT = int(os.getenv("WORKER_PORT", "8621"))
    DEVELOPMENT_MODE = os.getenv("DEVELOPMENT_MODE", "false").lower() == "true"
    DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
    
    # Database settings
    DB_DIR = os.path.join(BASE_DATA_DIR, "db")
    DB_FILE = os.getenv("DB_FILE", "orchestrator.db")
    DB_PATH = os.path.join(DB_DIR, DB_FILE)
    
    # Evidence settings
    # AUDIT COMPLIANT: Standardized screenshot directory (ALL providers use this)
    SCREENSHOT_DIR = os.path.join(BASE_DATA_DIR, "screenshots")
    SCREENSHOT_RETENTION_DAYS = int(os.getenv("SCREENSHOT_RETENTION_DAYS", "30"))
    
    # Authentication settings
    JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-this-in-production")
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRATION_MINUTES = int(os.getenv("JWT_EXPIRATION_MINUTES", "60"))
    
    # Default admin credentials
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
    
    # Scheduler settings
    JOB_POLL_INTERVAL = int(os.getenv("JOB_POLL_INTERVAL", "30"))  # seconds
    METRICS_INTERVAL = int(os.getenv("METRICS_INTERVAL", "300"))  # seconds
    CLEANUP_HOUR = int(os.getenv("CLEANUP_HOUR", "2"))  # 2 AM
    
    # Worker settings
    MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))
    WORKER_TIMEOUT = int(os.getenv("WORKER_TIMEOUT", "600"))  # seconds
    WORKER_ENDPOINTS = json.loads(os.getenv("WORKER_ENDPOINTS", '["http://localhost:8621/execute"]'))
    AUTHORIZED_WORKER_IPS = json.loads(os.getenv("AUTHORIZED_WORKER_IPS", '["127.0.0.1"]'))
    BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1"))
    
    # Retry settings
    MAX_RETRY_ATTEMPTS = int(os.getenv("MAX_RETRY_ATTEMPTS", "3"))
    RETRY_DELAY = int(os.getenv("RETRY_DELAY", "60"))  # seconds
    
    # Logging settings
    LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO"))
    LOG_DIR = os.path.join(BASE_DATA_DIR, "logs")
    LOG_FILE = os.getenv("LOG_FILE", "orchestrator.log")
    WORKER_LOG_FILE = os.getenv("WORKER_LOG_FILE", "worker.log")
      
   # Automation logging settings (ADD THESE)
    AUTOMATION_LOG_DIR = os.path.join(BASE_DATA_DIR, "logs", "automation")
    MFN_AUTOMATION_LOG_FILE = os.getenv("MFN_AUTOMATION_LOG_FILE", "mfn_automation.log")
    OSN_AUTOMATION_LOG_FILE = os.getenv("OSN_AUTOMATION_LOG_FILE", "osn_automation.log") 
    OCTOTEL_AUTOMATION_LOG_FILE = os.getenv("OCTOTEL_AUTOMATION_LOG_FILE", "octotel_automation.log")
    EVOTEL_AUTOMATION_LOG_FILE = os.getenv("EVOTEL_AUTOMATION_LOG_FILE", "evotel_automation.log")

    # MetroFiber Portal settings
    METROFIBER_URL = os.getenv("METROFIBER_URL", "https://ftth.metrofibre.co.za/")
    EMAIL = os.getenv("EMAIL", "vcappont2.bot@vcontractor.co.za")
    PASSWORD = os.getenv("PASSWORD", "ihOQ01oC$WDIPns")
    
    # Openserve Portal settings
    OPENSERVE_URL = os.getenv("OPENSERVE_URL", "https://partners.openserve.co.za/")
    OSEMAIL = os.getenv("OSEMAIL", os.getenv("EMAIL", "vcappont2.bot@vcontractor.co.za"))
    OSPASSWORD = os.getenv("OSPASSWORD", os.getenv("PASSWORD", "vBDKH$H9Jg"))

    # Octotel Portal settings
    OCTOTEL_URL = os.getenv("OCTOTEL_URL", "https://periscope.octotel.co.za")
    OCTOTEL_USERNAME = os.getenv("OCTOTEL_USERNAME", "vcappont2.bot@vcontractor.co.za")
    OCTOTEL_PASSWORD = os.getenv("OCTOTEL_PASSWORD", "VC_Ont_7689#")
    OCTOTEL_TOTP_SECRET = os.getenv("OCTOTEL_TOTP_SECRET", "TRJUWXQNL36OBI574QTZFZMONEWBQI557ICGFNZ5YIFLV3WWEZSQ====")  # New: TOTP secret
    
    # Octotel-specific timeouts
    OCTOTEL_PAGE_LOAD_TIMEOUT = int(os.getenv("OCTOTEL_PAGE_LOAD_TIMEOUT", "30"))
    OCTOTEL_ELEMENT_TIMEOUT = int(os.getenv("OCTOTEL_ELEMENT_TIMEOUT", "15"))

    # Evotel Portal settings
    # NOTE: Evotel uses circuit_number parameter for uniformity, but internally maps to their serial number field
    EVOTEL_URL = os.getenv("EVOTEL_URL", "https://my.evotel.co.za/Account/Login")
    EVOTEL_EMAIL = os.getenv("EVOTEL_EMAIL", "vcappont2.bot@vcontractor.co.za")
    EVOTEL_PASSWORD = os.getenv("EVOTEL_PASSWORD", "Vodabot#01")

    # Evotel-specific timeouts (matching other providers)
    EVOTEL_PAGE_LOAD_TIMEOUT = int(os.getenv("EVOTEL_PAGE_LOAD_TIMEOUT", "30"))
    EVOTEL_ELEMENT_TIMEOUT = int(os.getenv("EVOTEL_ELEMENT_TIMEOUT", "15"))
    EVOTEL_SEARCH_TIMEOUT = int(os.getenv("EVOTEL_SEARCH_TIMEOUT", "20"))
    EVOTEL_WORK_ORDER_TIMEOUT = int(os.getenv("EVOTEL_WORK_ORDER_TIMEOUT", "25"))

    # Chrome/Selenium settings
    if platform.system() == "Windows":
        CHROMEDRIVER_PATH = os.getenv("CHROMEDRIVER_PATH", ".\\drivers\\chromedriver-win64\\chromedriver.exe")
    else:
        CHROMEDRIVER_PATH = os.getenv("CHROMEDRIVER_PATH", "./drivers/chromedriver-linux64/chromedriver")
    
    HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
    START_MAXIMIZED = os.getenv("START_MAXIMIZED", "true").lower() == "true"
    NO_SANDBOX = os.getenv("NO_SANDBOX", "true").lower() == "true"
    DISABLE_DEV_SHM_USAGE = os.getenv("DISABLE_DEV_SHM_USAGE", "true").lower() == "true"
    
    # External callback settings
    CALLBACK_ENDPOINT = os.getenv("CALLBACK_ENDPOINT", "")
    CALLBACK_INTERVAL = int(os.getenv("CALLBACK_INTERVAL", "300"))  # seconds
    CALLBACK_AUTH_TOKEN = os.getenv("CALLBACK_AUTH_TOKEN", "")
    CALLBACK_TIMEOUT = int(os.getenv("CALLBACK_TIMEOUT", "10"))  # seconds
    
    # SECURITY STUFF
    SSL_CERT_PATH = os.getenv("SSL_CERT_PATH", "")
    SSL_KEY_PATH = os.getenv("SSL_KEY_PATH", "")

    # CORS settings
    CORS_ORIGINS = json.loads(os.getenv("CORS_ORIGINS", '["http://localhost:3000", "http://127.0.0.1:3000"]'))
    CORS_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() == "true"

    # CyberArk settings (for Phase 2)
    CYBERARK_APP_ID = os.getenv("CYBERARK_APP_ID", "")
    CYBERARK_SAFE = os.getenv("CYBERARK_SAFE", "")
    CYBERARK_OBJECT = os.getenv("CYBERARK_OBJECT", "")
    CYBERARK_URL = os.getenv("CYBERARK_URL", "")

    # UPDATED: More aggressive timeout settings to prevent hanging
    SELENIUM_IMPLICIT_WAIT = 3       # Reduced from 5
    SELENIUM_PAGE_LOAD_TIMEOUT = 20  # Reduced from 30
    
    # Privacy/POPIA settings
    DATA_PROTECTION_CONTACT = os.getenv("DATA_PROTECTION_CONTACT", "Place Holder")

    # UPDATED: Retry optimizations  
    MAX_RETRY_ATTEMPTS = 2           # Reduced from 3 - fail faster
    RETRY_DELAY = 15                 # Reduced from 30 - retry sooner
    
    # UPDATED: Wait optimizations for OSN specifically
    WAIT_TIMEOUT = 10               # Reduced from 15 - don't wait so long for elements
    ANGULAR_WAIT = 15               # Reduced from 20 - OSN pages should load faster
    
    # NEW: OSN-specific timeouts
    OSN_PAGE_LOAD_TIMEOUT = 15      # Maximum time to wait for page load
    OSN_ELEMENT_TIMEOUT = 8         # Maximum time to wait for elements
    OSN_SEARCH_TIMEOUT = 10         # Maximum time to wait for search results
    OSN_NO_RESULTS_CHECK_DELAY = 3  # Time to wait before checking for no results
    
    # NEW: Browser cleanup settings
    BROWSER_CLEANUP_TIMEOUT = 5     # Time to wait for browser cleanup
    FORCE_BROWSER_KILL = True       # Whether to force-kill hanging Chrome processes

    # NEW: Health reporting settings
    HEALTH_REPORT_INTERVAL = int(os.getenv("HEALTH_REPORT_INTERVAL", "300"))
    HEALTH_REPORT_ENDPOINT = os.getenv("HEALTH_REPORT_ENDPOINT", "http://your-ords/oggies_log")
    HEALTH_REPORT_ENABLED = os.getenv("HEALTH_REPORT_ENABLED", "true").lower() == "true"

    @classmethod
    def get_evotel_timeouts(cls):
        """Get Evotel-specific timeout configuration"""
        return {
            "page_load": cls.EVOTEL_PAGE_LOAD_TIMEOUT,
            "element_wait": cls.EVOTEL_ELEMENT_TIMEOUT,
            "search_timeout": cls.EVOTEL_SEARCH_TIMEOUT,
            "work_order_timeout": cls.EVOTEL_WORK_ORDER_TIMEOUT,
        }

    @classmethod
    def get_evotel_automation_log_path(cls):
        """Get the full path to the Evotel automation log file."""
        return os.path.join(cls.AUTOMATION_LOG_DIR, cls.EVOTEL_AUTOMATION_LOG_FILE)
    
    @classmethod
    def get_octotel_timeouts(cls):
        """Get Octotel-specific timeout configuration"""
        return {
            "page_load": cls.OCTOTEL_PAGE_LOAD_TIMEOUT,
            "element_wait": cls.OCTOTEL_ELEMENT_TIMEOUT,
        }
    
    @classmethod
    def get_log_path(cls):
        """Get the full path to the orchestrator log file."""
        return os.path.join(cls.LOG_DIR, cls.LOG_FILE)

    @classmethod
    def get_osn_timeouts(cls):
        """Get OSN-specific timeout configuration"""
        return {
            "page_load": cls.OSN_PAGE_LOAD_TIMEOUT,
            "element_wait": cls.OSN_ELEMENT_TIMEOUT,
            "search_timeout": cls.OSN_SEARCH_TIMEOUT,
            "no_results_delay": cls.OSN_NO_RESULTS_CHECK_DELAY,
            "cleanup_timeout": cls.BROWSER_CLEANUP_TIMEOUT
        }

    @classmethod
    def get_worker_log_path(cls):
        """Get the full path to the worker log file."""
        return os.path.join(cls.LOG_DIR, cls.WORKER_LOG_FILE)
    
    @classmethod
    def get_automation_log_path(cls):
        """Get the full path to the automation log file."""
        return os.path.join(cls.AUTOMATION_LOG_DIR, cls.MFN_AUTOMATION_LOG_FILE)
    
    @classmethod
    def get_job_screenshot_dir(cls, job_id):
        """
        AUDIT COMPLIANT: Get job-specific screenshot directory.
        Creates the directory if it doesn't exist.
        
        Args:
            job_id: The job identifier
            
        Returns:
            str: Path to the job screenshot directory
        """
        job_dir = os.path.join(cls.SCREENSHOT_DIR, f"job_{job_id}")
        Path(job_dir).mkdir(parents=True, exist_ok=True)
        return job_dir
    

    @classmethod
    def get_execution_summary_path(cls, job_id):
        """
        AUDIT COMPLIANT: Get path for job execution summary.
        Creates the executions directory if it doesn't exist.
        
        Args:
            job_id: The job identifier
            
        Returns:
            str: Path to the job execution summary file
        """
        executions_dir = os.path.join(cls.LOG_DIR, "executions")
        Path(executions_dir).mkdir(parents=True, exist_ok=True)
        return os.path.join(executions_dir, f"job_{job_id}_execution_summary.txt")
    
    @classmethod
    def setup_logging(cls, name=None):
        """
        Configure logging consistently across all modules.
        
        Args:
            name: Optional module name for the logger
            
        Returns:
            logging.Logger: Configured logger
        """
        # Ensure log directories exist
        Path(cls.LOG_DIR).mkdir(parents=True, exist_ok=True)
        Path(cls.AUTOMATION_LOG_DIR).mkdir(parents=True, exist_ok=True)
        
        # Determine the log file based on the name
        if name and 'worker' in name.lower():
            log_file = cls.get_worker_log_path()
        elif name and ('automation' in name.lower() or 'mfn' in name.lower()):
            log_file = cls.get_automation_log_path()
        elif name and ('automation' in name.lower() or 'osn' in name.lower()):
            log_file = os.path.join(cls.AUTOMATION_LOG_DIR, cls.OSN_AUTOMATION_LOG_FILE)
        else:
            log_file = cls.get_log_path()
        
        # Create a logger with the given name
        logger = logging.getLogger(name or "rpa")
        logger.setLevel(cls.LOG_LEVEL)
        
        # Check if handlers already exist to avoid duplicate handlers
        if not logger.handlers:
            # Add handlers
            file_handler = logging.FileHandler(log_file)
            console_handler = logging.StreamHandler()
            
            # Create formatter
            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            )
            
            # Set formatter for handlers
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            # Add handlers to logger
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)
        
        return logger

    @classmethod
    def setup_directories(cls):
        """Create necessary directories if they don't exist."""
        dirs = [
            cls.BASE_DATA_DIR,
            cls.DB_DIR, 
            cls.SCREENSHOT_DIR,  # Single standardized screenshot directory
            cls.LOG_DIR,
            os.path.join(cls.LOG_DIR, "executions")  # Add executions directory
        ]
        
        created_dirs = {}
        for directory in dirs:
            try:
                Path(directory).mkdir(parents=True, exist_ok=True)
                created_dirs[directory] = True
            except Exception as e:
                print(f"Error creating directory {directory}: {str(e)}")
                created_dirs[directory] = False
        
        return created_dirs
