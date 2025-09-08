#!/usr/bin/env python3
"""
End-to-end test of complete RPA system with Evotel validation
"""
import sys
import os
import json
import requests
import time
import subprocess
from threading import Thread

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class RPASystemTest:
    def __init__(self):
        self.orchestrator_process = None
        self.worker_process = None
        self.orchestrator_url = "http://localhost:8620"
        self.worker_url = "http://localhost:8621"
        
    def start_services(self):
        """Start orchestrator and worker services"""
        print("Starting RPA services...")
        
        try:
            # Start worker first
            print("Starting worker...")
            self.worker_process = subprocess.Popen(
                [sys.executable, "worker.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            time.sleep(3)
            
            # Start orchestrator
            print("Starting orchestrator...")
            self.orchestrator_process = subprocess.Popen(
                [sys.executable, "orchestrator.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            time.sleep(5)
            
            return True
            
        except Exception as e:
            print(f"Failed to start services: {e}")
            return False
    
    def stop_services(self):
        """Stop all services"""
        print("Stopping services...")
        
        if self.orchestrator_process:
            self.orchestrator_process.terminate()
            self.orchestrator_process.wait(timeout=10)
            
        if self.worker_process:
            self.worker_process.terminate()
            self.worker_process.wait(timeout=10)
    
    def test_orchestrator_status(self):
        """Test orchestrator health"""
        try:
            response = requests.get(f"{self.orchestrator_url}/health", timeout=10)
            if response.status_code == 200:
                print("✓ Orchestrator is healthy")
                return True
            else:
                print(f"✗ Orchestrator health check failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ Failed to connect to orchestrator: {e}")
            return False
    
    def test_worker_status(self):
        """Test worker health"""
        try:
            response = requests.get(f"{self.worker_url}/status", timeout=10)
            if response.status_code == 200:
                status = response.json()
                print("✓ Worker is healthy")
                
                # Check Evotel support
                if 'evotel' in status.get('providers', []):
                    print("✓ Evotel provider available")
                    return True
                else:
                    print("✗ Evotel provider not available")
                    return False
            else:
                print(f"✗ Worker health check failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"✗ Failed to connect to worker: {e}")
            return False
    
    def create_job(self, serial_number="48575443D9B290B1"):
        """Create a new Evotel validation job"""
        job_data = {
            "provider": "evotel",
            "action": "validation",
            "priority": 5,
            "parameters": {
                "external_job_id": "e2e_test_001",
                "serial_number": serial_number
            }
        }
        
        try:
            print(f"Creating job: {json.dumps(job_data, indent=2)}")
            
            response = requests.post(
                f"{self.orchestrator_url}/jobs",
                json=job_data,
                timeout=30
            )
            
            if response.status_code == 200:
                job = response.json()
                job_id = job.get("id")
                print(f"✓ Job created successfully with ID: {job_id}")
                return job_id
            else:
                print(f"✗ Job creation failed: {response.status_code}")
                print(f"Response: {response.text}")
                return None
                
        except Exception as e:
            print(f"✗ Failed to create job: {e}")
            return None
    
    def monitor_job(self, job_id, timeout=300):
        """Monitor job execution"""
        print(f"Monitoring job {job_id}...")
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                response = requests.get(
                    f"{self.orchestrator_url}/jobs/{job_id}",
                    timeout=10
                )
                
                if response.status_code == 200:
                    job = response.json()
                    status = job.get("status")
                    
                    print(f"Job {job_id} status: {status}")
                    
                    if status in ["completed", "failed", "error", "cancelled"]:
                        return job
                    
                    time.sleep(5)  # Poll every 5 seconds
                    
                else:
                    print(f"Failed to get job status: {response.status_code}")
                    time.sleep(5)
                    
            except Exception as e:
                print(f"Error monitoring job: {e}")
                time.sleep(5)
        
        print(f"Job monitoring timed out after {timeout} seconds")
        return None
    
    def analyze_job_result(self, job):
        """Analyze the final job result"""
        print("\n" + "=" * 60)
        print("JOB RESULT ANALYSIS")
        print("=" * 60)
        
        status = job.get("status")
        result = job.get("result", {})
        
        print(f"Final Status: {status}")
        
        if status == "completed":
            print("✓ Job completed successfully")
            
            # Check automation result
            details = result.get("details", {})
            if details.get("found"):
                print("✓ Service found in Evotel portal")
                
                # Display service information
                service_summary = details.get("service_summary", {})
                if service_summary:
                    print("\nService Information:")
                    for key, value in service_summary.items():
                        if value:
                            print(f"  {key}: {value}")
                
                # Display work order summary
                work_order_summary = details.get("work_order_summary", {})
                if work_order_summary:
                    print(f"\nWork Orders: {work_order_summary.get('total_work_orders', 0)}")
                    if work_order_summary.get("primary_work_order_reference"):
                        print(f"Primary WO: {work_order_summary['primary_work_order_reference']}")
                
                # Display completeness
                extraction_metadata = details.get("extraction_metadata", {})
                if extraction_metadata.get("completeness_score"):
                    score = float(extraction_metadata["completeness_score"]) * 100
                    print(f"Data Completeness: {score:.1f}%")
                
            else:
                print("- Service not found in Evotel portal")
                
            # Check for screenshots
            screenshots = result.get("screenshot_data", [])
            print(f"Screenshots captured: {len(screenshots)}")
            
            return True
            
        elif status in ["failed", "error"]:
            print(f"✗ Job failed: {result.get('message', 'No error message')}")
            
            # Show error details
            error_details = result.get("details", {})
            if error_details.get("error"):
                print(f"Error: {error_details['error']}")
                
            return False
            
        else:
            print(f"⚠ Unexpected job status: {status}")
            return False
    
    def run_full_test(self):
        """Run the complete end-to-end test"""
        print("=" * 60)
        print("END-TO-END RPA SYSTEM TEST - Evotel Validation")
        print("=" * 60)
        
        try:
            # Start services
            if not self.start_services():
                return False
            
            # Test service health
            if not self.test_orchestrator_status():
                return False
                
            if not self.test_worker_status():
                return False
            
            # Create and monitor job
            job_id = self.create_job()
            if job_id is None:
                return False
            
            final_job = self.monitor_job(job_id)
            if final_job is None:
                return False
            
            # Analyze results
            success = self.analyze_job_result(final_job)
            
            if success:
                print("\n" + "=" * 60)
                print("✓ END-TO-END TEST PASSED!")
                print("✓ Evotel integration is working correctly")
                print("=" * 60)
            else:
                print("\n" + "=" * 60)
                print("✗ END-TO-END TEST FAILED")
                print("=" * 60)
            
            return success
            
        finally:
            self.stop_services()

def main():
    """Main test execution"""
    test_system = RPASystemTest()
    success = test_system.run_full_test()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()