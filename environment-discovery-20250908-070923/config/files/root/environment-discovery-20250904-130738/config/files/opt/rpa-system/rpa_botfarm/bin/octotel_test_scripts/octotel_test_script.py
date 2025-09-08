#!/usr/bin/env python3
"""
Simple test script for Octotel validation that shows callbacks
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
logger = logging.getLogger("octotel-test")

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
            if "Validated" in status or "Success" in status:
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
                    
                    # Show Octotel-specific highlights
                    octotel_highlights = [
                        "octotel_customer_name", "octotel_service_type", "octotel_service_address",
                        "octotel_current_status", "octotel_has_pending_cancellation", "octotel_completeness_score",
                        "octotel_customer_email_0", "octotel_customer_phone_0", "octotel_line_reference",
                        "octotel_service_uuid_0", "octotel_network_node", "octotel_ont_device"
                    ]
                    
                    # Display highlights first
                    for key in octotel_highlights:
                        if key in job_evi:
                            display_key = key.replace("octotel_", "").replace("_", " ").title()
                            print(f"  🔸 {Colors.YELLOW}{display_key}{Colors.END}: {job_evi[key]}")
                    
                    # Count total fields
                    octotel_fields = [k for k in job_evi.keys() if k.startswith('octotel_')]
                    evidence_fields = [k for k in job_evi.keys() if k.startswith('evidence_')]
                    
                    print(f"\n  📊 Data Summary:")
                    print(f"    - Octotel fields: {len(octotel_fields)}")
                    print(f"    - Evidence fields: {len(evidence_fields)}")
                    print(f"    - Total fields: {len(job_evi)}")
                    
                    # Show change request availability
                    change_request = job_evi.get("evidence_change_request_available", "N/A")
                    pending_requests = job_evi.get("evidence_pending_requests_detected", "N/A")
                    print(f"    - Change Request Available: {change_request}")
                    print(f"    - Pending Requests: {pending_requests}")
                    
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

def run_octotel_validation(orchestrator_url, circuit_number):
    """Run an Octotel validation job and monitor for completion and callbacks."""
    start_time = datetime.now()
    
    # Generate test ID
    test_id = str(uuid.uuid4())[:8]
    external_job_id = f"OCTOTEL_TEST_{test_id}"
    
    logger.info(f"Starting Octotel validation for circuit {circuit_number}")
    logger.info(f"External Job ID: {external_job_id}")
    
    # 1. Create job
    try:
        job_data = {
            "provider": "octotel",
            "action": "validation",
            "parameters": {
                "circuit_number": circuit_number,
                "external_job_id": external_job_id
            },
            "priority": 5
        }
        
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
    max_wait_time = 240  # 4 minutes for Octotel
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
        
        # Display summary of data
        if isinstance(result, dict) and "details" in result:
            details = result["details"]
            
            # Summary display
            print(f"\n{Colors.BOLD}{Colors.GREEN}=== Job Results ==={Colors.END}")
            print(f"Job ID: {job_id}")
            print(f"Status: {status}")
            print(f"Provider: octotel")
            print(f"Circuit Number: {circuit_number}")
            print(f"Service Found: {details.get('found', False)}")
            
            # Show services data if available
            services = details.get("services", [])
            if services:
                primary_service = services[0]
                
                # Service identifiers
                service_identifiers = primary_service.get("service_identifiers", {})
                if service_identifiers:
                    print(f"\n{Colors.BOLD}Service Identifiers:{Colors.END}")
                    print(f"  Line Reference: {service_identifiers.get('line_reference', 'N/A')}")
                    print(f"  Primary ID: {service_identifiers.get('primary_id', 'N/A')}")
                    
                    service_uuids = service_identifiers.get('service_uuid', [])
                    if service_uuids:
                        print(f"  Service UUIDs: {len(service_uuids)} found")
                
                # Customer information
                customer_info = primary_service.get("customer_information", {})
                if customer_info:
                    print(f"\n{Colors.BOLD}Customer Information:{Colors.END}")
                    print(f"  Name: {customer_info.get('name', 'N/A')}")
                    
                    emails = customer_info.get('email', [])
                    if emails:
                        print(f"  Email: {emails[0] if isinstance(emails, list) else emails}")
                    
                    phones = customer_info.get('phone', [])
                    if phones:
                        print(f"  Phone: {phones[0] if isinstance(phones, list) else phones}")
                
                # Service details
                service_details = primary_service.get("service_details", {})
                if service_details:
                    print(f"\n{Colors.BOLD}Service Details:{Colors.END}")
                    print(f"  Type: {service_details.get('type', 'N/A')}")
                    print(f"  Speed Profile: {service_details.get('speed_profile', 'N/A')}")
                    print(f"  Start Date: {service_details.get('start_date', 'N/A')}")
                
                # Technical details
                technical_details = primary_service.get("technical_details", {})
                if technical_details:
                    print(f"\n{Colors.BOLD}Technical Details:{Colors.END}")
                    print(f"  Network Node: {technical_details.get('network_node', 'N/A')}")
                    print(f"  ONT Device: {technical_details.get('ont_device', 'N/A')}")
                
                # Status information
                status_info = primary_service.get("status_information", {})
                if status_info:
                    print(f"\n{Colors.BOLD}Status Information:{Colors.END}")
                    print(f"  Current Status: {status_info.get('current_status', 'N/A')}")
                    print(f"  Pending Cancellation: {status_info.get('has_pending_cancellation', 'N/A')}")
                    print(f"  Change Requests: {status_info.get('has_change_requests', 'N/A')}")
                
                # Data completeness
                data_completeness = primary_service.get("data_completeness", {})
                if data_completeness:
                    overall_score = data_completeness.get("overall_score", 0) * 100
                    print(f"\n{Colors.BOLD}Data Quality:{Colors.END}")
                    print(f"  Completeness Score: {overall_score:.1f}%")
                    print(f"  Has Table Data: {data_completeness.get('has_table_data', False)}")
                    print(f"  Has Sidebar Data: {data_completeness.get('has_sidebar_data', False)}")
            
            # Change request availability
            change_request_available = details.get("change_request_available", False)
            pending_requests = details.get("pending_requests_detected", False)
            
            print(f"\n{Colors.BOLD}Service Status:{Colors.END}")
            print(f"  Change Request Available: {Colors.GREEN if change_request_available else Colors.RED}{change_request_available}{Colors.END}")
            print(f"  Pending Requests Detected: {Colors.YELLOW if pending_requests else Colors.GREEN}{pending_requests}{Colors.END}")
            
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
                            octotel_keys = [k for k in evi_keys if k.startswith('octotel_')]
                            evidence_keys = [k for k in evi_keys if k.startswith('evidence_')]
                            print(f"  Evidence contains {len(evi_keys)} total fields:")
                            print(f"    - Octotel-specific: {len(octotel_keys)}")
                            print(f"    - Evidence fields: {len(evidence_keys)}")
                    except:
                        print(f"  Evidence (unparseable): {job_evi[:50]}...")
        
        return True
            
    except Exception as e:
        logger.error(f"❌ Error getting job result: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Test Octotel Validation with Callbacks")
    parser.add_argument("--url", default="http://localhost:8620", help="Orchestrator URL")
    parser.add_argument("--circuit", default="YOUR_CIRCUIT_NUMBER", help="Circuit number to test")
    parser.add_argument("--callback-port", type=int, default=8625, help="Port for callback listener")
    
    args = parser.parse_args()
    
    print(f"{Colors.BOLD}{Colors.BLUE}Starting Octotel Validation Test with Callbacks...{Colors.END}")
    print(f"{Colors.BOLD}Circuit Number: {args.circuit}{Colors.END}")
    print(f"{Colors.BOLD}Orchestrator: {args.url}{Colors.END}")
    print(f"{Colors.BOLD}Callback Port: {args.callback_port}{Colors.END}")
    
    # Check if user needs to set circuit number
    if args.circuit == "YOUR_CIRCUIT_NUMBER":
        print(f"\n{Colors.YELLOW}⚠️ Please provide a circuit number to test:{Colors.END}")
        print(f"{Colors.YELLOW}   python test_octotel.py --circuit YOUR_ACTUAL_CIRCUIT{Colors.END}")
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
        success = run_octotel_validation(args.url, args.circuit)
        
        if success:
            print(f"\n{Colors.BOLD}{Colors.GREEN}🎉 Test completed successfully!{Colors.END}")
            print(f"\n{Colors.BOLD}💡 Monitor the logs in your orchestrator and worker terminals{Colors.END}")
            print(f"{Colors.BOLD}💡 Screenshots are saved in: data/screenshots/job_X/{Colors.END}")
            sys.exit(0)
        else:
            print(f"\n{Colors.BOLD}{Colors.RED}⛔ Test failed{Colors.END}")
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
