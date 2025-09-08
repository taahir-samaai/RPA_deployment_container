#!/usr/bin/env python
"""
RPA Orchestrator Test Script
----------------------------
This script tests the RPA orchestration system by:
1. Checking system status/health
2. Creating various test jobs
3. Monitoring job progress
4. Validating job results

Usage:
    python test_orchestrator.py
"""

import requests
import json
import time
import sys
import os
import argparse
from datetime import datetime
from typing import Dict, List, Any, Optional

# Configuration
DEFAULT_BASE_URL = "http://localhost:8620"
DEFAULT_WORKER_URL = "http://localhost:8621"
DEFAULT_REQUESTS_TIMEOUT = 10

# Test job templates for different scenarios
TEST_JOBS = [
    {
        "name": "Basic Validation",
        "provider": "mfn",
        "action": "validation",
        "parameters": {
            "circuit_number": "TEST-CIRCUIT-001",
            "test_mode": True,
            "external_job_id": "EXT-VAL-001"  # External reference ID
        },
        "priority": 5
    },
    {
        "name": "High Priority Validation",
        "provider": "mfn",
        "action": "validation",
        "parameters": {
            "circuit_number": "TEST-CIRCUIT-002",
            "test_mode": True,
            "external_job_id": "EXT-VAL-002-HIGH"  # External reference ID
        },
        "priority": 10
    },
    {
        "name": "Low Priority Validation",
        "provider": "mfn",
        "action": "validation",
        "parameters": {
            "circuit_number": "TEST-CIRCUIT-005",
            "test_mode": True,
            "external_job_id": "EXT-VAL-005-LOW"  # External reference ID
        },
        "priority": 1
    },
    {
        "name": "Cancellation Request",
        "provider": "mfn",
        "action": "cancellation",
        "parameters": {
            "circuit_number": "TEST-CIRCUIT-003",
            "cancellation_reason": "Testing cancellation flow",
            "test_mode": True,
            "external_job_id": "EXT-CAN-003"  # External reference ID
        },
        "priority": 5
    },
    {
        "name": "To Be Cancelled Job",
        "provider": "mfn",
        "action": "validation",
        "parameters": {
            "circuit_number": "TEST-CIRCUIT-004",
            "test_mode": True,
            "external_job_id": "EXT-CAN-TEST-004",  # External reference ID
            "delay_execution": 30  # Add delay to ensure we can cancel
        },
        "priority": 3
    }
]

class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

class OrchestratorTester:
    """Test client for the RPA orchestration system."""
    
    def __init__(self, base_url: str = DEFAULT_BASE_URL, 
                 worker_url: str = DEFAULT_WORKER_URL,
                 timeout: int = DEFAULT_REQUESTS_TIMEOUT):
        """Initialize the tester with API URLs."""
        self.base_url = base_url
        self.worker_url = worker_url
        self.timeout = timeout
        self.jobs_created = []
        
    def print_header(self, text: str):
        """Print a formatted header."""
        print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 80}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.BLUE}= {text}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 80}{Colors.END}\n")
        
    def print_success(self, text: str):
        """Print a success message."""
        print(f"{Colors.GREEN}✓ {text}{Colors.END}")
        
    def print_warning(self, text: str):
        """Print a warning message."""
        print(f"{Colors.YELLOW}⚠ {text}{Colors.END}")
        
    def print_error(self, text: str):
        """Print an error message."""
        print(f"{Colors.RED}✗ {text}{Colors.END}")
        
    def print_info(self, text: str):
        """Print an info message."""
        print(f"{Colors.CYAN}ℹ {text}{Colors.END}")
    
    def check_orchestrator_health(self) -> bool:
        """Check if the orchestrator is healthy."""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                self.print_success(f"Orchestrator is healthy - status: {data.get('status')}")
                return True
            else:
                self.print_error(f"Orchestrator health check failed with status code: {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            self.print_error(f"Orchestrator health check failed: {str(e)}")
            return False
    
    def check_worker_health(self) -> bool:
        """Check if the worker is healthy."""
        try:
            response = requests.get(f"{self.worker_url}/health", timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                self.print_success(f"Worker is healthy - active jobs: {data.get('active_jobs', 'N/A')}")
                return True
            else:
                self.print_error(f"Worker health check failed with status code: {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            self.print_error(f"Worker health check failed: {str(e)}")
            return False
    
    def get_system_status(self) -> Dict:
        """Get detailed system status."""
        try:
            response = requests.get(f"{self.base_url}/metrics", timeout=self.timeout)
            if response.status_code == 200:
                return response.json()
            else:
                self.print_error(f"Failed to get system status: {response.status_code}")
                return {}
        except requests.exceptions.RequestException as e:
            self.print_error(f"Failed to get system status: {str(e)}")
            return {}
    
    def display_system_status(self):
        """Display detailed system status."""
        status = self.get_system_status()
        if not status:
            return
        
        current = status.get('current', {})
        
        self.print_header("System Status")
        print(f"Status: {current.get('status', 'N/A')}")
        print(f"Uptime: {current.get('uptime', 'N/A')}")
        print(f"Version: {current.get('version', 'N/A')}")
        print(f"\nCurrent Jobs:")
        print(f"- Queued: {current.get('queued_jobs', 0)}")
        print(f"- Running: {current.get('running_jobs', 0)}")
        print(f"- Completed: {current.get('completed_jobs', 0)}")
        print(f"- Failed: {current.get('failed_jobs', 0)}")
        
        print("\nWorker Status:")
        for worker, status in current.get('workers', {}).items():
            color = Colors.GREEN if status == 'online' else Colors.RED
            print(f"- {worker}: {color}{status}{Colors.END}")
    
    def create_job(self, job_template: Dict) -> Dict:
        """Create a job from a template."""
        job_data = {
            "provider": job_template["provider"],
            "action": job_template["action"],
            "parameters": job_template["parameters"],
            "priority": job_template["priority"]
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/jobs",
                json=job_data,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                job = response.json()
                self.print_success(f"Created job '{job_template['name']}' with ID: {job['id']}")
                self.jobs_created.append((job['id'], job_template['name']))
                return job
            else:
                self.print_error(f"Failed to create job '{job_template['name']}': {response.status_code}")
                print(response.text)
                return {}
        except requests.exceptions.RequestException as e:
            self.print_error(f"Failed to create job '{job_template['name']}': {str(e)}")
            return {}
    
    def get_job_status(self, job_id: int) -> Dict:
        """Get the status of a job."""
        try:
            response = requests.get(f"{self.base_url}/jobs/{job_id}", timeout=self.timeout)
            if response.status_code == 200:
                return response.json()
            else:
                self.print_error(f"Failed to get status for job {job_id}: {response.status_code}")
                return {}
        except requests.exceptions.RequestException as e:
            self.print_error(f"Failed to get status for job {job_id}: {str(e)}")
            return {}
    
    def get_job_history(self, job_id: int) -> List[Dict]:
        """Get the history of a job."""
        try:
            response = requests.get(f"{self.base_url}/history/{job_id}", timeout=self.timeout)
            if response.status_code == 200:
                return response.json()
            else:
                self.print_error(f"Failed to get history for job {job_id}: {response.status_code}")
                return []
        except requests.exceptions.RequestException as e:
            self.print_error(f"Failed to get history for job {job_id}: {str(e)}")
            return []
    
    def display_job_details(self, job_id: int, job_name: str):
        """Display detailed job information."""
        job = self.get_job_status(job_id)
        if not job:
            return
        
        history = self.get_job_history(job_id)
        
        self.print_header(f"Job Details: {job_name} (ID: {job_id})")
        
        # Status with color
        status = job.get('status', 'unknown')
        status_color = Colors.GREEN
        if status in ['failed', 'error']:
            status_color = Colors.RED
        elif status in ['pending', 'dispatching', 'retry_pending']:
            status_color = Colors.YELLOW
        elif status in ['running']:
            status_color = Colors.BLUE
            
        print(f"Status: {status_color}{status}{Colors.END}")
        print(f"Provider: {job.get('provider', 'N/A')}")
        print(f"Action: {job.get('action', 'N/A')}")
        print(f"Priority: {job.get('priority', 'N/A')}")
        print(f"Created: {job.get('created_at', 'N/A')}")
        
        if job.get('started_at'):
            print(f"Started: {job.get('started_at', 'N/A')}")
            
        if job.get('completed_at'):
            print(f"Completed: {job.get('completed_at', 'N/A')}")
            
        print("\nParameters:")
        for key, value in job.get('parameters', {}).items():
            print(f"- {key}: {value}")
            
        # Show result if available
        if job.get('result'):
            print("\nResult:")
            try:
                result = job.get('result', {})
                for key, value in result.items():
                    if key == 'screenshot_data':
                        print(f"- {key}: [{len(value)} screenshots]")
                    elif isinstance(value, dict):
                        print(f"- {key}:")
                        for k, v in value.items():
                            print(f"  - {k}: {v}")
                    else:
                        print(f"- {key}: {value}")
            except Exception as e:
                print(f"Error displaying result: {str(e)}")
                print(f"Raw result: {job.get('result')}")
        
        # Show history
        if history:
            print("\nHistory:")
            for entry in history:
                timestamp = entry.get('timestamp', 'N/A')
                status = entry.get('status', 'N/A')
                details = entry.get('details', '')
                
                # Truncate long details
                if details and len(details) > 100:
                    details = details[:97] + "..."
                    
                # Colorize status
                status_color = Colors.BLUE
                if status in ['failed', 'error']:
                    status_color = Colors.RED
                elif status in ['completed']:
                    status_color = Colors.GREEN
                    
                print(f"- [{timestamp}] {status_color}{status}{Colors.END}: {details}")
    
    def monitor_jobs(self, interval: int = 5, max_duration: int = 300):
        """Monitor all created jobs until they complete or timeout."""
        if not self.jobs_created:
            self.print_warning("No jobs to monitor")
            return
        
        self.print_header("Monitoring Jobs")
        
        start_time = time.time()
        pending_jobs = {job_id: job_name for job_id, job_name in self.jobs_created}
        
        while pending_jobs and (time.time() - start_time) < max_duration:
            for job_id, job_name in list(pending_jobs.items()):
                job = self.get_job_status(job_id)
                status = job.get('status', 'unknown')
                
                if status in ['completed', 'failed', 'error', 'cancelled']:
                    self.print_info(f"Job {job_id} ({job_name}) finished with status: {status}")
                    self.display_job_details(job_id, job_name)
                    del pending_jobs[job_id]
                else:
                    self.print_info(f"Job {job_id} ({job_name}) status: {status}")
            
            if pending_jobs:
                print(f"\nWaiting {interval} seconds for next check... ({len(pending_jobs)} jobs still pending)")
                time.sleep(interval)
        
        if pending_jobs:
            self.print_warning(f"Monitoring timed out with {len(pending_jobs)} jobs still pending")
            for job_id, job_name in pending_jobs.items():
                self.print_info(f"Timed out job: {job_id} ({job_name})")
        else:
            self.print_success("All jobs completed!")
    
    def trigger_job_processing(self):
        """Manually trigger job processing."""
        try:
            response = requests.post(f"{self.base_url}/process", timeout=self.timeout)
            if response.status_code == 200:
                self.print_success("Manually triggered job processing")
                return True
            else:
                self.print_error(f"Failed to trigger job processing: {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            self.print_error(f"Failed to trigger job processing: {str(e)}")
            return False
    
    def test_job_cancellation(self):
        """Test job cancellation functionality."""
        self.print_header("Testing Job Cancellation")
        
        # Find the job that's designed to be cancelled
        cancel_job_template = next((job for job in TEST_JOBS if job["name"] == "To Be Cancelled Job"), None)
        if not cancel_job_template:
            self.print_error("Could not find 'To Be Cancelled Job' template")
            return False
        
        # Create the job
        self.print_info("Creating job that will be cancelled...")
        job = self.create_job(cancel_job_template)
        if not job:
            self.print_error("Failed to create job for cancellation test")
            return False
        
        job_id = job["id"]
        
        # Wait briefly to ensure job is registered
        time.sleep(2)
        
        # Verify job status is still pending
        job_status = self.get_job_status(job_id)
        if not job_status:
            self.print_error(f"Failed to get job status for job {job_id}")
            return False
        
        # Cancel the job
        self.print_info(f"Attempting to cancel job {job_id}...")
        result = self.cancel_job(job_id)
        if not result:
            self.print_error(f"Failed to cancel job {job_id}")
            return False
        
        # Verify job was cancelled
        job_status = self.get_job_status(job_id)
        if not job_status:
            self.print_error(f"Failed to get job status for job {job_id}")
            return False
        
        if job_status.get("status") == "cancelled":
            self.print_success(f"Job {job_id} was successfully cancelled")
            return True
        else:
            self.print_error(f"Job cancellation failed. Job status is: {job_status.get('status')}")
            return False
    
    def test_priority_scheduling(self):
        """Test priority-based job scheduling."""
        self.print_header("Testing Priority-Based Scheduling")
        
        # Find high and low priority jobs
        high_job = next((job for job in TEST_JOBS if job["name"] == "High Priority Validation"), None)
        low_job = next((job for job in TEST_JOBS if job["name"] == "Low Priority Validation"), None)
        
        if not high_job or not low_job:
            self.print_error("Could not find high and low priority job templates")
            return False
        
        # Create jobs in reverse priority order (low first, then high)
        self.print_info("Creating low priority job first...")
        low_job_data = self.create_job(low_job)
        if not low_job_data:
            self.print_error("Failed to create low priority job")
            return False
        
        self.print_info("Creating high priority job second...")
        high_job_data = self.create_job(high_job)
        if not high_job_data:
            self.print_error("Failed to create high priority job")
            return False
        
        low_job_id = low_job_data["id"]
        high_job_id = high_job_data["id"]
        
        # Trigger job processing
        self.trigger_job_processing()
        
        # Wait briefly for processing to start
        time.sleep(5)
        
        # Check job statuses - high priority should start first
        high_job_status = self.get_job_status(high_job_id)
        low_job_status = self.get_job_status(low_job_id)
        
        if not high_job_status or not low_job_status:
            self.print_error("Failed to get job statuses")
            return False
        
        # Expect high priority job to be running/dispatching first
        high_status = high_job_status.get("status")
        low_status = low_job_status.get("status")
        
        self.print_info(f"High priority job status: {high_status}")
        self.print_info(f"Low priority job status: {low_status}")
        
        priority_working = False
        
        # Verify high priority is processed before low priority
        if high_status in ["running", "dispatching", "completed"]:
            if low_status in ["pending"]:
                self.print_success("Priority scheduling works correctly! High priority job is being processed before low priority job.")
                priority_working = True
            elif high_job_status.get("started_at", "") < low_job_status.get("started_at", ""):
                self.print_success("Priority scheduling works correctly! High priority job started before low priority job.")
                priority_working = True
        
        return priority_working
        
    def generate_test_report(self):
        """Generate a report of all test jobs and their status."""
        self.print_header("Test Job Report")
        
        all_successful = True
        job_results = []
        
        for job_id, job_name in self.jobs_created:
            # Get latest job data
            job_data = self.get_job_status(job_id)
            if not job_data:
                job_results.append({
                    "job_id": job_id,
                    "name": job_name,
                    "status": "unknown",
                    "success": False
                })
                all_successful = False
                continue
                
            status = job_data.get("status")
            success = status in ["completed"]
            
            if not success:
                all_successful = False
                
            job_results.append({
                "job_id": job_id,
                "name": job_name,
                "status": status,
                "success": success,
                "started_at": job_data.get("started_at"),
                "completed_at": job_data.get("completed_at"),
                "external_job_id": job_data.get("parameters", {}).get("external_job_id", "N/A")
            })
        
        # Print summary table
        print("\nJob Summary:")
        print(f"{'ID':<5} {'External ID':<15} {'Name':<25} {'Status':<12} {'Result':<8}")
        print("-" * 70)
        
        for job in job_results:
            status_color = Colors.GREEN if job["success"] else Colors.RED if job["status"] in ["failed", "error"] else Colors.YELLOW
            result_text = "SUCCESS" if job["success"] else "FAILED"
            result_color = Colors.GREEN if job["success"] else Colors.RED
            
            print(f"{job['job_id']:<5} {job.get('external_job_id', 'N/A'):<15} {job['name']:<25} {status_color}{job['status']:<12}{Colors.END} {result_color}{result_text}{Colors.END}")
        
        print("\nOverall Test Result:", end=" ")
        if all_successful:
            print(f"{Colors.GREEN}All tests PASSED{Colors.END}")
        else:
            print(f"{Colors.YELLOW}Some tests did not complete successfully{Colors.END}")
            
        return all_successful
            
    def run_complete_test(self, max_monitoring_time: int = 300):
        """Run a complete test cycle."""
        self.print_header("RPA Orchestration System Test")
        
        # Check health of services
        orchestrator_ok = self.check_orchestrator_health()
        worker_ok = self.check_worker_health()
        
        if not orchestrator_ok or not worker_ok:
            self.print_error("Health check failed - stopping test")
            return False
        
        # Display system status
        self.display_system_status()
        
        # Test cancellation functionality
        cancellation_ok = self.test_job_cancellation()
        
        # Create standard test jobs
        self.print_header("Creating Standard Test Jobs")
        # Skip the "To Be Cancelled Job" as we already tested it
        for job_template in [j for j in TEST_JOBS if j["name"] != "To Be Cancelled Job"]:
            self.create_job(job_template)
            time.sleep(1)  # Small delay between job creation
        
        # Test priority-based scheduling
        priority_ok = self.test_priority_scheduling()
        
        # Trigger job processing to speed up test
        self.trigger_job_processing()
        
        # Monitor jobs
        self.monitor_jobs(interval=3, max_duration=max_monitoring_time)
        
        # Show final system status
        self.display_system_status()
        
        # Generate test report
        all_successful = self.generate_test_report()
        
        return all_successful and cancellation_ok and priority_ok

def main():
    """Main function to run the test script."""
    parser = argparse.ArgumentParser(description='Test the RPA orchestration system')
    parser.add_argument('--base-url', default=DEFAULT_BASE_URL, 
                        help=f'Base URL for the orchestrator (default: {DEFAULT_BASE_URL})')
    parser.add_argument('--worker-url', default=DEFAULT_WORKER_URL, 
                        help=f'Base URL for the worker (default: {DEFAULT_WORKER_URL})')
    parser.add_argument('--timeout', type=int, default=DEFAULT_REQUESTS_TIMEOUT, 
                        help=f'Request timeout in seconds (default: {DEFAULT_REQUESTS_TIMEOUT})')
    parser.add_argument('--max-time', type=int, default=300, 
                        help='Maximum monitoring time in seconds (default: 300)')
    
    args = parser.parse_args()
    
    tester = OrchestratorTester(
        base_url=args.base_url,
        worker_url=args.worker_url,
        timeout=args.timeout
    )
    
    try:
        success = tester.run_complete_test(max_monitoring_time=args.max_time)
        if success:
            print("\nTest completed successfully!")
        else:
            print("\nTest completed with errors.")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nTest failed with error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
