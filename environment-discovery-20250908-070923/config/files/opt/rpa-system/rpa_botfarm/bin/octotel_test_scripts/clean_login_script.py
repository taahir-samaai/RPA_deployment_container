#!/usr/bin/env python3
"""
TOTP Login Script for Octotel Periscope using Selenium
Clean version with only essential functionality
Modified to work without webdriver_manager, similar to validation script
"""

import os
import time
import pyotp
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException

# Try to import config, fallback to environment variable or default path
try:
    from config import Config
    CHROMEDRIVER_PATH = Config.CHROMEDRIVER_PATH
except ImportError:
    # Fallback to environment variable or common paths
    CHROMEDRIVER_PATH = os.getenv('CHROMEDRIVER_PATH', '/usr/local/bin/chromedriver')
    print(f"Using chromedriver path: {CHROMEDRIVER_PATH}")

class TOTPLogin:
    def __init__(self, totp_secret, headless=False):
        """
        Initialize the TOTP login automation
        
        Args:
            totp_secret (str): The TOTP secret key (base32 encoded)
            headless (bool): Whether to run browser in headless mode
        """
        self.totp_secret = totp_secret
        self.totp = pyotp.TOTP(totp_secret)
        self.driver = None
        self.headless = headless
    
    def setup_driver(self):
        """Setup Chrome WebDriver with options using local chromedriver"""
        print("Setting up Chrome WebDriver...")
        options = Options()
        
        # Headless configuration
        if self.headless:
            options.add_argument('--headless=new')
            print("Running Chrome in HEADLESS mode")
        else:
            print("Running Chrome in VISIBLE mode")
        
        # Standard Chrome options
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-web-security')
        options.add_argument('--allow-running-insecure-content')
        options.add_argument('--incognito')
        
        # Anti-detection options
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        try:
            # Use local chromedriver path
            service = Service(executable_path=CHROMEDRIVER_PATH)
            self.driver = webdriver.Chrome(service=service, options=options)
            
            # Anti-detection script
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            if not self.headless:
                self.driver.maximize_window()
                
            self.driver.set_page_load_timeout(30)
            self.driver.implicitly_wait(5)
            
            print("ChromeDriver setup successful!")
        except Exception as e:
            print(f"Error setting up ChromeDriver: {e}")
            print(f"Make sure chromedriver is installed at: {CHROMEDRIVER_PATH}")
            print("Or set CHROMEDRIVER_PATH environment variable to the correct path")
            raise
        
    def generate_totp_code(self):
        """Generate current TOTP code"""
        return self.totp.now()
    
    def login(self, username, password):
        """
        Perform login with TOTP for Octotel Periscope
        
        Args:
            username (str): Username/email for login
            password (str): Password for login
        """
        try:
            # Navigate to Periscope
            print("Navigating to Periscope...")
            self.driver.get("https://periscope.octotel.co.za")
            
            # Wait for page to load
            time.sleep(3)
            
            # Find and click login button
            print("Clicking login button...")
            wait = WebDriverWait(self.driver, 15)
            login_btn = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//a[contains(text(), 'Login') or contains(text(), 'login') or contains(text(), 'Sign in') or contains(text(), 'sign in')]"
            )))
            login_btn.click()
            
            # Wait for login page to load
            time.sleep(3)
            
            # Fill login form using JavaScript (most reliable method)
            print("Entering credentials...")
            
            # Enter username
            js_script = f"""
            var usernameField = document.getElementById('signInFormUsername');
            if (usernameField) {{
                usernameField.focus();
                usernameField.value = '';
                usernameField.value = '{username}';
            }}
            """
            self.driver.execute_script(js_script)
            
            # Enter password
            js_script = f"""
            var passwordField = document.getElementById('signInFormPassword');
            if (passwordField) {{
                passwordField.focus();
                passwordField.value = '';
                passwordField.value = '{password}';
            }}
            """
            self.driver.execute_script(js_script)
            
            # Submit login form
            js_script = """
            var submitBtn = document.querySelector('input[name="signInSubmitButton"]');
            if (submitBtn) {
                submitBtn.click();
            }
            """
            self.driver.execute_script(js_script)
            print("Submitted login credentials")
            
            # Wait for MFA page
            time.sleep(5)
            
            # Handle TOTP
            return self.handle_totp()
                
        except Exception as e:
            print(f"Login failed with error: {str(e)}")
            return False
    
    def handle_totp(self):
        """Handle TOTP authentication"""
        print("Handling TOTP authentication...")
        try:
            # Generate TOTP code
            totp_code = self.generate_totp_code()
            print(f"Generated TOTP code: {totp_code}")
            
            # Enter TOTP code
            wait = WebDriverWait(self.driver, 15)
            totp_element = wait.until(
                EC.presence_of_element_located((By.ID, "totpCodeInput"))
            )
            totp_element.clear()
            totp_element.send_keys(totp_code)
            print("Entered TOTP code")
            
            # Submit TOTP
            submit_btn = wait.until(EC.element_to_be_clickable((By.ID, "signInButton")))
            submit_btn.click()
            print("Submitted TOTP code")
            
            # Wait for successful login
            time.sleep(5)
            return True
            
        except Exception as e:
            print(f"TOTP authentication failed: {e}")
            return False
    
    def close(self):
        """Close the browser"""
        if self.driver:
            self.driver.quit()

def main():
    """
    Main function to run Octotel login automation
    """
    # Configuration - Update with your actual values
    TOTP_SECRET = "TRJUWXQNL36OBI574QTZFZMONEWBQI557ICGFNZ5YIFLV3WWEZSQ===="  # Replace with your actual TOTP secret
    USERNAME = "vcappont2.bot@vcontractor.co.za"  # Replace with your actual username
    PASSWORD = "VC_Ont_7689#"  # Replace with your actual password
    
    # Validate configuration
    if TOTP_SECRET == "YOUR_TOTP_SECRET_HERE":
        print("ERROR: Please update TOTP_SECRET with your actual secret!")
        return
    
    if USERNAME == "your_username@example.com":
        print("ERROR: Please update USERNAME with your actual username!")
        return
    
    if PASSWORD == "your_password":
        print("ERROR: Please update PASSWORD with your actual password!")
        return
    
    # Check if chromedriver exists
    if not os.path.exists(CHROMEDRIVER_PATH):
        print(f"ERROR: Chromedriver not found at {CHROMEDRIVER_PATH}")
        print("Please install chromedriver or set CHROMEDRIVER_PATH environment variable")
        print("Download from: https://chromedriver.chromium.org/")
        return
    
    # Create login instance
    login_bot = TOTPLogin(TOTP_SECRET, headless=False)
    
    try:
        # Setup browser
        login_bot.setup_driver()
        
        # Perform login
        success = login_bot.login(USERNAME, PASSWORD)
        
        if success:
            print("\n=== LOGIN SUCCESSFUL ===")
            print("You're now logged into Periscope!")
            print("Browser will stay open - close it manually when done, or press Ctrl+C to close via script.")
            
            # Keep browser open indefinitely
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nClosing browser...")
                login_bot.close()
        else:
            print("\nLogin process failed!")
            login_bot.close()
            
    except KeyboardInterrupt:
        print("\nScript interrupted by user")
        login_bot.close()
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        login_bot.close()

if __name__ == "__main__":
    main()