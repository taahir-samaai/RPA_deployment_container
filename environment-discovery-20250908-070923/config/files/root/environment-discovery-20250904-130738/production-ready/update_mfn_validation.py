#!/usr/bin/env python3
"""
Script to update MFN validation.py with Cloudflare bypass capabilities
"""

import re
import os
import shutil
from datetime import datetime

def find_validation_file():
    """Find the validation.py file in the project"""
    possible_paths = [
        "rpa_botfarm/automations/mfn/validation.py",
        "automations/mfn/validation.py",
        "rpa_botfarm/mfn/validation.py"
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            print(f"Found validation file at: {path}")
            return path
    
    # If not found, search for it
    for root, dirs, files in os.walk("."):
        for file in files:
            if file == "validation.py" and "mfn" in root:
                full_path = os.path.join(root, file)
                print(f"Found validation file at: {full_path}")
                return full_path
    
    return None

def backup_file(filepath):
    """Create a backup of the original file"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{filepath}.backup_{timestamp}"
    shutil.copy2(filepath, backup_path)
    print(f"Created backup: {backup_path}")
    return backup_path

def update_initialize_driver(content):
    """Replace the initialize_driver method with Cloudflare bypass version"""
    
    pattern = r'def initialize_driver\(self\):.*?(?=\n    def|\n    @|\nclass|\n\n\ndef|\Z)'
    
    new_method = '''def initialize_driver(self):
        """Initialize Chrome driver with Cloudflare bypass optimizations"""
        try:
            if self.driver:
                self.driver.quit()
                
            import platform
            chrome_options = Options()
            
            # Basic Chrome options from Config
            if Config.START_MAXIMIZED:
                chrome_options.add_argument("--start-maximized")
            if Config.NO_SANDBOX:
                chrome_options.add_argument("--no-sandbox")
            if Config.DISABLE_DEV_SHM_USAGE:
                chrome_options.add_argument("--disable-dev-shm-usage")
            
            # CLOUDFLARE BYPASS - CRITICAL ADDITIONS
            chrome_options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            
            # Additional stealth options
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-plugins")
            chrome_options.add_argument("--window-size=1920,1080")
            
            # Handle headless mode
            if Config.HEADLESS:
                logger.info("Running in headless mode")
                chrome_options.add_argument("--headless=new")
            else:
                logger.info("Running in visible mode")
            
            # Use Config for driver path
            driver_path = Config.CHROMEDRIVER_PATH
            logger.info(f"Using ChromeDriver path: {driver_path}")
            
            from selenium.webdriver.chrome.service import Service
            service = Service(executable_path=driver_path)
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # CRITICAL: Remove webdriver property that Cloudflare detects
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            # Set longer timeouts for Cloudflare challenges
            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(10)
            self.driver.set_window_size(1920, 1080)
            
            logger.info(f"Job {self.job_id}: WebDriver initialized with Cloudflare bypass on {platform.system()}")
            return True
            
        except WebDriverException as e:
            logger.error(f"Job {self.job_id}: Failed to initialize WebDriver: {str(e)}")
            logger.error(f"Driver path attempted: {Config.CHROMEDRIVER_PATH}")
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None
            return False'''
    
    new_content = re.sub(pattern, new_method, content, flags=re.DOTALL)
    
    if new_content != content:
        print("Updated initialize_driver method with Cloudflare bypass")
        return new_content
    else:
        print("Could not find initialize_driver method to replace")
        return content

def update_login_method(content):
    """Replace the login method with Cloudflare handling version"""
    
    pattern = r'@retry\(\s*stop=stop_after_attempt\(3\),.*?\ndef login\(self\):.*?return True'
    
    new_method = '''@retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=15),
        retry=retry_if_exception_type((TimeoutException, WebDriverException)),
        before_sleep=before_sleep_log(logger, logging.INFO)
    )
    def login(self):
        """Login with Cloudflare challenge handling"""
        try:
            logger.info(f"Job {self.job_id}: Navigating to MetroFiber portal with Cloudflare handling")
            
            # Navigate to portal
            self.driver.get(self.portal_url)
            time.sleep(3)
            
            # Check if we hit Cloudflare challenge
            page_title = self.driver.title.lower()
            
            if "just a moment" in page_title:
                logger.info(f"Job {self.job_id}: Cloudflare challenge detected, waiting for resolution...")
                self.take_screenshot("cloudflare_challenge_detected")
                
                # Wait up to 30 seconds for Cloudflare to resolve
                max_wait = 30
                waited = 0
                
                while waited < max_wait:
                    time.sleep(2)
                    waited += 2
                    
                    current_title = self.driver.title.lower()
                    
                    if "just a moment" not in current_title:
                        logger.info(f"Job {self.job_id}: Cloudflare challenge resolved after {waited} seconds")
                        self.take_screenshot("cloudflare_challenge_resolved")
                        break
                        
                    logger.info(f"Job {self.job_id}: Still waiting for Cloudflare... ({waited}s/{max_wait}s)")
                
                if waited >= max_wait and "just a moment" in self.driver.title.lower():
                    logger.error(f"Job {self.job_id}: Cloudflare challenge not resolved")
                    raise Exception("Cloudflare challenge not resolved")
            
            # Continue with normal login process
            logger.info(f"Job {self.job_id}: Page loaded successfully, proceeding with login")
            
            # Wait for page to be fully loaded
            wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            time.sleep(5)
            
            # Find login elements
            username_input = wait.until(EC.element_to_be_clickable((By.ID, "username")))
            password_input = self.driver.find_element(By.ID, "password")
            login_button = self.driver.find_element(By.CLASS_NAME, "btnLogin")
            
            # Enter credentials with human-like timing
            username_input.clear()
            time.sleep(0.5)
            username_input.send_keys(self.email)
            time.sleep(0.5)
            password_input.clear()
            time.sleep(0.5)
            password_input.send_keys(self.password)
            
            # Take screenshot before login
            self.take_screenshot("pre_login")
            time.sleep(1)
            
            # Click login
            login_button.click()
            time.sleep(5)
            
            # Verify successful login
            wait.until(EC.presence_of_element_located((By.XPATH, "//a[@href='customers.php']")))
            logger.info(f"Job {self.job_id}: Successfully logged in to MetroFiber portal")
            
            # Take screenshot after login
            self.take_screenshot("post_login")
            return True
            
        except Exception as e:
            logger.error(f"Job {self.job_id}: Login failed: {str(e)}")
            self.take_screenshot("login_error")
            raise'''
    
    new_content = re.sub(pattern, new_method, content, flags=re.DOTALL)
    
    if new_content != content:
        print("Updated login method with Cloudflare handling")
        return new_content
    else:
        print("Could not find login method to replace")
        return content

def main():
    """Main function to update the validation.py file"""
    
    # Find the validation file
    validation_file = find_validation_file()
    
    if not validation_file:
        print("Error: Could not find MFN validation.py file")
        print("Searched for: automations/mfn/validation.py")
        return False
    
    print(f"Updating {validation_file} with Cloudflare bypass...")
    
    try:
        # Create backup
        backup_path = backup_file(validation_file)
        
        # Read the current file
        with open(validation_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Apply updates
        content = update_initialize_driver(content)
        content = update_login_method(content)
        
        # Write the updated file
        with open(validation_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"Updated {validation_file}")
        print(f"Backup saved as: {backup_path}")
        print("")
        print("Summary of changes:")
        print("  - Added Cloudflare bypass Chrome options")
        print("  - Added webdriver property removal")
        print("  - Added Cloudflare challenge detection")
        print("  - Added human-like login timing")
        print("")
        print("Next steps:")
        print("  1. Rebuild containers: podman build -t localhost/rpa-worker:latest -f containers/worker/Containerfile .")
        print("  2. Restart workers: ./scripts/start-system.sh")
        
        return True
        
    except Exception as e:
        print(f"Error updating file: {str(e)}")
        return False

if __name__ == "__main__":
    main()
