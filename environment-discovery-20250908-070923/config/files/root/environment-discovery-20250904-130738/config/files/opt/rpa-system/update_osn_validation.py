#!/usr/bin/env python3
"""
Script to update OSN validation.py with proper login handling for Microsoft B2C redirect
"""

import re
import os
import shutil
from datetime import datetime

def backup_file(filepath):
    """Create a backup of the original file"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{filepath}.backup_{timestamp}"
    shutil.copy2(filepath, backup_path)
    print(f"✅ Created backup: {backup_path}")
    return backup_path

def update_login_method(content):
    """Replace the login method with proper B2C handling"""
    
    # Pattern to match the login method
    pattern = r'def _login\(self\):\s*""".*?"""\s*try:.*?except Exception as e:\s*self\.logger\.error\(f"Login failed: {str\(e\)}"\)\s*raise'
    
    # New login method with proper B2C handling
    new_method = '''def _login(self):
        """Perform login with proper waits for B2C redirect"""
        try:
            self.driver.get("https://partners.openserve.co.za/login")
            
            # Wait for redirect to B2C login page
            WebDriverWait(self.driver, 30).until(
                EC.url_contains("b2clogin.com")
            )
            
            # Wait for email field to be clickable
            email_input = WebDriverWait(self.driver, 30).until(
                EC.element_to_be_clickable((By.ID, "email"))
            )
            email_input.clear()
            email_input.send_keys(Config.OSEMAIL)
            
            # Wait for password field to be clickable
            password_input = WebDriverWait(self.driver, 30).until(
                EC.element_to_be_clickable((By.ID, "password"))
            )
            password_input.clear()
            password_input.send_keys(Config.OSPASSWORD)
            
            # Wait for login button to be clickable
            login_button = WebDriverWait(self.driver, 30).until(
                EC.element_to_be_clickable((By.ID, "next"))
            )
            login_button.click()
            
            # Wait for redirect back to partners.openserve.co.za after successful login
            WebDriverWait(self.driver, 30).until(
                EC.url_contains("partners.openserve.co.za")
            )
            
            # Wait for the navigation element to confirm successful login
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.ID, "navOrders"))
            )
            
            self.logger.info("Login successful")
            
        except Exception as e:
            self.logger.error(f"Login failed: {str(e)}")
            raise'''
    
    # Replace the method
    new_content = re.sub(pattern, new_method, content, flags=re.DOTALL)
    
    if new_content != content:
        print("✅ Updated login method with B2C redirect handling")
        return new_content
    else:
        print("⚠️  Could not find login method to replace")
        return content

def update_setup_browser(content):
    """Update the browser setup with proper options"""
    
    # Pattern to match the _setup_browser method
    pattern = r'def _setup_browser\(self, job_id: str\):\s*""".*?"""\s*# Chrome options.*?self\.driver\.set_page_load_timeout\(15\)\s*self\.driver\.implicitly_wait\(3\)'
    
    # New setup browser method
    new_method = '''def _setup_browser(self, job_id: str):
        """Setup browser and evidence directory - USING CONFIG ONLY"""
        self.screenshot_dir = Path(Config.get_job_screenshot_dir(job_id))
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.execution_summary_path = Config.get_execution_summary_path(job_id)
        
        # Chrome options
        options = ChromeOptions()
        
        # USE CONFIG INSTEAD OF os.getenv()
        if Config.NO_SANDBOX:
            options.add_argument('--no-sandbox')
        if Config.DISABLE_DEV_SHM_USAGE:
            options.add_argument('--disable-dev-shm-usage')
        
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        # Handle headless mode - USE CONFIG
        if Config.HEADLESS:
            logger.info("Running in headless mode")
            options.add_argument("--headless=new")
        else:
            logger.info("Running in visible mode")

        # Create driver
        from selenium.webdriver.chrome.service import Service
        service = Service(executable_path=Config.CHROMEDRIVER_PATH)
        self.driver = webdriver.Chrome(service=service, options=options)
        
        if Config.START_MAXIMIZED:
            self.driver.maximize_window()
            
        self.driver.set_page_load_timeout(30)
        self.driver.implicitly_wait(10)
        
        # Remove webdriver property to avoid detection
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")'''
    
    # Replace the method
    new_content = re.sub(pattern, new_method, content, flags=re.DOTALL)
    
    if new_content != content:
        print("✅ Updated browser setup method")
        return new_content
    else:
        print("⚠️  Could not find setup browser method to replace")
        return content

def add_import_if_missing(content, import_statement):
    """Add an import statement if it's missing"""
    if import_statement not in content:
        # Find a good place to add the import (after existing imports)
        lines = content.split('\n')
        insert_index = 0
        
        for i, line in enumerate(lines):
            if line.strip().startswith('import ') or line.strip().startswith('from '):
                insert_index = i + 1
            elif line.strip() and not line.startswith('#') and not line.startswith('"""'):
                break
        
        lines.insert(insert_index, import_statement)
        content = '\n'.join(lines)
        print(f"✅ Added import: {import_statement}")
    
    return content

def main():
    """Main function to update the validation.py file"""
    
    # Path to the validation.py file
    validation_file = "rpa_botfarm/automations/osn/validation.py"
    
    # Check if file exists
    if not os.path.exists(validation_file):
        print(f"❌ Error: {validation_file} not found")
        print("Make sure you're running this script from the project root directory")
        return False
    
    print(f"🔄 Updating {validation_file} with B2C login fixes...")
    
    try:
        # Create backup
        backup_path = backup_file(validation_file)
        
        # Read the current file
        with open(validation_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print(f"📖 Read {len(content)} characters from {validation_file}")
        
        # Add necessary imports if missing
        content = add_import_if_missing(content, "from selenium.webdriver.support.ui import WebDriverWait")
        content = add_import_if_missing(content, "from selenium.webdriver.support import expected_conditions as EC")
        content = add_import_if_missing(content, "from selenium.webdriver.common.by import By")
        
        # Apply updates
        content = update_setup_browser(content)
        content = update_login_method(content)
        
        # Write the updated file
        with open(validation_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"💾 Updated {validation_file}")
        print(f"📝 Backup saved as: {backup_path}")
        print("")
        print("🎯 Summary of changes made:")
        print("   ✅ Added proper waits for B2C redirect")
        print("   ✅ Added explicit waits for form elements")
        print("   ✅ Added stealth options to avoid detection")
        print("   ✅ Increased timeouts for slower B2C login")
        print("")
        print("🚀 Next steps:")
        print("   1. Rebuild containers: podman build -t localhost/rpa-worker:latest -f containers/worker/Containerfile .")
        print("   2. Restart workers: ./scripts/start-system.sh")
        print("   3. Test automation: curl -X POST http://localhost:8621/execute -H 'Content-Type: application/json' -d '{\"job_id\": 9001, \"provider\": \"osn\", \"action\": \"validation\", \"parameters\": {\"circuit_number\": \"B510101157\"}}'")
        
        return True
        
    except Exception as e:
        print(f"❌ Error updating file: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    if success:
        print("\n✅ Update completed successfully!")
    else:
        print("\n❌ Update failed!")
