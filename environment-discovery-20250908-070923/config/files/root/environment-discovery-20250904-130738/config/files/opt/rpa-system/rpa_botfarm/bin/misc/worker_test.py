#!/usr/bin/env python3
"""
Test worker service integration with Evotel module
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

def start_worker():
    """Start the worker service in a subprocess"""
    try:
        # Start worker
        process = subprocess.Popen(
            [sys.executable, "worker.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Give worker time to start
        time.sleep(5)
        
        return process
    except Exception as e:
        print(f"Failed to start worker: {e}")
        return None

def test_worker_status():
    """Test worker status endpoint"""
    try:
        response = requests.get("http://localhost:8621/status", timeout=10)
        if response.status_code == 200:
            status = response.json()
            print("✓ Worker is online")
            print(f"  Version: {status.get('version')}")
            print(f"  Providers: {status.get('providers', [])}")
            print(f"  Actions: {status.get('actions', {})}")
            
            # Check if evotel is supported
            if 'evotel' in status.get('providers', []):
                print("✓ Evotel provider is available")
                evotel_actions = status.get('actions', {}).get('evotel', [])
                if 'validation' in evotel_actions:
                    print("✓ Evotel validation action is available")
                    return True
                else:
                    print("✗ Evotel validation action not found")
                    return False
            else:
                print("✗ Evotel provider not found in worker")
                return False
        else:
            print(f"✗ Worker status check failed: {response.status_code}")
            return False
            
    except requests.RequestException as e:
        print(f"✗ Failed to connect to worker: {e}")
        return False

def test_worker_execution():
    """Test job execution via worker"""
    print("\n" + "=" * 60)
    print("WORKER EXECUTION TEST")
    print("=" * 60)
    
    # Test job request
    job_request = {
        "job_id": 12345,
        "provider": "evotel",
        "action": "validation",
        "parameters": {
            "job_id": "test_worker_001",
            "serial_number": "48575443D9B290B1"  # Example serial number
        }
    }
    
    try:
        print(f"Sending job request: {json.dumps(job_request, indent=2)}")
        
        # Submit job to worker
        response = requests.post(
            "http://localhost:8621/execute",
            json=job_request,
            timeout=300  # 5 minutes timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            print("\n✓ Job executed successfully")
            print("Worker Response:")
            print(json.dumps(result, indent=2, default=str))
            
            # Validate response structure
            assert "status" in result
            assert "job_id" in result
            assert "result" in result
            
            job_status = result.get("status")
            job_result = result.get("result", {})
            
            if job_status == "success":
                print("\n✓ Job completed successfully")
                
                # Check automation result
                automation_status = job_result.get("status")
                if automation_status == "success":
                    print("✓ Evotel validation succeeded")
                    
                    details = job_result.get("details", {})
                    if details.get("found"):
                        print("✓ Service found in Evotel")
                        
                        # Print service info
                        service_summary = details.get("service_summary", {})
                        if service_summary.get("customer"):
                            print(f"  Customer: {service_summary['customer']}")
                        if service_summary.get("product"):
                            print(f"  Product: {service_summary['product']}")
                            
                    else:
                        print("- Service not found in Evotel")
                        
                elif automation_status in ["failure", "error"]:
                    print(f"⚠ Automation failed: {job_result.get('message', 'No message')}")
                    
                else:
                    print(f"⚠ Unexpected automation status: {automation_status}")
                    
            elif job_status == "error":
                print(f"✗ Job failed: {job_result.get('error', 'No error message')}")
                return False
                
            return True
            
        else:
            print(f"✗ Worker request failed: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except requests.Timeout:
        print("✗ Job execution timed out")
        return False
    except Exception as e:
        print(f"✗ Job execution failed: {e}")
        return False

def main():
    """Main test function"""
    print("=" * 60)
    print("WORKER INTEGRATION TEST - Evotel Validation")
    print("=" * 60)
    
    # Check if worker is already running
    if test_worker_status():
        print("Worker is already running, proceeding with tests...")
        success = test_worker_execution()
    else:
        print("Starting worker service...")
        worker_process = start_worker()
        
        if worker_process is None:
            print("✗ Failed to start worker")
            return False
            
        try:
            # Test worker status
            if test_worker_status():
                success = test_worker_execution()
            else:
                success = False
                
        finally:
            # Clean up worker process
            print("\nStopping worker...")
            worker_process.terminate()
            worker_process.wait(timeout=10)
    
    if success:
        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED - Evotel integration working!")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("✗ TESTS FAILED - Check errors above")
        print("=" * 60)
        
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)