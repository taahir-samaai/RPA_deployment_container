"""
Simplified Test Script for RPA Orchestration System
Creates a cancellation job and monitors it to completion
"""

import requests
import json
import time
import uuid
import logging
import sys
import argparse
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("rpa-test")

def run_cancellation_test(orchestrator_url, circuit_number, effective_date=None):
    """Run a cancellation test and monitor it to completion"""
    start_time = datetime.now()
    logger.info(f"Testing cancellation on {circuit_number} at {orchestrator_url}")
    if effective_date:
        logger.info(f"Using effective cancellation date: {effective_date}")
    
    # Generate test ID
    test_id = str(uuid.uuid4())[:8]
    
    # 1. Check system health
    try:
        response = requests.get(f"{orchestrator_url}/health")
        if response.status_code == 200:
            logger.info("✅ System health check passed")
        else:
            logger.error(f"❌ System health check failed: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"❌ Health check failed: {str(e)}")
        return False
    
    # 2. Create cancellation job
    try:
        job_params = {
            "external_job_id": f"TEST_JOB_{test_id}",
            "circuit_number": circuit_number
        }
        
        # Add effective cancellation date if provided
        if effective_date:
            job_params["effective_cancellation_date"] = effective_date
        
        job_data = {
            "provider": "mfn",
            "action": "cancellation",
            "parameters": job_params,
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
        logger.info(f"✅ Created cancellation job with ID: {job_id}")
        
    except Exception as e:
        logger.error(f"❌ Job creation failed: {str(e)}")
        return False
    
    # 3. Trigger job processing
    try:
        response = requests.post(f"{orchestrator_url}/process")
        if response.status_code == 200:
            logger.info("✅ Triggered job processing")
        else:
            logger.warning(f"⚠️ Process trigger returned: {response.status_code}")
    except Exception as e:
        logger.warning(f"⚠️ Process trigger failed: {str(e)}")
    
    # 4. Monitor job until completion
    completed = False
    max_wait_time = 180  # 3 minutes
    start_monitoring = datetime.now()
    
    logger.info(f"Monitoring job {job_id} until completion (max {max_wait_time}s)...")
    
    while not completed and (datetime.now() - start_monitoring).total_seconds() < max_wait_time:
        try:
            response = requests.get(f"{orchestrator_url}/jobs/{job_id}")
            
            if response.status_code != 200:
                logger.warning(f"⚠️ Failed to get job status: {response.status_code}")
                time.sleep(5)
                continue
                
            job_data = response.json()
            status = job_data.get("status")
            
            logger.info(f"Job status: {status}")
            
            if status in ["completed", "failed", "error"]:
                completed = True
                break
            
            # Wait 5 seconds between checks
            time.sleep(5)
            
        except Exception as e:
            logger.warning(f"⚠️ Error checking job status: {str(e)}")
            time.sleep(5)
    
    # 5. Get final result
    try:
        response = requests.get(f"{orchestrator_url}/jobs/{job_id}")
        job_data = response.json()
        status = job_data.get("status")
        result = job_data.get("result", {})
        
        if completed:
            logger.info(f"✅ Job completed with status: {status}")
            
            # Check for screenshots
            screenshots_response = requests.get(f"{orchestrator_url}/jobs/{job_id}/screenshots")
            if screenshots_response.status_code == 200:
                screenshot_data = screenshots_response.json()
                screenshot_count = screenshot_data.get("screenshot_count", 0)
                logger.info(f"📸 {screenshot_count} screenshots captured")
            
            # Process cancellation-specific data
            if isinstance(result, dict) and "details" in result:
                details = result["details"]
                
                # Print cancellation captured ID (the most important piece)
                cancellation_id = details.get("cancellation_captured_id")
                if cancellation_id:
                    logger.info(f"🔑 Cancellation ID: {cancellation_id}")
                
                # Check for cancellation capture data
                if "cancellation_captured" in details:
                    captured = details["cancellation_captured"]
                    logger.info("📋 Cancellation Capture Data:")
                    if isinstance(captured, dict):
                        for key, value in captured.items():
                            if key in ["cancellation_captured_id", "date", "row_text"]:
                                logger.info(f"  - {key}: {value}")
                
                # Compare initial and updated customer data
                initial = details.get("initial_customer_data", {})
                updated = details.get("customer_data", {})
                
                # Print initial expiry date if available
                if initial:
                    logger.info("📋 Initial Customer Data:")
                    for field in ["customer", "area", "originalbw", "activation", "expiry_date"]:
                        if field in initial:
                            logger.info(f"  - {field}: {initial[field]}")
                
                # Print updated expiry date if available
                if updated:
                    logger.info("📋 Updated Customer Data:")
                    for field in ["customer", "area", "expiry_date", "status"]:
                        if field in updated:
                            logger.info(f"  - {field}: {updated[field]}")
                    
                    # Highlight expiry date change
                    if "expiry_date" in initial and "expiry_date" in updated:
                        initial_date = initial["expiry_date"]
                        updated_date = updated["expiry_date"]
                        if initial_date != updated_date:
                            logger.info(f"✅ Expiry date changed: {initial_date} → {updated_date}")
            
            return status == "completed"
        else:
            logger.error(f"❌ Job did not complete within time limit. Last status: {status}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error getting final job result: {str(e)}")
        return False
    finally:
        logger.info(f"Test completed in {datetime.now() - start_time}")

def main():
    parser = argparse.ArgumentParser(description="Simple RPA Cancellation Test")
    parser.add_argument("--url", default="http://localhost:8620", help="Orchestrator URL")
    parser.add_argument("--circuit", default="FTTX244307", help="Circuit number to cancel")
    parser.add_argument("--date", help="Effective cancellation date (YYYY-MM-DD format)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    success = run_cancellation_test(args.url, args.circuit, args.date)
    
    if success:
        logger.info("🎉 Cancellation test completed successfully!")
        sys.exit(0)
    else:
        logger.error("⛔ Cancellation test failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
