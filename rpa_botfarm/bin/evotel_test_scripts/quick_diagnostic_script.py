#!/usr/bin/env python3
"""
Quick Orchestrator Database Diagnostic Script
Run this to quickly identify why your orchestrator.db isn't updating
"""

import os
import sqlite3
import requests
import json
from datetime import datetime
from pathlib import Path

# Import your config
try:
    from config import Config
    print("✓ Config imported successfully")
except ImportError as e:
    print(f"✗ Failed to import config: {e}")
    exit(1)

def check_database_file():
    """Check if database file exists and is accessible"""
    print("\n=== DATABASE FILE CHECK ===")
    
    print(f"Expected DB path: {Config.DB_PATH}")
    
    if os.path.exists(Config.DB_PATH):
        print("✓ Database file exists")
        
        # Check file permissions
        if os.access(Config.DB_PATH, os.R_OK):
            print("✓ Database file is readable")
        else:
            print("✗ Database file is NOT readable")
            
        if os.access(Config.DB_PATH, os.W_OK):
            print("✓ Database file is writable")
        else:
            print("✗ Database file is NOT writable")
            
        # Check file size
        file_size = os.path.getsize(Config.DB_PATH)
        print(f"Database file size: {file_size} bytes")
        
        if file_size == 0:
            print("⚠️ Database file is empty!")
            
    else:
        print("✗ Database file does NOT exist")
        
        # Check if directory exists
        db_dir = os.path.dirname(Config.DB_PATH)
        if os.path.exists(db_dir):
            print(f"✓ Database directory exists: {db_dir}")
        else:
            print(f"✗ Database directory does NOT exist: {db_dir}")

def check_database_content():
    """Check database tables and recent jobs"""
    print("\n=== DATABASE CONTENT CHECK ===")
    
    if not os.path.exists(Config.DB_PATH):
        print("✗ Cannot check content - database file doesn't exist")
        return
        
    try:
        conn = sqlite3.connect(Config.DB_PATH)
        cursor = conn.cursor()
        
        # Check tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Tables found: {[table[0] for table in tables]}")
        
        if ('job_queue',) in tables:
            print("✓ job_queue table exists")
            
            # Check table structure
            cursor.execute("PRAGMA table_info(job_queue);")
            columns = cursor.fetchall()
            print(f"job_queue columns: {len(columns)} columns")
            
            # Count total jobs
            cursor.execute("SELECT COUNT(*) FROM job_queue;")
            total_jobs = cursor.fetchone()[0]
            print(f"Total jobs in database: {total_jobs}")
            
            # Check today's jobs
            today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute("SELECT COUNT(*) FROM job_queue WHERE DATE(created_at) = ?;", (today,))
            today_jobs = cursor.fetchone()[0]
            print(f"Jobs created today ({today}): {today_jobs}")
            
            # Check recent jobs
            cursor.execute("""
                SELECT id, provider, action, status, created_at 
                FROM job_queue 
                ORDER BY created_at DESC 
                LIMIT 5;
            """)
            recent_jobs = cursor.fetchall()
            print("\nRecent jobs:")
            for job in recent_jobs:
                print(f"  ID: {job[0]}, Provider: {job[1]}, Action: {job[2]}, Status: {job[3]}, Created: {job[4]}")
                
        else:
            print("✗ job_queue table does NOT exist")
            
        conn.close()
        
    except sqlite3.Error as e:
        print(f"✗ Database error: {e}")

def check_orchestrator_service():
    """Check if orchestrator service is running"""
    print("\n=== ORCHESTRATOR SERVICE CHECK ===")
    
    base_url = f"http://{Config.ORCHESTRATOR_HOST}:{Config.ORCHESTRATOR_PORT}"
    
    # Check health
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            print("✓ Orchestrator health endpoint is responding")
        else:
            print(f"⚠️ Orchestrator health returned status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"✗ Cannot reach orchestrator health endpoint: {e}")
        return False
    
    # Check scheduler status
    try:
        response = requests.get(f"{base_url}/scheduler", timeout=5)
        if response.status_code == 200:
            scheduler_data = response.json()
            print(f"✓ Scheduler is running: {scheduler_data.get('running')}")
            print(f"Scheduled jobs: {scheduler_data.get('job_count')}")
        else:
            print(f"⚠️ Scheduler endpoint returned status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"✗ Cannot reach scheduler endpoint: {e}")
    
    # Check metrics
    try:
        response = requests.get(f"{base_url}/metrics", timeout=5)
        if response.status_code == 200:
            metrics = response.json()
            current = metrics.get('current', {})
            print(f"✓ Current job metrics:")
            print(f"  Queued: {current.get('queued_jobs', 0)}")
            print(f"  Running: {current.get('running_jobs', 0)}")
            print(f"  Completed: {current.get('completed_jobs', 0)}")
            print(f"  Failed: {current.get('failed_jobs', 0)}")
        else:
            print(f"⚠️ Metrics endpoint returned status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"✗ Cannot reach metrics endpoint: {e}")
    
    return True

def test_job_creation():
    """Test creating a job"""
    print("\n=== JOB CREATION TEST ===")
    
    base_url = f"http://{Config.ORCHESTRATOR_HOST}:{Config.ORCHESTRATOR_PORT}"
    
    test_job = {
        "provider": "mfn",
        "action": "validation",
        "parameters": {
            "circuit_number": "DIAGNOSTIC_TEST_123",
            "external_job_id": f"diagnostic_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        }
    }
    
    try:
        response = requests.post(
            f"{base_url}/jobs",
            json=test_job,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 200:
            job_data = response.json()
            print(f"✓ Test job created successfully")
            print(f"Job ID: {job_data.get('id')}")
            print(f"Status: {job_data.get('status')}")
            return job_data.get('id')
        else:
            print(f"✗ Job creation failed with status: {response.status_code}")
            print(f"Response: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"✗ Job creation request failed: {e}")
    
    return None

def check_directories():
    """Check if required directories exist"""
    print("\n=== DIRECTORY CHECK ===")
    
    directories = [
        Config.BASE_DATA_DIR,
        Config.DB_DIR,
        Config.LOG_DIR,
        Config.SCREENSHOT_DIR
    ]
    
    for directory in directories:
        if os.path.exists(directory):
            print(f"✓ {directory} exists")
            if os.access(directory, os.W_OK):
                print(f"✓ {directory} is writable")
            else:
                print(f"✗ {directory} is NOT writable")
        else:
            print(f"✗ {directory} does NOT exist")

def check_logs():
    """Check recent log entries"""
    print("\n=== LOG CHECK ===")
    
    log_file = Config.get_log_path()
    
    if os.path.exists(log_file):
        print(f"✓ Log file exists: {log_file}")
        
        # Check recent entries
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
                
            if lines:
                print(f"Total log lines: {len(lines)}")
                print("\nLast 5 log entries:")
                for line in lines[-5:]:
                    print(f"  {line.strip()}")
                    
                # Check for errors
                error_lines = [line for line in lines if 'ERROR' in line.upper()]
                if error_lines:
                    print(f"\nRecent errors found: {len(error_lines)}")
                    print("Last error:")
                    print(f"  {error_lines[-1].strip()}")
            else:
                print("⚠️ Log file is empty")
                
        except Exception as e:
            print(f"✗ Cannot read log file: {e}")
    else:
        print(f"✗ Log file does not exist: {log_file}")

def main():
    """Run all diagnostic checks"""
    print("=" * 60)
    print("ORCHESTRATOR DATABASE DIAGNOSTIC")
    print("=" * 60)
    
    # Basic configuration check
    print("\n=== CONFIGURATION ===")
    print(f"Base data directory: {Config.BASE_DATA_DIR}")
    print(f"Database path: {Config.DB_PATH}")
    print(f"Orchestrator URL: http://{Config.ORCHESTRATOR_HOST}:{Config.ORCHESTRATOR_PORT}")
    
    # Run all checks
    check_directories()
    check_database_file()
    check_database_content()
    service_running = check_orchestrator_service()
    check_logs()
    
    if service_running:
        test_job_id = test_job_creation()
        
        if test_job_id:
            print(f"\n=== FOLLOW-UP ===")
            print(f"Wait 30 seconds, then check if job {test_job_id} appears in database:")
            print(f"sqlite3 {Config.DB_PATH} \"SELECT * FROM job_queue WHERE id = {test_job_id};\"")
    
    print("\n" + "=" * 60)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
