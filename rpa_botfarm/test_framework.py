#!/usr/bin/env python3
"""
RPA Testing Framework with Uniform circuit_number Support
=========================================================
Updated testing framework using circuit_number uniformly across ALL FNO providers.

Usage Examples:
    # Basic tests
    python test_framework.py --health
    python test_framework.py --status
    python test_framework.py --callbacks --callback-port 8625

    # Provider tests (ALL now use circuit_number for uniformity)
    python test_framework.py --test-validation --circuit FTTX123456 --provider mfn
    python test_framework.py --test-validation --circuit 48575443D9B290B1 --provider evotel
    python test_framework.py --test-cancellation --circuit 48575443D9B290B1 --provider evotel

    # Load and integration tests
    python test_framework.py --load-test --provider evotel --concurrency 3 --job-count 10
    python test_framework.py --integration --provider evotel --circuit 48575443D9B290B1
    
    # Backward compatibility (deprecated but supported)
    python test_framework.py --test-validation --provider evotel --serial 48575443D9B290B1
"""

import argparse
import concurrent.futures
import http.server
import json
import logging
import os
import random
import socketserver
import string
import sys
import threading
import time
import traceback
import uuid
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

import requests
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=requests.packages.urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

# Global storage
callbacks = []
job_completion_status = {}

class TestLogger:
    def __init__(self, name="rpa-test", level=logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    def header(self, text: str):
        print(f"\n{'=' * 60}")
        print(f"= {text}")
        print(f"{'=' * 60}\n")
    
    def success(self, text: str):
        print(f"✓ {text}")
        self.logger.info(text)
    
    def error(self, text: str):
        print(f"✗ {text}")
        self.logger.error(text)
    
    def info(self, text: str):
        print(f"ℹ {text}")
        self.logger.info(text)
    
    def warning(self, text: str):
        print(f"⚠ {text}")
        self.logger.warning(text)

logger = TestLogger()

class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"callbacks": len(callbacks)}).encode('utf-8'))
    
    def do_POST(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
        
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            raw_data = self.rfile.read(content_length) if content_length > 0 else b''
            raw_text = raw_data.decode('utf-8', errors='replace')
            
            parsed_data = {}
            if raw_text:
                try:
                    parsed_data = json.loads(raw_text)
                except:
                    parsed_data = {"RAW_DATA": raw_text[:500]}
            
            callback_record = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "data": parsed_data
            }
            callbacks.append(callback_record)
            
            # Display callback
            job_id = parsed_data.get("JOB_ID", "N/A")
            provider = parsed_data.get("FNO", "N/A")
            status = parsed_data.get("STATUS", "N/A")
            
            print(f"\nCALLBACK: Job {job_id} ({provider}) -> {status}")
            
            if job_id != "N/A":
                job_completion_status[job_id] = {
                    "status": "completed" if "success" in status.lower() else "failed",
                    "timestamp": callback_record["time"],
                    "provider": provider
                }
                
        except Exception as e:
            logger.error(f"Error processing callback: {str(e)}")

class RpaTestFramework:
    def __init__(self, orchestrator_url="http://localhost:8620", 
                 worker_url="http://localhost:8621", timeout=30):
        self.orchestrator_url = orchestrator_url
        self.worker_url = worker_url
        self.timeout = timeout
        self.callback_server = None
        self.callback_thread = None
        self.jobs_created = []
    
    # Health check
    def check_health(self):
        logger.header("Health Check")
        orchestrator_ok = self._check_service(f"{self.orchestrator_url}/health", "Orchestrator")
        worker_ok = self._check_service(f"{self.worker_url}/health", "Worker")
        return orchestrator_ok and worker_ok
    
    def _check_service(self, url, name):
        try:
            response = requests.get(url, timeout=self.timeout)
            if response.status_code == 200:
                logger.success(f"{name} healthy")
                return True
            else:
                logger.error(f"{name} returned {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Cannot connect to {name}: {str(e)}")
            return False
    
    # Callback listener
    def start_callback_listener(self, port=8625, background=True):
        logger.header(f"Starting Callback Listener on Port {port}")
        try:
            self.callback_server = socketserver.TCPServer(("", port), CallbackHandler)
            
            if background:
                def run_server():
                    self.callback_server.serve_forever()
                self.callback_thread = threading.Thread(target=run_server, daemon=True)
                self.callback_thread.start()
                logger.success(f"Callback listener started on port {port}")
            else:
                logger.info("Press Ctrl+C to stop")
                self.callback_server.serve_forever()
            return True
        except Exception as e:
            logger.error(f"Failed to start callback server: {str(e)}")
            return False
    
    def stop_callback_listener(self):
        if self.callback_server:
            try:
                self.callback_server.shutdown()
                self.callback_server.server_close()
                logger.success("Callback listener stopped")
            except Exception as e:
                logger.error(f"Error stopping callback listener: {str(e)}")
    
    # System status
    def get_system_status(self):
        logger.header("System Status")
        try:
            response = requests.get(f"{self.orchestrator_url}/metrics", timeout=self.timeout)
            if response.status_code != 200:
                logger.error(f"Failed to get metrics: {response.status_code}")
                return False
            
            metrics = response.json()
            current = metrics.get("current", {})
            
            logger.info(f"Status: {current.get('status', 'N/A')}")
            logger.info(f"Queued: {current.get('queued_jobs', 0)}")
            logger.info(f"Running: {current.get('running_jobs', 0)}")
            logger.info(f"Completed: {current.get('completed_jobs', 0)}")
            logger.info(f"Failed: {current.get('failed_jobs', 0)}")
            
            return True
        except Exception as e:
            logger.error(f"Error getting status: {str(e)}")
            return False
    
    # Job testing - UPDATED FOR UNIFORM circuit_number USAGE
    def test_validation(self, circuit_number=None, provider="mfn", monitor=True, serial_number=None):
        logger.header(f"Testing {provider.upper()} Validation")
        
        # UPDATED: ALL providers now use circuit_number for uniformity
        # Handle backward compatibility for serial_number parameter
        if serial_number and not circuit_number:
            logger.warning(f"Using deprecated --serial parameter. Please use --circuit for uniformity.")
            circuit_number = serial_number
        
        if not circuit_number:
            logger.error("Circuit number required for all providers")
            return False
        
        # UNIFORM parameters for ALL providers
        parameters = {
            "circuit_number": circuit_number,  # Uniform parameter name
            "external_job_id": f"TEST_VAL_{uuid.uuid4().hex[:8]}"
        }
        
        logger.info(f"Using circuit number: {circuit_number}")
        if provider == "evotel":
            logger.info("Note: Circuit number will map to Evotel's serial number field internally")
        
        job_id = self._create_job(
            provider=provider,
            action="validation",
            parameters=parameters
        )
        
        if not job_id:
            return False
        
        if monitor:
            return self._monitor_job(job_id, timeout=300)  # Increased timeout for complex providers
        return True
    
    def test_cancellation(self, circuit_number=None, provider="mfn", solution_id=None, 
                         requested_date=None, monitor=True, serial_number=None):
        logger.header(f"Testing {provider.upper()} Cancellation")
        
        # UPDATED: ALL providers now use circuit_number for uniformity
        # Handle backward compatibility for serial_number parameter
        if serial_number and not circuit_number:
            logger.warning(f"Using deprecated --serial parameter. Please use --circuit for uniformity.")
            circuit_number = serial_number
        
        if not circuit_number:
            logger.error("Circuit number required for all providers")
            return False
        
        # UNIFORM parameters for ALL providers
        parameters = {
            "circuit_number": circuit_number,  # Uniform parameter name
            "external_job_id": f"TEST_CAN_{uuid.uuid4().hex[:8]}"
        }
        
        logger.info(f"Using circuit number: {circuit_number}")
        if provider == "evotel":
            logger.info("Note: Circuit number will map to Evotel's serial number field internally")
        
        # Add provider-specific additional parameters
        if solution_id:
            parameters["solution_id"] = solution_id
        if requested_date:
            parameters["requested_date"] = requested_date
        
        job_id = self._create_job(
            provider=provider,
            action="cancellation",
            parameters=parameters
        )
        
        if not job_id:
            return False
        
        if monitor:
            return self._monitor_job(job_id, timeout=300)  # Increased timeout for complex providers
        return True
    
    # Integration test - UPDATED FOR UNIFORM circuit_number USAGE
    def run_integration_test(self, circuit_number=None, provider="mfn", serial_number=None):
        logger.header(f"Integration Test: {provider.upper()}")
        
        # Handle backward compatibility
        if serial_number and not circuit_number:
            logger.warning(f"Using deprecated --serial parameter. Please use --circuit for uniformity.")
            circuit_number = serial_number
        
        if not circuit_number:
            logger.error("Circuit number required for integration test")
            return False
        
        logger.info("Phase 1: Initial Validation")
        if not self.test_validation(circuit_number, provider):
            return False
        
        time.sleep(5)  # Wait between phases
        
        logger.info("Phase 2: Cancellation")
        solution_id = f"INTEG_{uuid.uuid4().hex[:8]}" if provider in ["osn", "octotel"] else None
        if not self.test_cancellation(circuit_number, provider, solution_id):
            return False
        
        time.sleep(5)  # Wait between phases
        
        logger.info("Phase 3: Post-Cancellation Validation")
        if not self.test_validation(circuit_number, provider):
            return False
        
        logger.success("Integration test completed successfully")
        return True
    
    # Load test - UPDATED FOR UNIFORM circuit_number USAGE
    def run_load_test(self, concurrency=5, job_count=20, provider="mfn"):
        logger.header(f"Load Test: {job_count} jobs, {concurrency} concurrent ({provider.upper()})")
        
        start_time = time.time()
        jobs_to_create = self._generate_load_test_jobs(job_count, provider)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(self._create_job_from_template, job) for job in jobs_to_create]
            success_count = sum(1 for future in concurrent.futures.as_completed(futures) if future.result())
        
        total_time = time.time() - start_time
        success_rate = (success_count/job_count)*100
        
        logger.info(f"Completed in {total_time:.2f}s")
        logger.info(f"Success rate: {success_count}/{job_count} ({success_rate:.1f}%)")
        
        return success_count == job_count
    
    def _generate_load_test_jobs(self, count, provider):
        jobs = []
        for i in range(count):
            action = random.choice(["validation", "cancellation"])
            
            # UPDATED: ALL providers now use circuit_number uniformly
            if provider == "evotel":
                # Generate realistic circuit numbers for Evotel (these map to their serial numbers)
                circuit_numbers = [
                    f"48575443{random.choice(['D9B290B1', '2E64EDA8', 'ABC123EF', 'DEF456AB'])}",
                    f"LOAD{i:04d}{''.join(random.choices('ABCDEF0123456789', k=8))}"
                ]
                circuit_number = random.choice(circuit_numbers)
            else:
                circuit_number = f"LOAD_{provider.upper()}_{i:04d}"
            
            # UNIFORM parameters structure
            parameters = {
                "circuit_number": circuit_number,  # Uniform parameter name for ALL providers
                "external_job_id": f"LOAD_{uuid.uuid4().hex[:8]}"
            }
            
            # Add provider-specific additional parameters
            if action == "cancellation" and provider in ["osn", "octotel"]:
                parameters["solution_id"] = f"SOL_{i:04d}"
            
            jobs.append({
                "provider": provider,
                "action": action,
                "parameters": parameters,
                "priority": random.randint(1, 10)
            })
        return jobs
    
    # Monitoring
    def monitor_job(self, job_id, timeout=300):
        logger.header(f"Monitoring Job {job_id}")
        return self._monitor_job(job_id, timeout)
    
    def _monitor_job(self, job_id, timeout=300):
        start_time = time.time()
        
        while (time.time() - start_time) < timeout:
            try:
                response = requests.get(f"{self.orchestrator_url}/jobs/{job_id}", timeout=self.timeout)
                if response.status_code == 200:
                    job = response.json()
                    status = job.get("status")
                    
                    logger.info(f"Job {job_id} status: {status}")
                    
                    if status in ["completed", "failed", "error"]:
                        if status == "completed":
                            logger.success(f"Job {job_id} completed")
                            return True
                        else:
                            logger.error(f"Job {job_id} failed: {status}")
                            result = job.get("result", {})
                            if result:
                                logger.error(f"Error details: {result.get('error', 'No details')}")
                            return False
                    
                    time.sleep(5)
                else:
                    logger.error(f"Failed to get job status: {response.status_code}")
                    return False
                    
            except Exception as e:
                logger.error(f"Error monitoring job: {str(e)}")
                time.sleep(5)
        
        logger.error(f"Job {job_id} timed out after {timeout}s")
        return False
    
    # Report generation
    def generate_report(self, output_file=None):
        logger.header("Generating Report")
        
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "jobs_created": len(self.jobs_created),
            "callbacks_received": len(callbacks),
            "job_completion_status": job_completion_status,
            "framework_version": "uniform_circuit_number_v1.0"
        }
        
        if output_file:
            try:
                with open(output_file, 'w') as f:
                    json.dump(report_data, f, indent=2)
                logger.success(f"Report saved to {output_file}")
            except Exception as e:
                logger.error(f"Failed to save report: {str(e)}")
                return False
        else:
            print(json.dumps(report_data, indent=2))
        
        return True
    
    # Helper methods
    def _create_job(self, provider, action, parameters, priority=5):
        job_data = {
            "provider": provider,
            "action": action,
            "parameters": parameters,
            "priority": priority
        }
        
        logger.info(f"Creating {provider} {action} job with parameters: {parameters}")
        
        try:
            response = requests.post(f"{self.orchestrator_url}/jobs", json=job_data, timeout=self.timeout)
            if response.status_code == 200:
                job = response.json()
                job_id = job.get("id")
                self.jobs_created.append(job_id)
                logger.success(f"Created job {job_id}")
                
                # Trigger processing
                try:
                    requests.post(f"{self.orchestrator_url}/process", timeout=self.timeout)
                except:
                    pass
                
                return job_id
            else:
                logger.error(f"Failed to create job: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error creating job: {str(e)}")
            return None
    
    def _create_job_from_template(self, job_template):
        return self._create_job(
            job_template["provider"],
            job_template["action"],
            job_template["parameters"],
            job_template["priority"]
        ) is not None

def main():
    parser = argparse.ArgumentParser(
        description="RPA Testing Framework with Uniform circuit_number Support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Health and status checks
  python test_framework.py --health --status
  
  # Uniform circuit_number usage for ALL providers
  python test_framework.py --test-validation --circuit FTTX123456 --provider mfn
  python test_framework.py --test-validation --circuit 48575443D9B290B1 --provider evotel
  python test_framework.py --test-cancellation --circuit 48575443D9B290B1 --provider evotel
  
  # Integration and load tests
  python test_framework.py --integration --circuit 48575443D9B290B1 --provider evotel
  python test_framework.py --load-test --provider evotel --concurrency 3 --job-count 10
  
  # Backward compatibility (deprecated)
  python test_framework.py --test-validation --provider evotel --serial 48575443D9B290B1
        """
    )
    
    # Connection settings
    parser.add_argument("--orchestrator-url", default="http://localhost:8620")
    parser.add_argument("--worker-url", default="http://localhost:8621")
    parser.add_argument("--timeout", type=int, default=30)
    
    # Test modules
    parser.add_argument("--health", action="store_true", help="Check system health")
    parser.add_argument("--status", action="store_true", help="Get system status")
    parser.add_argument("--callbacks", action="store_true", help="Start callback listener")
    parser.add_argument("--callback-port", type=int, default=8625)
    
    # Job testing
    parser.add_argument("--test-validation", action="store_true", help="Test validation job")
    parser.add_argument("--test-cancellation", action="store_true", help="Test cancellation job")
    parser.add_argument("--integration", action="store_true", help="Run integration test")
    parser.add_argument("--load-test", action="store_true", help="Run load test")
    
    # Parameters - UPDATED FOR UNIFORMITY
    parser.add_argument("--provider", choices=["mfn", "osn", "octotel", "evotel"], default="mfn",
                       help="FNO provider to test")
    parser.add_argument("--circuit", help="Circuit number (uniform for ALL providers including Evotel)")
    parser.add_argument("--serial", help="DEPRECATED: Use --circuit instead. Serial number for backward compatibility")
    parser.add_argument("--solution-id", help="Solution ID for OSN/Octotel cancellations")
    parser.add_argument("--requested-date", help="Requested date for cancellations")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent jobs for load test")
    parser.add_argument("--job-count", type=int, default=20, help="Total jobs for load test")
    
    # Monitoring and reporting
    parser.add_argument("--monitor", action="store_true", help="Monitor a specific job")
    parser.add_argument("--job-id", type=int, help="Job ID to monitor")
    parser.add_argument("--report", action="store_true", help="Generate test report")
    parser.add_argument("--output", help="Output file for report")
    
    # Options
    parser.add_argument("--background", action="store_true", help="Run callback server in background")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate arguments
    if args.serial and not args.circuit:
        logger.warning("--serial is deprecated. Please use --circuit for uniformity across all providers.")
        logger.info("For now, mapping --serial to --circuit for backward compatibility.")
    
    framework = RpaTestFramework(
        orchestrator_url=args.orchestrator_url,
        worker_url=args.worker_url,
        timeout=args.timeout
    )
    
    success = True
    
    try:
        # Start callback listener if needed
        if args.callbacks or any([args.test_validation, args.test_cancellation, args.integration, args.load_test]):
            framework.start_callback_listener(args.callback_port, background=args.background or not args.callbacks)
            if args.callbacks and not args.background:
                return
        
        # Run tests - UPDATED FOR UNIFORM circuit_number USAGE
        if args.health:
            if not framework.check_health():
                success = False
        
        if args.status:
            if not framework.get_system_status():
                success = False
        
        if args.test_validation:
            if not framework.test_validation(
                circuit_number=args.circuit, 
                provider=args.provider, 
                serial_number=args.serial  # Backward compatibility
            ):
                success = False
        
        if args.test_cancellation:
            if not framework.test_cancellation(
                circuit_number=args.circuit, 
                provider=args.provider, 
                solution_id=args.solution_id, 
                requested_date=args.requested_date,
                serial_number=args.serial  # Backward compatibility
            ):
                success = False
        
        if args.integration:
            if not framework.run_integration_test(
                circuit_number=args.circuit, 
                provider=args.provider,
                serial_number=args.serial  # Backward compatibility
            ):
                success = False
        
        if args.load_test:
            if not framework.run_load_test(args.concurrency, args.job_count, args.provider):
                success = False
        
        if args.monitor and args.job_id:
            if not framework.monitor_job(args.job_id):
                success = False
        
        if args.report:
            if not framework.generate_report(args.output):
                success = False
        
        # Wait for callbacks
        if framework.callback_server and success:
            time.sleep(5)  # Wait for callbacks to arrive
        
        if success:
            logger.success("All tests completed successfully")
        else:
            logger.error("Some tests failed")
            sys.exit(1)
            
    finally:
        framework.stop_callback_listener()

if __name__ == "__main__":
    main()