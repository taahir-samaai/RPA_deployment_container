#!/usr/bin/env python3
"""
RPA System Status Script
------------------------
A comprehensive status reporter for the RPA orchestration system.
This script pulls configuration from the .env file and connects to all system components
to provide a full overview of the system status.
"""

import os
import sys
import json
import time
import datetime
import requests
from pathlib import Path
import sqlite3
from dotenv import load_dotenv
import colorama
from colorama import Fore, Style
import textwrap
import argparse

# Initialize colorama for cross-platform colored terminal output
colorama.init()

def format_table(data, headers, widths=None):
    """
    Format data as a simple table without external dependencies
    
    Args:
        data: List of rows (each row is a list of values)
        headers: List of column headers
        widths: Optional list of column widths
    
    Returns:
        str: Formatted table string
    """
    if not data:
        return "No data"
    
    # Determine column widths if not provided
    if not widths:
        # Initialize with header lengths
        widths = [len(str(h)) for h in headers]
        # Check data widths
        for row in data:
            for i, cell in enumerate(row):
                if i < len(widths):  # Ensure we don't go out of bounds
                    widths[i] = max(widths[i], len(str(cell)))
    
    # Format header
    header_line = " | ".join([str(h).ljust(widths[i]) for i, h in enumerate(headers)])
    separator = "-+-".join(["-" * w for w in widths])
    
    # Format rows
    result = [header_line, separator]
    for row in data:
        formatted_row = " | ".join([str(cell).ljust(widths[i]) if i < len(widths) else str(cell) 
                                   for i, cell in enumerate(row)])
        result.append(formatted_row)
    
    return "\n".join(result)

def load_config():
    """Load configuration from .env file and environment"""
    # Load environment variables from .env file
    load_dotenv()
    
    config = {
        # Server settings
        "ORCHESTRATOR_HOST": os.getenv("ORCHESTRATOR_HOST", "127.0.0.1"),
        "ORCHESTRATOR_PORT": int(os.getenv("ORCHESTRATOR_PORT", "8620")),
        "WORKER_HOST": os.getenv("WORKER_HOST", "127.0.0.1"),
        "WORKER_PORT": int(os.getenv("WORKER_PORT", "8621")),
        
        # Base data directory
        "BASE_DATA_DIR": os.getenv("BASE_DATA_DIR", "./data"),
        
        # Database settings
        "DB_PATH": os.path.join(
            os.getenv("BASE_DATA_DIR", "./data"), 
            "db", 
            os.getenv("DB_FILE", "orchestrator.db")
        ),
        
        # Evidence and log directories
        "EVIDENCE_DIR": os.path.join(os.getenv("BASE_DATA_DIR", "./data"), "evidence"),
        "LOG_DIR": os.path.join(os.getenv("BASE_DATA_DIR", "./data"), "logs"),
        
        # Worker settings
        "WORKER_ENDPOINTS": json.loads(os.getenv("WORKER_ENDPOINTS", '["http://localhost:8621/execute"]')),
    }
    
    return config

def check_orchestrator(config):
    """Check orchestrator status and metrics"""
    print(f"{Fore.CYAN}=== Orchestrator Status ==={Style.RESET_ALL}")
    
    orchestrator_url = f"http://{config['ORCHESTRATOR_HOST']}:{config['ORCHESTRATOR_PORT']}"
    
    # Check basic health
    try:
        response = requests.get(f"{orchestrator_url}/health", timeout=5)
        if response.status_code == 200:
            health_data = response.json()
            print(f"{Fore.GREEN}✓ Orchestrator is healthy{Style.RESET_ALL}")
            print(f"  Timestamp: {health_data.get('timestamp', 'N/A')}")
        else:
            print(f"{Fore.RED}✗ Orchestrator health check failed: {response.status_code}{Style.RESET_ALL}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"{Fore.RED}✗ Cannot connect to orchestrator: {str(e)}{Style.RESET_ALL}")
        return False
    
    # Get detailed metrics
    try:
        response = requests.get(f"{orchestrator_url}/metrics", timeout=5)
        if response.status_code == 200:
            metrics_data = response.json()
            current = metrics_data.get("current", {})
            
            print(f"\n{Fore.YELLOW}Current System Status:{Style.RESET_ALL}")
            print(f"  Status: {current.get('status', 'N/A')}")
            print(f"  Uptime: {current.get('uptime', 'N/A')}")
            print(f"  Version: {current.get('version', 'N/A')}")
            
            print(f"\n{Fore.YELLOW}Active Jobs:{Style.RESET_ALL}")
            print(f"  Queued: {current.get('queued_jobs', 0)}")
            print(f"  Running: {current.get('running_jobs', 0)}")
            print(f"  Completed: {current.get('completed_jobs', 0)}")
            print(f"  Failed: {current.get('failed_jobs', 0)}")
            
            # Worker status
            workers = current.get("workers", {})
            if workers:
                print(f"\n{Fore.YELLOW}Worker Status:{Style.RESET_ALL}")
                worker_table = []
                for endpoint, status in workers.items():
                    color = Fore.GREEN if status == "online" else Fore.RED
                    worker_table.append([endpoint, f"{color}{status}{Style.RESET_ALL}"])
                
                print(format_table(worker_table, ["Endpoint", "Status"]))
            
            # Scheduler status
            try:
                scheduler_response = requests.get(f"{orchestrator_url}/scheduler", timeout=5)
                if scheduler_response.status_code == 200:
                    scheduler_data = scheduler_response.json()
                    print(f"\n{Fore.YELLOW}Scheduler Status:{Style.RESET_ALL}")
                    print(f"  Running: {scheduler_data.get('running', False)}")
                    print(f"  Jobs: {scheduler_data.get('job_count', 0)}")
                    
                    if scheduler_data.get("jobs"):
                        job_table = []
                        for job in scheduler_data.get("jobs", []):
                            job_table.append([
                                job.get("id", "N/A"),
                                job.get("function", "N/A"),
                                job.get("next_run", "N/A")
                            ])
                        
                        print("\n" + format_table(job_table, ["Job ID", "Function", "Next Run"]))
            except requests.exceptions.RequestException:
                print(f"{Fore.YELLOW}Could not retrieve scheduler status{Style.RESET_ALL}")
                
            return True
    except requests.exceptions.RequestException as e:
        print(f"{Fore.RED}✗ Failed to get metrics: {str(e)}{Style.RESET_ALL}")
        return False

def check_workers(config):
    """Check status of all worker nodes"""
    print(f"\n{Fore.CYAN}=== Worker Status ==={Style.RESET_ALL}")
    
    worker_endpoints = config.get("WORKER_ENDPOINTS", [])
    
    if not worker_endpoints:
        print(f"{Fore.YELLOW}No worker endpoints configured{Style.RESET_ALL}")
        return False
    
    all_workers_healthy = True
    
    for endpoint in worker_endpoints:
        # Convert execute endpoint to status endpoint
        status_endpoint = endpoint.replace("/execute", "/status")
        health_endpoint = endpoint.replace("/execute", "/health")
        
        print(f"\n{Fore.BLUE}Worker: {endpoint}{Style.RESET_ALL}")
        
        # Check basic health
        try:
            response = requests.get(health_endpoint, timeout=5)
            if response.status_code == 200:
                health_data = response.json()
                print(f"{Fore.GREEN}✓ Worker is healthy{Style.RESET_ALL}")
                print(f"  Timestamp: {health_data.get('timestamp', 'N/A')}")
                print(f"  Active Jobs: {health_data.get('active_jobs', 0)}")
            else:
                print(f"{Fore.RED}✗ Worker health check failed: {response.status_code}{Style.RESET_ALL}")
                all_workers_healthy = False
                continue
        except requests.exceptions.RequestException as e:
            print(f"{Fore.RED}✗ Cannot connect to worker: {str(e)}{Style.RESET_ALL}")
            all_workers_healthy = False
            continue
        
        # Get detailed status
        try:
            response = requests.get(status_endpoint, timeout=5)
            if response.status_code == 200:
                status_data = response.json()
                
                print(f"\n{Fore.YELLOW}Worker Details:{Style.RESET_ALL}")
                print(f"  Version: {status_data.get('version', 'N/A')}")
                print(f"  Uptime: {status_data.get('uptime', 'N/A')}")
                print(f"  Hostname: {status_data.get('hostname', 'N/A')}")
                print(f"  System: {status_data.get('system', 'N/A')}")
                print(f"  Python Version: {status_data.get('python_version', 'N/A')}")
                print(f"  Selenium Available: {status_data.get('selenium_available', False)}")
                
                # Job stats
                job_stats = status_data.get("job_stats", {})
                print(f"\n{Fore.YELLOW}Job Statistics:{Style.RESET_ALL}")
                print(f"  Active: {job_stats.get('active', 0)}")
                print(f"  Total: {job_stats.get('total', 0)}")
                print(f"  Successful: {job_stats.get('successful', 0)}")
                print(f"  Failed: {job_stats.get('failed', 0)}")
                
                # Capacity
                capacity = status_data.get("capacity", {})
                print(f"\n{Fore.YELLOW}Capacity:{Style.RESET_ALL}")
                print(f"  Max Concurrent: {capacity.get('max_concurrent', 0)}")
                print(f"  Current Load: {capacity.get('current_load', 0)}")
                
                # Providers and actions
                providers = status_data.get("providers", [])
                actions = status_data.get("actions", {})
                if providers:
                    print(f"\n{Fore.YELLOW}Supported Providers: {', '.join(providers)}{Style.RESET_ALL}")
                
                if actions:
                    print(f"\n{Fore.YELLOW}Supported Actions:{Style.RESET_ALL}")
                    for provider, provider_actions in actions.items():
                        print(f"  {provider}: {', '.join(provider_actions)}")
            else:
                print(f"{Fore.RED}✗ Worker status check failed: {response.status_code}{Style.RESET_ALL}")
                all_workers_healthy = False
        except requests.exceptions.RequestException as e:
            print(f"{Fore.RED}✗ Failed to get worker status: {str(e)}{Style.RESET_ALL}")
            all_workers_healthy = False
    
    return all_workers_healthy

def check_database(config):
    """Check database status and recent jobs"""
    print(f"\n{Fore.CYAN}=== Database Status ==={Style.RESET_ALL}")
    
    db_path = config.get("DB_PATH")
    
    if not os.path.exists(db_path):
        print(f"{Fore.RED}✗ Database file not found: {db_path}{Style.RESET_ALL}")
        return False
    
    try:
        print(f"{Fore.GREEN}✓ Database file exists: {db_path}{Style.RESET_ALL}")
        print(f"  Size: {get_file_size(db_path)}")
        print(f"  Last Modified: {get_file_modified_time(db_path)}")
        
        # Connect to database and get job statistics
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Check if job_queue table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='job_queue'")
        if not cursor.fetchone():
            print(f"{Fore.RED}✗ job_queue table not found in database{Style.RESET_ALL}")
            return False
        
        # Get job counts by status
        cursor.execute("""
            SELECT status, COUNT(*) as count 
            FROM job_queue 
            GROUP BY status
        """)
        status_counts = cursor.fetchall()
        
        print(f"\n{Fore.YELLOW}Job Counts by Status:{Style.RESET_ALL}")
        status_table = []
        for row in status_counts:
            color = Fore.GREEN
            if row['status'] in ['failed', 'error']:
                color = Fore.RED
            elif row['status'] in ['pending', 'dispatching', 'retry_pending']:
                color = Fore.YELLOW
            elif row['status'] in ['running']:
                color = Fore.BLUE
            
            status_table.append([f"{color}{row['status']}{Style.RESET_ALL}", row['count']])
        
        print(format_table(status_table, ["Status", "Count"]))
        
        # Get recent jobs
        cursor.execute("""
            SELECT id, external_job_id, provider, action, status, 
                   created_at, updated_at, completed_at
            FROM job_queue 
            ORDER BY created_at DESC
            LIMIT 10
        """)
        recent_jobs = cursor.fetchall()
        
        if recent_jobs:
            print(f"\n{Fore.YELLOW}Recent Jobs (Last 10):{Style.RESET_ALL}")
            recent_table = []
            for job in recent_jobs:
                # Format status with color
                status = job['status'] or 'unknown'
                color = Fore.GREEN
                if status in ['failed', 'error']:
                    color = Fore.RED
                elif status in ['pending', 'dispatching', 'retry_pending']:
                    color = Fore.YELLOW
                elif status in ['running']:
                    color = Fore.BLUE
                
                formatted_status = f"{color}{status}{Style.RESET_ALL}"
                
                # Format dates
                created_at = format_date(job['created_at'])
                completed_at = format_date(job['completed_at']) if job['completed_at'] else 'N/A'
                
                # Format external_job_id or use ID if not available
                job_id = job['external_job_id'] or f"#{job['id']}"
                
                recent_table.append([
                    job['id'],
                    job_id,
                    job['provider'],
                    job['action'],
                    formatted_status,
                    created_at,
                    completed_at
                ])
            
            print(format_table(recent_table, 
                           ["ID", "External ID", "Provider", "Action", "Status", "Created", "Completed"]))
        
        # Get currently running jobs
        cursor.execute("""
            SELECT id, external_job_id, provider, action, started_at, assigned_worker
            FROM job_queue 
            WHERE status IN ('running', 'dispatching')
            ORDER BY started_at DESC
        """)
        running_jobs = cursor.fetchall()
        
        if running_jobs:
            print(f"\n{Fore.YELLOW}Currently Running Jobs ({len(running_jobs)}):{Style.RESET_ALL}")
            running_table = []
            for job in running_jobs:
                started_at = format_date(job['started_at']) if job['started_at'] else 'N/A'
                runtime = get_runtime(job['started_at']) if job['started_at'] else 'N/A'
                
                running_table.append([
                    job['id'],
                    job['external_job_id'] or f"#{job['id']}",
                    job['provider'],
                    job['action'],
                    started_at,
                    runtime,
                    job['assigned_worker'] or 'N/A'
                ])
            
            print(format_table(running_table, 
                           ["ID", "External ID", "Provider", "Action", "Started", "Runtime", "Worker"]))
        else:
            print(f"\n{Fore.YELLOW}No currently running jobs{Style.RESET_ALL}")
        
        # Get recently failed jobs
        cursor.execute("""
            SELECT id, external_job_id, provider, action, updated_at
            FROM job_queue 
            WHERE status IN ('failed', 'error')
            ORDER BY updated_at DESC
            LIMIT 5
        """)
        failed_jobs = cursor.fetchall()
        
        if failed_jobs:
            print(f"\n{Fore.YELLOW}Recent Failed Jobs ({len(failed_jobs)}):{Style.RESET_ALL}")
            failed_table = []
            for job in failed_jobs:
                failed_at = format_date(job['updated_at']) if job['updated_at'] else 'N/A'
                
                # Get error message if available
                cursor.execute("""
                    SELECT result FROM job_queue WHERE id = ?
                """, (job['id'],))
                result_row = cursor.fetchone()
                error_message = "N/A"
                
                if result_row and result_row['result']:
                    try:
                        result = json.loads(result_row['result'])
                        error_message = result.get('error', result.get('message', 'N/A'))
                        # Truncate long error messages
                        if error_message and len(error_message) > 50:
                            error_message = error_message[:47] + "..."
                    except (json.JSONDecodeError, TypeError):
                        error_message = "Invalid result format"
                
                failed_table.append([
                    job['id'],
                    job['external_job_id'] or f"#{job['id']}",
                    job['provider'],
                    job['action'],
                    failed_at,
                    error_message
                ])
            
            print(format_table(failed_table, 
                           ["ID", "External ID", "Provider", "Action", "Failed At", "Error"]))
        
        # Get system metrics
        cursor.execute("""
            SELECT * FROM system_metrics
            ORDER BY timestamp DESC
            LIMIT 1
        """)
        latest_metrics = cursor.fetchone()
        
        if latest_metrics:
            print(f"\n{Fore.YELLOW}Latest System Metrics:{Style.RESET_ALL}")
            print(f"  Timestamp: {format_date(latest_metrics['timestamp'])}")
            print(f"  Queued Jobs: {latest_metrics['queued_jobs']}")
            print(f"  Running Jobs: {latest_metrics['running_jobs']}")
            print(f"  Completed Jobs: {latest_metrics['completed_jobs']}")
            print(f"  Failed Jobs: {latest_metrics['failed_jobs']}")
        
        conn.close()
        return True
        
    except sqlite3.Error as e:
        print(f"{Fore.RED}✗ Database error: {str(e)}{Style.RESET_ALL}")
        return False
    except Exception as e:
        print(f"{Fore.RED}✗ Error checking database: {str(e)}{Style.RESET_ALL}")
        return False

def check_job_history(config, job_id):
    """Check detailed history for a specific job"""
    print(f"\n{Fore.CYAN}=== Job {job_id} History ==={Style.RESET_ALL}")
    
    orchestrator_url = f"http://{config['ORCHESTRATOR_HOST']}:{config['ORCHESTRATOR_PORT']}"
    
    # Get job details
    try:
        response = requests.get(f"{orchestrator_url}/jobs/{job_id}", timeout=5)
        if response.status_code == 200:
            job_data = response.json()
            
            print(f"\n{Fore.YELLOW}Job Details:{Style.RESET_ALL}")
            print(f"  ID: {job_data.get('id')}")
            print(f"  External ID: {job_data.get('external_job_id', 'N/A')}")
            print(f"  Provider: {job_data.get('provider')}")
            print(f"  Action: {job_data.get('action')}")
            
            # Status with color
            status = job_data.get('status', 'unknown')
            color = Fore.GREEN
            if status in ['failed', 'error']:
                color = Fore.RED
            elif status in ['pending', 'dispatching', 'retry_pending']:
                color = Fore.YELLOW
            elif status in ['running']:
                color = Fore.BLUE
            
            print(f"  Status: {color}{status}{Style.RESET_ALL}")
            print(f"  Created: {format_date(job_data.get('created_at'))}")
            print(f"  Started: {format_date(job_data.get('started_at')) if job_data.get('started_at') else 'N/A'}")
            print(f"  Completed: {format_date(job_data.get('completed_at')) if job_data.get('completed_at') else 'N/A'}")
            print(f"  Worker: {job_data.get('assigned_worker', 'N/A')}")
            
            # Display parameters
            parameters = job_data.get('parameters', {})
            if parameters:
                print(f"\n{Fore.YELLOW}Parameters:{Style.RESET_ALL}")
                for key, value in parameters.items():
                    print(f"  {key}: {value}")
            
            # Get job history
            history_response = requests.get(f"{orchestrator_url}/history/{job_id}", timeout=5)
            if history_response.status_code == 200:
                history_data = history_response.json()
                
                if history_data:
                    print(f"\n{Fore.YELLOW}Job History:{Style.RESET_ALL}")
                    history_table = []
                    for entry in history_data:
                        # Color code status
                        entry_status = entry.get('status', 'unknown')
                        color = Fore.GREEN
                        if entry_status in ['failed', 'error']:
                            color = Fore.RED
                        elif entry_status in ['pending', 'dispatching', 'retry_pending', 'created']:
                            color = Fore.YELLOW
                        elif entry_status in ['running', 'started']:
                            color = Fore.BLUE
                        
                        # Format and truncate details
                        details = entry.get('details', 'N/A')
                        if details and len(details) > 70:
                            details = details[:67] + "..."
                        
                        history_table.append([
                            format_date(entry.get('timestamp')),
                            f"{color}{entry_status}{Style.RESET_ALL}",
                            details
                        ])
                    
                    print(format_table(history_table, ["Timestamp", "Status", "Details"]))
            else:
                print(f"{Fore.RED}✗ Could not retrieve job history: {history_response.status_code}{Style.RESET_ALL}")
            
            # Check if job has screenshots
            screenshot_response = requests.get(f"{orchestrator_url}/jobs/{job_id}/screenshots", timeout=5)
            if screenshot_response.status_code == 200:
                screenshot_data = screenshot_response.json()
                
                screenshot_count = screenshot_data.get('screenshot_count', 0)
                if screenshot_count > 0:
                    print(f"\n{Fore.YELLOW}Job has {screenshot_count} screenshots{Style.RESET_ALL}")
                    
                    # Show screenshot details
                    screenshots = screenshot_data.get('screenshots', [])
                    screenshot_table = []
                    for screenshot in screenshots:
                        screenshot_table.append([
                            screenshot.get('id'),
                            screenshot.get('name'),
                            format_date(screenshot.get('timestamp')),
                            screenshot.get('description', 'N/A')
                        ])
                    
                    print(format_table(screenshot_table, 
                                   ["ID", "Name", "Timestamp", "Description"]))
            
            # Display result if available
            result = job_data.get('result', {})
            if result:
                print(f"\n{Fore.YELLOW}Job Result:{Style.RESET_ALL}")
                # Format result for display
                result_str = json.dumps(result, indent=2)
                # Split and indent for readability
                for line in result_str.split('\n'):
                    print(f"  {line}")
            
            # Check evidence directory
            evidence_dir = os.path.join(config['EVIDENCE_DIR'], f"job_{job_id}")
            if os.path.exists(evidence_dir):
                print(f"\n{Fore.YELLOW}Evidence Directory:{Style.RESET_ALL}")
                print(f"  Path: {evidence_dir}")
                
                evidence_files = list(Path(evidence_dir).glob("*"))
                if evidence_files:
                    print(f"  Files: {len(evidence_files)}")
                    evidence_table = []
                    for file in evidence_files:
                        evidence_table.append([
                            file.name,
                            get_file_size(file),
                            get_file_modified_time(file)
                        ])
                    
                    print(format_table(evidence_table, ["Filename", "Size", "Modified"]))
                else:
                    print("  No evidence files found")
            else:
                print(f"\n{Fore.YELLOW}No evidence directory found for this job{Style.RESET_ALL}")
            
        else:
            print(f"{Fore.RED}✗ Could not retrieve job details: {response.status_code}{Style.RESET_ALL}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"{Fore.RED}✗ Error retrieving job details: {str(e)}{Style.RESET_ALL}")
        return False
    
    return True

def check_filesystem(config):
    """Check filesystem status, logs, and evidence directories"""
    print(f"\n{Fore.CYAN}=== Filesystem Status ==={Style.RESET_ALL}")
    
    base_data_dir = config.get("BASE_DATA_DIR")
    evidence_dir = config.get("EVIDENCE_DIR")
    log_dir = config.get("LOG_DIR")
    
    # Check base data directory
    if os.path.exists(base_data_dir):
        print(f"{Fore.GREEN}✓ Base data directory exists: {base_data_dir}{Style.RESET_ALL}")
        print(f"  Size: {get_directory_size(base_data_dir)}")
    else:
        print(f"{Fore.RED}✗ Base data directory not found: {base_data_dir}{Style.RESET_ALL}")
    
    # Check evidence directory
    if os.path.exists(evidence_dir):
        print(f"\n{Fore.GREEN}✓ Evidence directory exists: {evidence_dir}{Style.RESET_ALL}")
        print(f"  Size: {get_directory_size(evidence_dir)}")
        
        # Count job evidence directories
        job_dirs = list(Path(evidence_dir).glob("job_*"))
        print(f"  Job evidence directories: {len(job_dirs)}")
        
        # List recent job evidence directories
        recent_job_dirs = sorted(job_dirs, key=os.path.getmtime, reverse=True)[:5]
        if recent_job_dirs:
            print(f"\n{Fore.YELLOW}Recent Evidence Directories:{Style.RESET_ALL}")
            evidence_table = []
            for dir_path in recent_job_dirs:
                job_id = dir_path.name.replace("job_", "")
                evidence_table.append([
                    job_id,
                    get_directory_size(dir_path),
                    get_file_modified_time(dir_path)
                ])
            
            print(format_table(evidence_table, ["Job ID", "Size", "Modified"]))
    else:
        print(f"{Fore.RED}✗ Evidence directory not found: {evidence_dir}{Style.RESET_ALL}")
    
    # Check log directory
    if os.path.exists(log_dir):
        print(f"\n{Fore.GREEN}✓ Log directory exists: {log_dir}{Style.RESET_ALL}")
        print(f"  Size: {get_directory_size(log_dir)}")
        
        # List log files
        log_files = list(Path(log_dir).glob("*.log"))
        automation_log_files = list(Path(log_dir).glob("automation/*.log"))
        
        if log_files or automation_log_files:
            print(f"\n{Fore.YELLOW}Log Files:{Style.RESET_ALL}")
            log_table = []
            for log_file in log_files + automation_log_files:
                log_table.append([
                    log_file.name,
                    get_file_size(log_file),
                    get_file_modified_time(log_file)
                ])
            
            print(format_table(log_table, ["Filename", "Size", "Modified"]))
            
            # Check for errors in recent logs
            orchestrator_log = os.path.join(log_dir, "orchestrator.log")
            worker_log = os.path.join(log_dir, "worker.log")
            
            if os.path.exists(orchestrator_log):
                error_count = count_errors_in_log(orchestrator_log)
                print(f"\n{Fore.YELLOW}Recent Errors in Orchestrator Log: {error_count}{Style.RESET_ALL}")
                if error_count > 0:
                    recent_errors = get_recent_errors(orchestrator_log, 3)
                    for error in recent_errors:
                        wrapped_error = textwrap.fill(error, width=100, initial_indent="  ", subsequent_indent="  ")
                        print(f"{Fore.RED}{wrapped_error}{Style.RESET_ALL}")
            
            if os.path.exists(worker_log):
                error_count = count_errors_in_log(worker_log)
                print(f"\n{Fore.YELLOW}Recent Errors in Worker Log: {error_count}{Style.RESET_ALL}")
                if error_count > 0:
                    recent_errors = get_recent_errors(worker_log, 3)
                    for error in recent_errors:
                        wrapped_error = textwrap.fill(error, width=100, initial_indent="  ", subsequent_indent="  ")
                        print(f"{Fore.RED}{wrapped_error}{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}✗ Log directory not found: {log_dir}{Style.RESET_ALL}")
    
    return True

# Helper functions
def get_file_size(file_path):
    """Get human-readable file size"""
    try:
        size_bytes = os.path.getsize(file_path)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"
    except Exception:
        return "Unknown"

def get_directory_size(dir_path):
    """Get human-readable directory size"""
    try:
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(dir_path):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                if os.path.exists(file_path):
                    total_size += os.path.getsize(file_path)
        
        # Convert to human-readable format
        for unit in ['B', 'KB', 'MB', 'GB']:
            if total_size < 1024.0:
                return f"{total_size:.2f} {unit}"
            total_size /= 1024.0
        return f"{total_size:.2f} TB"
    except Exception:
        return "Unknown"

def get_file_modified_time(file_path):
    """Get formatted file modification time"""
    try:
        mtime = os.path.getmtime(file_path)
        dt = datetime.datetime.fromtimestamp(mtime)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "Unknown"

def format_date(date_string):
    """Format ISO date string to readable format"""
    if not date_string:
        return "N/A"
    
    try:
        # Handle different date formats
        if 'T' in date_string:
            # ISO format with T separator
            dt = datetime.datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        else:
            # Try standard formats
            try:
                dt = datetime.datetime.strptime(date_string, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                dt = datetime.datetime.strptime(date_string, "%Y-%m-%d %H:%M:%S.%f")
        
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return date_string

def get_runtime(start_time_str):
    """Calculate runtime from start time to now"""
    if not start_time_str:
        return "N/A"
    
    try:
        # Parse the start time
        if 'T' in start_time_str:
            # ISO format with T separator
            start_time = datetime.datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
        else:
            # Try standard formats
            try:
                start_time = datetime.datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                start_time = datetime.datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S.%f")
        
        # Calculate the difference
        now = datetime.datetime.now()
        if start_time.tzinfo:
            now = now.replace(tzinfo=start_time.tzinfo)
        
        delta = now - start_time
        
        # Format the duration
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if delta.days > 0:
            return f"{delta.days}d {hours}h {minutes}m"
        else:
            return f"{hours}h {minutes}m {seconds}s"
    except Exception:
        return "Unknown"

def count_errors_in_log(log_file, max_lines=1000):
    """Count ERROR level entries in the log file"""
    try:
        error_count = 0
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            # Read last N lines
            lines = list(f)[-max_lines:]
            for line in lines:
                if "[ERROR]" in line:
                    error_count += 1
        return error_count
    except Exception:
        return 0

def get_recent_errors(log_file, count=3, max_lines=1000):
    """Get recent ERROR messages from log file"""
    try:
        errors = []
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            # Read last N lines
            lines = list(f)[-max_lines:]
            for line in lines:
                if "[ERROR]" in line:
                    errors.append(line.strip())
                    if len(errors) >= count:
                        break
        return errors
    except Exception:
        return []

def main():
    """Main function to run system status checks"""
    parser = argparse.ArgumentParser(description="RPA System Status Checker")
    parser.add_argument("--job", type=int, help="Check detailed history for a specific job ID")
    parser.add_argument("--db-only", action="store_true", help="Only check database status")
    parser.add_argument("--orchestrator-only", action="store_true", help="Only check orchestrator status")
    parser.add_argument("--workers-only", action="store_true", help="Only check workers status")
    parser.add_argument("--filesystem-only", action="store_true", help="Only check filesystem status")
    
    args = parser.parse_args()
    
    # Load configuration from .env
    config = load_config()
    
    print(f"{Fore.CYAN}=== RPA System Status Report ==={Style.RESET_ALL}")
    print(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Configuration from: {os.path.abspath('.env')}\n")
    
    # If checking specific job, only do that
    if args.job:
        check_job_history(config, args.job)
        return
    
    # Check specified components or all if none specified
    run_all = not any([args.db_only, args.orchestrator_only, args.workers_only, args.filesystem_only])
    
    if run_all or args.orchestrator_only:
        check_orchestrator(config)
    
    if run_all or args.workers_only:
        check_workers(config)
    
    if run_all or args.db_only:
        check_database(config)
    
    if run_all or args.filesystem_only:
        check_filesystem(config)
    
    print(f"\n{Fore.CYAN}=== Status Check Complete ==={Style.RESET_ALL}")

if __name__ == "__main__":
    main()