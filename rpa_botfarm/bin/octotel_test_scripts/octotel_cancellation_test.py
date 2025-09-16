#!/usr/bin/env python3
"""
Simple test script for Octotel cancellation that shows callbacks
"""
import argparse
import json
import logging
import threading
import time
import uuid
import sys
from datetime import datetime
import http.server
import socketserver
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("octotel-cancellation-test")

# ANSI colors for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

# Global storage for callbacks
callbacks = []

class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for callback requests."""
    
    def log_message(self, format, *args):
        """Override to use our logger instead of stderr."""
        logger.debug("%s - %s", self.address_string(), format % args)
    
    def do_POST(self):
        """Handle POST requests with maximum robustness."""
        try:
            # Always respond with success first to avoid connection issues
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {"status": "success", "message": "Callback received"}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            
            # Now process the data without risking response errors
            now = datetime.now()
            timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
            
            # Get raw data first
            content_length = int(self.headers.get('Content-Length', 0))
            raw_data = self.rfile.read(content_length) if content_length > 0 else b''
            raw_text = raw_data.decode('utf-8', errors='replace')
            
            # Display the raw data header
            print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 80}{Colors.END}")
            print(f"{Colors.BOLD}{Colors.CYAN}= CALLBACK RECEIVED @ {timestamp}{Colors.END}")
            print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 80}{Colors.END}")
            
            # Try to parse as JSON, but continue even if it fails
            parsed_data = {}
            try:
                if raw_text:
                    parsed_data = json.loads(raw_text)
                    logger.info("Successfully parsed callback as JSON")
            except Exception as json_err:
                logger.warning(f"Could not parse as JSON, treating as raw text: {str(json_err)}")
                # Create a simple structure for raw text
                parsed_data = {
                    "RAW_DATA": raw_text[:500] + ("..." if len(raw_text) > 500 else "")
                }
            
            # Store callback record with whatever we have
            callback_record = {
                "time": timestamp,
                "data": parsed_data,
                "raw_text": raw_text
            }
            
            # Add to in-memory storage
            callbacks.append(callback_record)
            
            # Display formatted data
            # Extract key fields
            job_id = parsed_data.get("JOB_ID", "N/A")
            provider = parsed_data.get("FNO", "N/A")
            status = parsed_data.get("STATUS", "N/A")
            status_dt = parsed_data.get("STATUS_DT", "N/A")
            
            # Determine status color
            status_color = Colors.BLUE
            if "Cancelled" in status or "Success" in status:
                status_color = Colors.GREEN
            elif "Error" in status or "Failed" in status or "Not Found" in status:
                status_color = Colors.RED
            elif "Pending" in status:
                status_color = Colors.YELLOW
            
            # Display basic info
            print(f"Job ID: {Colors.BOLD}{job_id}{Colors.END}")
            print(f"Provider: {provider}")
            print(f"Status: {status_color}{status}{Colors.END}")
            print(f"Status Date: {status_dt}")
            
            # Process JOB_EVI for Octotel-specific data
            job_evi = parsed_data.get("JOB_EVI", "")
            if job_evi:
                # Try to parse as JSON if it's a string
                if isinstance(job_evi, str):
                    try:
                        job_evi = json.loads(job_evi)
                    except:
                        pass
                
                if isinstance(job_evi, dict):
                    print(f"\n{Colors.BOLD}Job Evidence:{Colors.END}")
                    
                    # Show Octotel cancellation-specific highlights
                    octotel_highlights = [
                        "cancellation_submitted", "release_reference", "cancellation_timestamp",
                        "cancellation_reason", "cancellation_comment", "service_found",
                        "is_active", "change_request_available", "pending_requests_detected",
                        "customer_name", "service_type", "service_address", "current_status"
                    ]
                    
                    # Display highlights first
                    for key in octotel_highlights:
                        if key in job_evi:
                            display_key = key.replace("_", " ").title()
                            value = job_evi[key]
                            if key == "cancellation_submitted":
                                color = Colors.GREEN if value else Colors.RED
                                print(f"  🔸 {Colors.YELLOW}{display_key}{Colors.END}: {color}{value}{Colors.END}")
                            elif key == "release_reference":
                                print(f"  📋 {Colors.YELLOW}{display_key}{Colors.END}: {Colors.BOLD}{value}{Colors.END}")
                            else:
                                print(f"  🔸 {Colors.YELLOW}{display_key}{Colors.END}: {value}")
                    
                    # Count total fields
                    cancellation_fields = [k for k in job_evi.keys() if 'cancellation' in k.lower()]
                    service_fields = [k for k in job_evi.keys() if k.startswith('service_') or k.startswith('customer_')]
                    
                    print(f"\n  📊 Data Summary:")
                    print(f"    - Cancellation fields: {len(cancellation_fields)}")
                    print(f"    - Service fields: {len(service_fields)}")
                    print(f"    - Total fields: {len(job_evi)}")
                    
                    # Show key cancellation indicators
                    submitted = job_evi.get("cancellation_submitted", "N/A")
                    found = job_evi.get("found", "N/A")
                    active = job_evi.get("is_active", "N/A")
                    print(f"    - Service Found: {found}")
                    print(f"    - Service Active: {active}")
                    print(f"    - Cancellation Submitted: {submitted}")
                    
                else:
                    print(f"\n{Colors.BOLD}Job Evidence (raw):{Colors.END}")
                    print(f"  {job_evi}")
            
            # Display footer
            print(f"{Colors.CYAN}{'=' * 80}{Colors.END}")
            
        except Exception as e:
            # Log the error but don't let it affect the response (already sent)
            logger.error(f"Error processing callback: {str(e)}")
            logger.error(sys.exc_info()[2])
            
            # Print something to console so user knows about the error
            print(f"\n{Colors.RED}Error processing callback: {str(e)}{Colors.END}")
            print(f"{Colors.RED}Check log for details{Colors.END}")

def start_callback_server(port=8625):
    """Start a callback server in a separate thread."""
    server = socketserver.TCPServer(("", port), CallbackHandler)
    
    def run_server():
        logger.info(f"Starting callback listener on port {port}")
        server.serve_forever()
    
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    
    return server, thread

def run_octotel_cancellation(orchestrator_url, circuit_number, solution_id=None, requested_date=None):
    """Run an Octotel cancellation job and monitor for completion and callbacks."""
    start_time = datetime.now()
    
    # Generate test ID
    test_id = str(uuid.uuid4())[:8]
    external_job_id = f"OCTOTEL_CANCEL_{test_id}"
    
    # Generate default solution ID if not provided
    if not solution_id:
        solution_id = f"AUTO_{circuit_number}_{test_id}"
        logger.info(f"Generated solution ID: {solution_id}")
    
    logger.info(f"Starting Octotel cancellation for circuit {circuit_number}")
    logger.info(f"External Job ID: {external_job_id}")
    logger.info(f"Solution ID: {solution_id}")
    if requested_date:
        logger.info(f"Requested Date: {requested_date}")
    
    # 1. Create job
    try:
        job_data = {
            "provider": "octotel",
            "action": "cancellation",  # Changed from validation to cancellation
            "parameters": {
                "circuit_number": circuit_number,
                "solution_id": solution_id,
                "external_job_id": external_job_id
            },
            "priority": 5
        }
        
        # Add requested date if provided
        if requested_date:
            job_data["parameters"]["requested_date"] = requested_date
        
        response = requests.post(
            f"{orchestrator_url}/jobs",
            json=job_data
        )
        
        if response.status_code != 200:
            logger.error(f"❌ Job creation failed: {response.status_code}")
            return False
            
        data = response.json()
        job_id = data.get("id")
        logger.info(f"✅ Created job with ID: {job_id}")
        
    except Exception as e:
        logger.error(f"❌ Job creation failed: {str(e)}")
        return False
    
    # 2. Trigger job processing
    try:
        response = requests.post(f"{orchestrator_url}/process")
        if response.status_code == 200:
            logger.info("✅ Triggered job processing")
        else:
            logger.warning(f"⚠️ Process trigger returned: {response.status_code}")
    except Exception as e:
        logger.warning(f"⚠️ Process trigger failed: {str(e)}")
    
    # 3. Monitor job until completion
    completed = False
    max_wait_time = 300  # 5 minutes for cancellation (longer than validation)
    start_monitoring = datetime.now()
    
    logger.info(f"Monitoring job {job_id} until completion (max {max_wait_time}s)...")
    
    callback_received = False
    
    while not completed and (datetime.now() - start_monitoring).total_seconds() < max_wait_time:
        try:
            # Check for callbacks
            if len(callbacks) > 0 and not callback_received:
                callback_received = True
                logger.info("📡 Callback received during job execution")
                
            # Check job status via API
            response = requests.get(f"{orchestrator_url}/jobs/{job_id}")
            
            if response.status_code != 200:
                logger.warning(f"⚠️ Failed to get job status: {response.status_code}")
                time.sleep(5)
                continue
                
            job_data = response.json()
            status = job_data.get("status")
            
            if status in ["completed", "failed", "error"]:
                completed = True
                break
                
            logger.info(f"Job status: {status}")
            time.sleep(5)
            
        except Exception as e:
            logger.warning(f"⚠️ Error checking job status: {str(e)}")
            time.sleep(5)
    
    # If no callback received yet, wait a bit more
    if not callback_received and len(callbacks) == 0:
        logger.info("No callbacks received yet, waiting for callback...")
        time.sleep(10)
    
    if not completed:
        logger.error(f"❌ Job did not complete within time limit")
        return False
    
    # 4. Get final result
    try:
        response = requests.get(f"{orchestrator_url}/jobs/{job_id}")
        job_data = response.json()
        status = job_data.get("status")
        result = job_data.get("result", {})
        
        logger.info(f"✅ Job completed with status: {status} in {datetime.now() - start_time}")
        
        # Check for screenshots
        screenshots_response = requests.get(f"{orchestrator_url}/jobs/{job_id}/screenshots")
        if screenshots_response.status_code == 200:
            screenshot_data = screenshots_response.json()
            screenshot_count = screenshot_data.get("screenshot_count", 0)
            logger.info(f"📸 {screenshot_count} screenshots captured")
        
        # Display summary of cancellation results
        if isinstance(result, dict) and "details" in result:
            details = result["details"]
            
            # Summary display
            print(f"\n{Colors.BOLD}{Colors.GREEN}=== Cancellation Results ==={Colors.END}")
            print(f"Job ID: {job_id}")
            print(f"Status: {status}")
            print(f"Provider: octotel")
            print(f"Circuit Number: {circuit_number}")
            print(f"Solution ID: {solution_id}")
            
            # Key cancellation results
            cancellation_submitted = details.get('cancellation_submitted', False)
            service_found = details.get('found', False)
            release_reference = details.get('release_reference', 'N/A')
            
            print(f"\n{Colors.BOLD}Cancellation Status:{Colors.END}")
            submitted_color = Colors.GREEN if cancellation_submitted else Colors.RED
            print(f"  Service Found: {Colors.GREEN if service_found else Colors.RED}{service_found}{Colors.END}")
            print(f"  Cancellation Submitted: {submitted_color}{cancellation_submitted}{Colors.END}")
            print(f"  Release Reference: {Colors.BOLD}{release_reference}{Colors.END}")
            
            # Service details if available
            if service_found:
                service_data = details.get("service_data", {})
                if service_data:
                    print(f"\n{Colors.BOLD}Service Information:{Colors.END}")
                    print(f"  Customer Name: {service_data.get('customer_name', 'N/A')}")
                    print(f"  Service Type: {service_data.get('service_type', 'N/A')}")
                    print(f"  Address: {service_data.get('address', 'N/A')}")
                    print(f"  Status: {service_data.get('status', 'N/A')}")
                    
                    # Change request availability
                    change_available = service_data.get('change_request_available', False)
                    pending_requests = service_data.get('pending_requests_detected', False)
                    
                    print(f"\n{Colors.BOLD}Service Status:{Colors.END}")
                    print(f"  Change Request Available: {Colors.GREEN if change_available else Colors.RED}{change_available}{Colors.END}")
                    print(f"  Pending Requests Detected: {Colors.YELLOW if pending_requests else Colors.GREEN}{pending_requests}{Colors.END}")
            
            # Cancellation details
            cancellation_timestamp = details.get('cancellation_timestamp', 'N/A')
            execution_time = details.get('execution_time', 'N/A')
            
            print(f"\n{Colors.BOLD}Process Details:{Colors.END}")
            print(f"  Cancellation Timestamp: {cancellation_timestamp}")
            print(f"  Execution Time: {execution_time}s" if execution_time != 'N/A' else f"  Execution Time: {execution_time}")
            print(f"  Cancellation Reason: Customer Service ISP")  # Fixed reason from code
            print(f"  Cancellation Comment: Bot cancellation")      # Fixed comment from code
            
            # Validation results if available
            validation_results = details.get('validation_results', {})
            if validation_results:
                print(f"\n{Colors.BOLD}Validation Results:{Colors.END}")
                for key, value in validation_results.items():
                    display_key = key.replace('_', ' ').title()
                    print(f"  {display_key}: {value}")
            
            # Callback summary
            print(f"\n{Colors.BOLD}{Colors.MAGENTA}=== Callback Summary ==={Colors.END}")
            print(f"Callbacks Received: {len(callbacks)}")
            for i, callback in enumerate(callbacks):
                cb_data = callback.get("data", {})
                print(f"\nCallback {i+1} at {callback.get('time', 'unknown')}:")
                print(f"  Status: {cb_data.get('STATUS', 'N/A')}")
                
                # Show a snippet of JOB_EVI
                job_evi = cb_data.get("JOB_EVI", "")
                if job_evi and isinstance(job_evi, str):
                    try:
                        parsed_evi = json.loads(job_evi)
                        evi_keys = list(parsed_evi.keys())
                        if evi_keys:
                            cancellation_keys = [k for k in evi_keys if 'cancellation' in k.lower()]
                            service_keys = [k for k in evi_keys if k.startswith('service_') or k.startswith('customer_')]
                            print(f"  Evidence contains {len(evi_keys)} total fields:")
                            print(f"    - Cancellation-specific: {len(cancellation_keys)}")
                            print(f"    - Service fields: {len(service_keys)}")
                            
                            # Show key cancellation status
                            if 'cancellation_submitted' in parsed_evi:
                                print(f"    - Submitted: {parsed_evi['cancellation_submitted']}")
                            if 'release_reference' in parsed_evi:
                                print(f"    - Reference: {parsed_evi['release_reference']}")
                    except:
                        print(f"  Evidence (unparseable): {job_evi[:50]}...")
        
        return True
            
    except Exception as e:
        logger.error(f"❌ Error getting job result: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Test Octotel Cancellation with Callbacks")
    parser.add_argument("--url", default="http://localhost:8620", help="Orchestrator URL")
    parser.add_argument("--circuit", default="YOUR_CIRCUIT_NUMBER", help="Circuit number to cancel")
    parser.add_argument("--solution-id", help="Solution ID for reference (optional - will auto-generate if not provided)")
    parser.add_argument("--requested-date", help="Requested cancellation date (DD/MM/YYYY)")
    parser.add_argument("--callback-port", type=int, default=8625, help="Port for callback listener")
    
    args = parser.parse_args()
    
    print(f"{Colors.BOLD}{Colors.BLUE}Starting Octotel Cancellation Test with Callbacks...{Colors.END}")
    print(f"{Colors.BOLD}Circuit Number: {args.circuit}{Colors.END}")
    if args.solution_id:
        print(f"{Colors.BOLD}Solution ID: {args.solution_id}{Colors.END}")
    else:
        print(f"{Colors.BOLD}Solution ID: Will auto-generate{Colors.END}")
    print(f"{Colors.BOLD}Orchestrator: {args.url}{Colors.END}")
    print(f"{Colors.BOLD}Callback Port: {args.callback_port}{Colors.END}")
    if args.requested_date:
        print(f"{Colors.BOLD}Requested Date: {args.requested_date}{Colors.END}")
    
    # Check if user needs to set required parameters
    if args.circuit == "YOUR_CIRCUIT_NUMBER":
        print(f"\n{Colors.YELLOW}⚠️ Please provide a circuit number to cancel:{Colors.END}")
        print(f"{Colors.YELLOW}   python test_octotel_cancellation.py --circuit YOUR_ACTUAL_CIRCUIT{Colors.END}")
        print(f"{Colors.YELLOW}   (Solution ID will be auto-generated if not provided){Colors.END}")
        sys.exit(1)
    
    # Start callback server
    try:
        server, server_thread = start_callback_server(args.callback_port)
        logger.info(f"Callback server started on port {args.callback_port}")
        
        # Update orchestrator to use our callback endpoint (optional)
        try:
            response = requests.post(
                f"{args.url}/config/test",
                json={"CALLBACK_ENDPOINT": f"http://localhost:{args.callback_port}"}
            )
            if response.status_code == 200:
                logger.info(f"✅ Temporarily configured orchestrator to send callbacks to port {args.callback_port}")
            else:
                logger.warning(f"⚠️ Could not update callback endpoint: {response.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ Error updating callback endpoint: {str(e)}")
            logger.info("🔧 Make sure your orchestrator config.py has CALLBACK_ENDPOINT set to:")
            logger.info(f"   CALLBACK_ENDPOINT = 'http://localhost:{args.callback_port}'")
    except Exception as e:
        logger.error(f"Error starting callback server: {str(e)}")
        server = None
        logger.warning("Continuing without callback server")
    
    try:
        success = run_octotel_cancellation(args.url, args.circuit, args.solution_id, args.requested_date)
        
        if success:
            print(f"\n{Colors.BOLD}{Colors.GREEN}🎉 Cancellation test completed successfully!{Colors.END}")
            print(f"\n{Colors.BOLD}💡 Monitor the logs in your orchestrator and worker terminals{Colors.END}")
            print(f"{Colors.BOLD}💡 Screenshots are saved in: data/screenshots/job_X/{Colors.END}")
            print(f"\n{Colors.BOLD}{Colors.RED}⚠️ IMPORTANT: This performed an actual cancellation request!{Colors.END}")
            print(f"{Colors.BOLD}{Colors.RED}   Check the Octotel portal to verify the cancellation status.{Colors.END}")
            sys.exit(0)
        else:
            print(f"\n{Colors.BOLD}{Colors.RED}⛔ Cancellation test failed{Colors.END}")
            sys.exit(1)
            
    finally:
        # Shutdown the server if it was started
        if 'server' in locals() and server:
            try:
                server.shutdown()
                logger.info("Callback server shutdown")
            except:
                pass

if __name__ == "__main__":
    main()