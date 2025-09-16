def main():
    """Main function to run the load test."""
    parser = argparse.ArgumentParser(description='Load test the RPA orchestration system')
    parser.add_argument('--base-url', default=DEFAULT_BASE_URL, 
                        help=f'Base URL for the orchestrator (default: {DEFAULT_BASE_URL})')
    parser.add_argument('--concurrency', type=int, default=DEFAULT_CONCURRENCY, 
                        help=f'Number of concurrent jobs to submit (default: {DEFAULT_CONCURRENCY})')
    parser.add_argument('--job-count', type=int, default=DEFAULT_JOB_COUNT, 
                        help=f'Total number of jobs to create (default: {DEFAULT_JOB_COUNT})')
    parser.add_argument('--test-type', default=DEFAULT_TEST_TYPE, choices=TEST_TYPES,
                        help=f'Type of test to run (default: {DEFAULT_TEST_TYPE})')
    parser.add_argument('--timeout', type=int, default=30,
                        help='Timeout for API requests in seconds (default: 30)')
    parser.add_argument('--monitor', action='store_true',
                        help='Monitor jobs until completion')
    parser.add_argument('--monitor-timeout', type=int, default=300,
                        help='Maximum time to monitor jobs in seconds (default: 300)')
    parser.add_argument('--output', help='Write test results to JSON file')
    parser.add_argument('--analyze', help='Analyze results from a previous test run')
    
    args = parser.parse_args()
    
    # Check if we should analyze a previous run
    if args.analyze:
        analyze_results(args.analyze)
        return
    
    # Create load tester
    tester = LoadTester(
        base_url=args.base_url,
        concurrency=args.concurrency,
        timeout=args.timeout
    )
    
    try:
        # Run the load test
        results = tester.run_test(
            test_type=args.test_type,
            job_count=args.job_count
        )
        
        # Monitor jobs if requested
        if args.monitor and results['job_ids']:
            monitoring_results = tester.monitor_jobs(
                job_ids=results['job_ids'],
                max_duration=args.monitor_timeout
            )
            results['monitoring'] = monitoring_results
        
        # Save results to file if requested
        if args.output:
            save_results(results, args.output)
            print(f"\nResults saved to {args.output}")
        
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nTest failed with error: {str(e)}")
        sys.exit(1)

def save_results(results: Dict, filename: str):
    """Save test results to a JSON file."""
    # Add timestamp
    results['timestamp'] = datetime.now().isoformat()
    
    with open(filename, 'w') as f:
        json.dump(results, f, indent=2)

def analyze_results(filename: str):
    """Analyze and visualize results from a previous test run."""
    try:
        with open(filename, 'r') as f:
            results = json.load(f)
        
        print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 80}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.BLUE}= Load Test Analysis - {filename}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 80}{Colors.END}\n")
        
        # Print test parameters
        print(f"Test Type: {results.get('test_type', 'unknown')}")
        print(f"Job Count: {results.get('job_count', 'unknown')}")
        print(f"Concurrency: {results.get('concurrency', 'unknown')}")
        print(f"Timestamp: {results.get('timestamp', 'unknown')}")
        
        # Print performance metrics
        print(f"\nPerformance Metrics:")
        print(f"Total Time: {results.get('total_time', 0):.2f} seconds")
        print(f"Throughput: {results.get('throughput', 0):.2f} jobs/second")
        print(f"Avg Job Creation Time: {results.get('avg_job_time', 0):.3f} seconds")
        print(f"Min/Max Job Time: {results.get('min_job_time', 0):.3f}s / {results.get('max_job_time', 0):.3f}s")
        
        # Print job results
        print(f"\nJob Results:")
        print(f"Successful: {results.get('successful_jobs', 0)}")
        print(f"Failed: {results.get('failed_jobs', 0)}")
        
        # Print monitoring results if available
        if 'monitoring' in results:
            monitoring = results['monitoring']
            print(f"\nJob Monitoring Results:")
            print(f"Monitoring Time: {monitoring.get('monitoring_time', 0):.2f} seconds")
            print(f"Jobs Completed: {monitoring.get('completed_count', 0)}/{monitoring.get('job_count', 0)}")
            print(f"Timed Out: {monitoring.get('timed_out_count', 0)}")
            
            # Print status breakdown
            print(f"\nStatus Breakdown:")
            for status, count in monitoring.get('status_counts', {}).items():
                percentage = (count / monitoring.get('job_count', 1)) * 100
                print(f"  - {status}: {count} ({percentage:.1f}%)")
        
        # Generate visualizations
        try:
            # 1. Job Creation Time Histogram
            plt.figure(figsize=(10, 6))
            plt.subplot(2, 2, 1)
            plt.bar(['Success', 'Failure'], [results.get('successful_jobs', 0), results.get('failed_jobs', 0)])
            plt.title('Job Creation Success/Failure')
            plt.ylabel('Count')
            
            # 2. Status Distribution (if monitoring data exists)
            if 'monitoring' in results:
                status_data = results['monitoring'].get('status_counts', {})
                plt.subplot(2, 2, 2)
                plt.pie(
                    status_data.values(), 
                    labels=status_data.keys(),
                    autopct='%1.1f%%'
                )
                plt.title('Job Status Distribution')
                
                # 3. Create a line chart of completion time vs job count
                if len(results['monitoring'].get('job_statuses', {})) > 0:
                    plt.subplot(2, 1, 2)
                    plt.axhline(y=0.5, color='r', linestyle='-', alpha=0.3)
                    plt.axhline(y=1.0, color='g', linestyle='-', alpha=0.3)
                    plt.ylim(0, 1.1)
                    plt.title('Job Completion Rate Over Time')
                    plt.xlabel('Monitoring Time (seconds)')
                    plt.ylabel('Completion Percentage')
            
            plt.tight_layout()
            
            # Save the image
            output_file = os.path.splitext(filename)[0] + '_analysis.png'
            plt.savefig(output_file)
            print(f"\nAnalysis chart saved to {output_file}")
            
        except Exception as e:
            print(f"Error generating visualizations: {str(e)}")
        
    except Exception as e:
        print(f"Error analyzing results: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()#!/usr/bin/env python
"""
RPA Orchestrator Load Test
-------------------------
This script generates load tests for the RPA orchestration system
by creating multiple jobs simultaneously with various configurations.
It helps verify the system's capacity, error handling, and overall stability.

Usage:
    python load_test.py [--base-url URL] [--concurrency N] [--test-type TYPE] [--job-count N]
"""

import argparse
import concurrent.futures
import json
import random
import requests
import time
import string
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import uuid
import os
import matplotlib.pyplot as plt

# Default configuration
DEFAULT_BASE_URL = "http://localhost:8620"
DEFAULT_CONCURRENCY = 5
DEFAULT_JOB_COUNT = 20
DEFAULT_TEST_TYPE = "mixed"

# Available test types
TEST_TYPES = ["mixed", "validation", "cancellation", "priority", "error", "stress"]

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

class LoadTester:
    """Load tester for the RPA orchestration system."""
    
    def __init__(self, base_url: str = DEFAULT_BASE_URL, 
                 concurrency: int = DEFAULT_CONCURRENCY,
                 timeout: int = 30):
        """Initialize the load tester."""
        self.base_url = base_url
        self.concurrency = concurrency
        self.timeout = timeout
        self.results = []
        self.job_ids = []
        self.start_time = None
        self.end_time = None
    
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
    
    def generate_circuit_number(self) -> str:
        """Generate a random circuit number for testing."""
        return f"LOAD-TEST-{random.randint(1000, 9999)}"
    
    def generate_external_id(self) -> str:
        """Generate a random external job ID."""
        timestamp = int(time.time())
        random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        return f"EXT-{timestamp}-{random_chars}"
    
    def create_validation_job(self, priority: int = None) -> Dict:
        """Create a validation job template."""
        if priority is None:
            priority = random.randint(1, 10)
            
        return {
            "provider": "mfn",
            "action": "validation",
            "parameters": {
                "circuit_number": self.generate_circuit_number(),
                "test_mode": True,
                "external_job_id": self.generate_external_id(),
                "load_test": True
            },
            "priority": priority
        }
    
    def create_cancellation_job(self, priority: int = None) -> Dict:
        """Create a cancellation job template."""
        if priority is None:
            priority = random.randint(1, 10)
            
        return {
            "provider": "mfn",
            "action": "cancellation",
            "parameters": {
                "circuit_number": self.generate_circuit_number(),
                "cancellation_reason": "Load testing",
                "test_mode": True,
                "external_job_id": self.generate_external_id(),
                "load_test": True
            },
            "priority": priority
        }
    
    def create_error_job(self) -> Dict:
        """Create a job template designed to trigger errors."""
        return {
            "provider": "mfn",
            "action": "validation",
            "parameters": {
                "circuit_number": self.generate_circuit_number(),
                "test_mode": True,
                "external_job_id": self.generate_external_id(),
                "force_error": True,
                "load_test": True
            },
            "priority": random.randint(1, 10)
        }
    
    def submit_job(self, job_data: Dict) -> Tuple[bool, Dict, float]:
        """Submit a job to the orchestrator and return the result."""
        start_time = time.time()
        
        try:
            response = requests.post(
                f"{self.base_url}/jobs",
                json=job_data,
                timeout=self.timeout
            )
            
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                job = response.json()
                return True, job, elapsed
            else:
                return False, {"error": response.text, "status_code": response.status_code}, elapsed
        except requests.exceptions.RequestException as e:
            elapsed = time.time() - start_time
            return False, {"error": str(e)}, elapsed
    
    def monitor_jobs(self, job_ids: List[int], interval: int = 5, max_duration: int = 300) -> Dict:
        """Monitor jobs until completion or timeout."""
        self.print_header(f"Monitoring {len(job_ids)} Jobs")
        
        start_time = time.time()
        pending_jobs = set(job_ids)
        job_statuses = {}
        final_states = ['completed', 'failed', 'error', 'cancelled']
        
        while pending_jobs and (time.time() - start_time) < max_duration:
            for job_id in list(pending_jobs):
                try:
                    response = requests.get(
                        f"{self.base_url}/jobs/{job_id}",
                        timeout=self.timeout
                    )
                    
                    if response.status_code == 200:
                        job = response.json()
                        status = job.get('status', 'unknown')
                        job_statuses[job_id] = status
                        
                        if status in final_states:
                            self.print_info(f"Job {job_id} finished with status: {status}")
                            pending_jobs.remove(job_id)
                    else:
                        self.print_warning(f"Failed to get status for job {job_id}: {response.status_code}")
                except Exception as e:
                    self.print_error(f"Error checking job {job_id}: {str(e)}")
            
            if pending_jobs:
                pending_count = len(pending_jobs)
                completed_count = len(job_ids) - pending_count
                print(f"\rWaiting... {completed_count}/{len(job_ids)} jobs completed ({pending_count} remaining)", end="")
                time.sleep(interval)
        
        print()  # New line after progress indicator
        
        # Calculate final statistics
        status_counts = {}
        for status in job_statuses.values():
            status_counts[status] = status_counts.get(status, 0) + 1
        
        elapsed = time.time() - start_time
        
        self.print_header("Job Monitoring Results")
        self.print_info(f"Total monitoring time: {elapsed:.2f} seconds")
        self.print_info(f"Jobs completed: {len(job_ids) - len(pending_jobs)}/{len(job_ids)}")
        
        for status, count in sorted(status_counts.items()):
            status_color = Colors.GREEN
            if status in ['failed', 'error']:
                status_color = Colors.RED
            elif status in ['running', 'dispatching']:
                status_color = Colors.BLUE
            elif status in ['pending', 'retry_pending']:
                status_color = Colors.YELLOW
                
            self.print_info(f"Status {status_color}{status}{Colors.END}: {count} jobs")
        
        if pending_jobs:
            self.print_warning(f"Monitoring timed out with {len(pending_jobs)} jobs still pending")
        
        return {
            'monitoring_time': elapsed,
            'job_count': len(job_ids),
            'completed_count': len(job_ids) - len(pending_jobs),
            'timed_out_count': len(pending_jobs),
            'status_counts': status_counts,
            'job_statuses': job_statuses
        }
    
    def run_test(self, test_type: str, job_count: int) -> Dict:
        """Run a load test with the specified parameters."""
        self.print_header(f"Running {test_type.upper()} Load Test")
        self.print_info(f"Creating {job_count} jobs with concurrency {self.concurrency}")
        
        # Reset results
        self.results = []
        self.job_ids = []
        self.start_time = time.time()
        job_creation_times = []
        
        # Generate job templates based on test type
        jobs_to_create = []
        
        if test_type == "validation":
            jobs_to_create = [self.create_validation_job() for _ in range(job_count)]
        elif test_type == "cancellation":
            jobs_to_create = [self.create_cancellation_job() for _ in range(job_count)]
        elif test_type == "priority":
            # Mix of high, medium, and low priority jobs
            jobs_to_create = [
                self.create_validation_job(priority=10) for _ in range(job_count // 3)
            ] + [
                self.create_validation_job(priority=5) for _ in range(job_count // 3)
            ] + [
                self.create_validation_job(priority=1) for _ in range(job_count - (2 * (job_count // 3)))
            ]
            random.shuffle(jobs_to_create)  # Randomize order
        elif test_type == "error":
            jobs_to_create = [self.create_error_job() for _ in range(job_count)]
        elif test_type == "stress":
            # Create a mix of all job types with random priorities
            jobs_to_create = []
            for _ in range(job_count):
                job_type = random.choice(["validation", "cancellation", "error"])
                if job_type == "validation":
                    jobs_to_create.append(self.create_validation_job())
                elif job_type == "cancellation":
                    jobs_to_create.append(self.create_cancellation_job())
                else:
                    jobs_to_create.append(self.create_error_job())
        else:  # mixed test type
            # Create a mix of validation and cancellation jobs
            jobs_to_create = []
            for _ in range(job_count):
                if random.random() < 0.7:  # 70% validation
                    jobs_to_create.append(self.create_validation_job())
                else:  # 30% cancellation
                    jobs_to_create.append(self.create_cancellation_job())
        
        # Submit jobs in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = [executor.submit(self.submit_job, job) for job in jobs_to_create]
            for i, future in enumerate(concurrent.futures.as_completed(futures)):
                success, result, elapsed = future.result()
                job_creation_times.append(elapsed)
                
                if success:
                    job_id = result.get('id')
                    self.job_ids.append(job_id)
                    self.results.append({
                        'success': True,
                        'job_id': job_id,
                        'elapsed': elapsed,
                        'job_data': result
                    })
                    self.print_success(f"Created job {i+1}/{job_count}: ID {job_id} in {elapsed:.3f}s")
                else:
                    self.results.append({
                        'success': False,
                        'error': result.get('error', 'Unknown error'),
                        'elapsed': elapsed
                    })
                    self.print_error(f"Failed to create job {i+1}/{job_count}: {result.get('error', 'Unknown error')}")
        
        self.end_time = time.time()
        total_time = self.end_time - self.start_time
        
        # Calculate statistics
        success_count = sum(1 for r in self.results if r.get('success'))
        error_count = len(self.results) - success_count
        avg_time = sum(job_creation_times) / len(job_creation_times) if job_creation_times else 0
        max_time = max(job_creation_times) if job_creation_times else 0
        min_time = min(job_creation_times) if job_creation_times else 0
        
        # Print summary
        self.print_header("Load Test Results")
        self.print_info(f"Total time: {total_time:.2f} seconds")
        self.print_info(f"Jobs submitted: {len(self.results)}")
        self.print_info(f"Successful: {success_count}")
        self.print_info(f"Failed: {error_count}")
        self.print_info(f"Average job creation time: {avg_time:.3f} seconds")
        self.print_info(f"Min/Max job creation time: {min_time:.3f}s / {max_time:.3f}s")
        self.print_info(f"Throughput: {len(self.results) / total_time:.2f} jobs/second")
        
        return {
            'test_type': test_type,
            'job_count': job_count,
            'concurrency': self.concurrency,
            'total_time': total_time,
            'successful_jobs': success_count,
            'failed_jobs': error_count,
            'avg_job_time': avg_time,
            'min_job_time': min_time,
            'max_job_time': max_time,
            'throughput': len(self.results) / total_time if total_time > 0 else 0,
            'job_ids': self.job_ids
        }
