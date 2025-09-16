#!/usr/bin/env python
"""
RPA Callback Listener
--------------------
This script creates a simple server to listen for callback notifications
from the RPA orchestration system. It displays and logs all incoming callbacks
to help with monitoring and debugging the system.

Features:
- HTTP server that listens for POST requests with callback data
- Web interface for viewing recent callbacks and statistics
- Console display of incoming callbacks
- Periodic statistics reporting
- Optional logging of all callbacks to a file

Usage:
    python callback_listener.py [--port PORT] [--log-file LOG_FILE] [--stats-interval SECONDS]
"""

import http.server
import socketserver
import json
import logging
import argparse
import os
import time
import signal
import sys
from datetime import datetime
from typing import Dict, Any, Optional
import threading

# Default configuration
DEFAULT_PORT = 8625
DEFAULT_LOG_FILE = "callbacks.log"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger("callback_listener")

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

class CallbackStats:
    """Track statistics about received callbacks."""
    def __init__(self):
        self.total_callbacks = 0
        self.callbacks_by_status = {}
        self.callbacks_by_provider = {}
        self.callbacks_by_hour = {}
        self.callbacks_by_action = {}
        self.processing_times = []  # Track job processing times when available
        self.start_time = datetime.now()
        self.last_callback_time = None
        self.response_times = []  # Time between callbacks
    
    def update(self, data: Dict[str, Any]):
        """Update stats based on a new callback."""
        self.total_callbacks += 1
        current_time = datetime.now()
        
        # Update last callback time and track response times
        if self.last_callback_time:
            time_since_last = (current_time - self.last_callback_time).total_seconds()
            self.response_times.append(time_since_last)
            # Keep only the last 100 response times
            if len(self.response_times) > 100:
                self.response_times = self.response_times[-100:]
        
        self.last_callback_time = current_time
        
        # Track by status
        status = data.get("STATUS", "unknown")
        self.callbacks_by_status[status] = self.callbacks_by_status.get(status, 0) + 1
        
        # Track by provider
        provider = data.get("FNO", "unknown")
        self.callbacks_by_provider[provider] = self.callbacks_by_provider.get(provider, 0) + 1
        
        # Track by hour (for rate analysis)
        hour = current_time.strftime("%Y-%m-%d %H:00")
        self.callbacks_by_hour[hour] = self.callbacks_by_hour.get(hour, 0) + 1
        
        # Try to extract action type
        job_details = data.get("JOB_EVI", {})
        circuit_number = job_details.get("Circuit Number", "unknown")
        if "cancellation" in circuit_number.lower() or "cancel" in str(data).lower():
            action = "cancellation"
        elif "validation" in str(data).lower() or "validate" in str(data).lower():
            action = "validation"
        else:
            action = "other"
        
        self.callbacks_by_action[action] = self.callbacks_by_action.get(action, 0) + 1
        
        # Try to calculate processing time if timestamps available
        if "STATUS_DT" in data and job_details.get("Activation Date"):
            try:
                # These formats would need to match what your system provides
                end_time = datetime.strptime(data["STATUS_DT"], "%Y/%m/%d %H:%M:%S")
                start_time = datetime.strptime(job_details["Activation Date"], "%Y/%m/%d %H:%M:%S")
                processing_seconds = (end_time - start_time).total_seconds()
                if processing_seconds > 0:
                    self.processing_times.append(processing_seconds)
                    # Keep only the last 100 processing times
                    if len(self.processing_times) > 100:
                        self.processing_times = self.processing_times[-100:]
            except (ValueError, TypeError):
                # Date parsing failed, just skip it
                pass
    
    def get_average_processing_time(self):
        """Calculate average job processing time."""
        if not self.processing_times:
            return None
        return sum(self.processing_times) / len(self.processing_times)
    
    def get_average_response_time(self):
        """Calculate average time between callbacks."""
        if not self.response_times:
            return None
        return sum(self.response_times) / len(self.response_times)
    
    def get_callback_rate(self):
        """Calculate callback rate per hour (recent)."""
        if not self.callbacks_by_hour:
            return 0
        
        # Get counts for the last 3 hours
        recent_hours = sorted(self.callbacks_by_hour.keys())[-3:]
        recent_count = sum(self.callbacks_by_hour.get(hour, 0) for hour in recent_hours)
        
        # Avoid division by zero
        if not recent_count:
            return 0
            
        return recent_count / len(recent_hours)
    
    def export_to_json(self) -> Dict:
        """Export statistics as JSON."""
        return {
            "total_callbacks": self.total_callbacks,
            "uptime_seconds": (datetime.now() - self.start_time).total_seconds(),
            "average_processing_time": self.get_average_processing_time(),
            "average_response_time": self.get_average_response_time(),
            "callback_rate_per_hour": self.get_callback_rate(),
            "callbacks_by_status": self.callbacks_by_status,
            "callbacks_by_provider": self.callbacks_by_provider,
            "callbacks_by_action": self.callbacks_by_action,
            "callbacks_by_hour": self.callbacks_by_hour,
        }
    
    def display(self):
        """Display current stats to console."""
        uptime = datetime.now() - self.start_time
        
        print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.BLUE}= Callback Listener Statistics{Colors.END}")
        print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.END}")
        print(f"Uptime: {uptime}")
        print(f"Total callbacks received: {self.total_callbacks}")
        
        # Show rate information
        callback_rate = self.get_callback_rate()
        print(f"\nCallback Rate: {callback_rate:.2f} per hour")
        
        # Show average times
        avg_proc_time = self.get_average_processing_time()
        if avg_proc_time:
            print(f"Average Processing Time: {avg_proc_time:.2f} seconds")
        
        avg_resp_time = self.get_average_response_time()
        if avg_resp_time:
            print(f"Average Time Between Callbacks: {avg_resp_time:.2f} seconds")
        
        if self.callbacks_by_status:
            print("\nCallbacks by Status:")
            for status, count in sorted(self.callbacks_by_status.items(), key=lambda x: x[1], reverse=True):
                # Color based on status
                color = Colors.GREEN
                if status.lower() in ["failed", "error"]:
                    color = Colors.RED
                elif status.lower() in ["pending", "dispatching"]:
                    color = Colors.YELLOW
                
                percentage = (count / self.total_callbacks) * 100
                print(f"  - {color}{status}{Colors.END}: {count} ({percentage:.1f}%)")
        
        if self.callbacks_by_provider:
            print("\nCallbacks by Provider:")
            for provider, count in sorted(self.callbacks_by_provider.items(), key=lambda x: x[1], reverse=True):
                percentage = (count / self.total_callbacks) * 100
                print(f"  - {provider}: {count} ({percentage:.1f}%)")
        
        if self.callbacks_by_action:
            print("\nCallbacks by Action Type:")
            for action, count in sorted(self.callbacks_by_action.items(), key=lambda x: x[1], reverse=True):
                percentage = (count / self.total_callbacks) * 100
                print(f"  - {action}: {count} ({percentage:.1f}%)")
        
        print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.END}\n")

class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for callback requests."""
    
    # Class-level storage for callback data
    callbacks = []
    stats = CallbackStats()
    
    def log_message(self, format, *args):
        """Override to use our logger instead of stderr."""
        logger.info("%s - %s", self.address_string(), format % args)
    
    def _set_response(self, status_code=200, content_type="application/json"):
        """Set the HTTP response headers."""
        self.send_response(status_code)
        self.send_header('Content-type', content_type)
        self.end_headers()
    
    def do_GET(self):
        """Handle GET requests - display statistics or export data."""
        # Parse query parameters
        import urllib.parse as urlparse
        from urllib.parse import parse_qs
        
        # Parse the URL and get query parameters
        parsed_url = urlparse.urlparse(self.path)
        query_params = parse_qs(parsed_url.query)
        
        # Check for export request
        if parsed_url.path == "/export":
            format_type = query_params.get('format', ['json'])[0]
            if format_type == 'json':
                self._export_json()
            elif format_type == 'csv':
                self._export_csv()
            else:
                self._set_response(400)
                self.wfile.write(b'Invalid export format. Use "json" or "csv".')
            return
            
        # Check for API stats request
        if parsed_url.path == "/api/stats":
            self._export_stats_json()
            return
            
        # Check for API callbacks request
        if parsed_url.path == "/api/callbacks":
            self._export_callbacks_json(query_params)
            return
            
        # Default: display HTML dashboard
        self._display_html_dashboard(query_params)
    
    def do_POST(self):
        """Handle POST requests - process callbacks."""
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode('utf-8'))
            
            # Log the callback
            now = datetime.now()
            timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
            
            # Store complete callback with timestamp
            callback_record = {
                "time": timestamp,
                "data": data
            }
            
            # Display the callback
            self._display_callback(callback_record)
            
            # Add to in-memory storage
            self.callbacks.append(callback_record)
            if len(self.callbacks) > 1000:  # Limit storage
                self.callbacks = self.callbacks[-1000:]
            
            # Update statistics
            self.stats.update(data)
            
            # Log to file if configured
            if hasattr(self.server, 'log_file') and self.server.log_file:
                with open(self.server.log_file, 'a') as f:
                    f.write(f"[{timestamp}] {json.dumps(data)}\n")
            
            # Send response
            self._set_response()
            response = {"status": "success", "message": "Callback received"}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {str(e)}")
            self._set_response(400)
            response = {"status": "error", "message": f"Invalid JSON: {str(e)}"}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            
        except Exception as e:
            logger.error(f"Error processing callback: {str(e)}")
            self._set_response(500)
            response = {"status": "error", "message": f"Error: {str(e)}"}
            self.wfile.write(json.dumps(response).encode('utf-8'))
    
    def _display_callback(self, callback_record: Dict):
        """Display a formatted callback in the console."""
        data = callback_record["data"]
        timestamp = callback_record["time"]
        print(data)
        # Extract key fields
        job_id = data.get("JOB_ID", "N/A")
        ext_id = data.get("EXTERNAL_JOB_ID", "N/A")
        provider = data.get("FNO", "N/A")
        status = data.get("STATUS", "N/A")
        status_dt = data.get("STATUS_DT", "N/A")
        
        # Determine status color
        status_color = Colors.BLUE
        if status.lower() in ["completed", "success"]:
            status_color = Colors.GREEN
        elif status.lower() in ["failed", "error"]:
            status_color = Colors.RED
        elif status.lower() in ["pending", "dispatching"]:
            status_color = Colors.YELLOW
        
        # Display header
        print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 80}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.CYAN}= CALLBACK RECEIVED @ {timestamp}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 80}{Colors.END}")
        
        # Display basic info
        print(f"Job ID: {Colors.BOLD}{job_id}{Colors.END}")
        print(f"External ID: {ext_id}")
        print(f"Provider: {provider}")
        print(f"Status: {status_color}{status}{Colors.END}")
        print(f"Status Date: {status_dt}")
        
        # Display evidence details if present
        job_evi = data.get("JOB_EVI", {})
        if job_evi:
            print(f"\n{Colors.BOLD}Job Evidence:{Colors.END}")
            for key, value in job_evi.items():
                print(f"  - {key}: {value}")
        
        print(f"{Colors.CYAN}{'=' * 80}{Colors.END}")

    def _export_json(self):
        """Export all callbacks as JSON."""
        self._set_response(content_type="application/json")
        
        export_data = {
            "metadata": {
                "total_callbacks": len(self.callbacks),
                "export_time": datetime.now().isoformat(),
                "uptime": str(datetime.now() - self.stats.start_time)
            },
            "callbacks": self.callbacks
        }
        
        self.wfile.write(json.dumps(export_data, indent=2).encode('utf-8'))
    
    def _export_csv(self):
        """Export callbacks as CSV."""
        import csv
        import io
        
        self._set_response(content_type="text/csv")
        self.send_header('Content-Disposition', 'attachment; filename="callbacks.csv"')
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            "Timestamp", "Job ID", "External ID", "Provider", "Status", 
            "Customer Name", "Account", "Circuit Number", "Address", "Package"
        ])
        
        # Write data
        for callback in self.callbacks:
            data = callback.get("data", {})
            job_evi = data.get("JOB_EVI", {})
            
            writer.writerow([
                callback.get("time", ""),
                data.get("JOB_ID", ""),
                data.get("EXTERNAL_JOB_ID", ""),
                data.get("FNO", ""),
                data.get("STATUS", ""),
                job_evi.get("Customer_Name", ""),
                job_evi.get("Account", ""),
                job_evi.get("Circuit Number", ""),
                job_evi.get("Address", ""),
                job_evi.get("Package", "")
            ])
        
        self.wfile.write(output.getvalue().encode('utf-8'))
    
    def _export_stats_json(self):
        """Export stats as JSON."""
        self._set_response(content_type="application/json")
        
        # Get stats as JSON
        stats_data = self.stats.export_to_json()
        
        self.wfile.write(json.dumps(stats_data, indent=2).encode('utf-8'))
    
    def _export_callbacks_json(self, query_params):
        """Export filtered callbacks as JSON."""
        self._set_response(content_type="application/json")
        
        # Parse filters
        status_filter = query_params.get('status', [None])[0]
        provider_filter = query_params.get('provider', [None])[0]
        limit = min(int(query_params.get('limit', [50])[0]), 1000)
        
        # Filter callbacks
        filtered_callbacks = self.callbacks
        
        if status_filter:
            filtered_callbacks = [
                cb for cb in filtered_callbacks 
                if cb.get("data", {}).get("STATUS", "").lower() == status_filter.lower()
            ]
            
        if provider_filter:
            filtered_callbacks = [
                cb for cb in filtered_callbacks 
                if cb.get("data", {}).get("FNO", "").lower() == provider_filter.lower()
            ]
        
        # Apply limit (most recent first)
        filtered_callbacks = filtered_callbacks[-limit:] if limit > 0 else filtered_callbacks
        
        export_data = {
            "metadata": {
                "total_callbacks": len(self.callbacks),
                "filtered_callbacks": len(filtered_callbacks),
                "filters": {
                    "status": status_filter,
                    "provider": provider_filter,
                    "limit": limit
                },
                "export_time": datetime.now().isoformat()
            },
            "callbacks": filtered_callbacks
        }
        
        self.wfile.write(json.dumps(export_data, indent=2).encode('utf-8'))
    
    def _display_html_dashboard(self, query_params):
        """Display HTML dashboard with optional filters."""
        self._set_response(content_type="text/html")
        
        # Parse filters
        status_filter = query_params.get('status', [None])[0]
        provider_filter = query_params.get('provider', [None])[0]
        limit = min(int(query_params.get('limit', [50])[0]), 200)
        auto_refresh = query_params.get('refresh', ['true'])[0].lower() == 'true'
        
        # Filter callbacks
        filtered_callbacks = self.callbacks
        
        if status_filter:
            filtered_callbacks = [
                cb for cb in filtered_callbacks 
                if cb.get("data", {}).get("STATUS", "").lower() == status_filter.lower()
            ]
            
        if provider_filter:
            filtered_callbacks = [
                cb for cb in filtered_callbacks 
                if cb.get("data", {}).get("FNO", "").lower() == provider_filter.lower()
            ]
        
        # Apply limit (most recent first)
        display_callbacks = list(reversed(filtered_callbacks[-limit:] if limit > 0 else filtered_callbacks))
        
        # Get unique statuses and providers for filter dropdowns
        all_statuses = set()
        all_providers = set()
        for callback in self.callbacks:
            data = callback.get("data", {})
            all_statuses.add(data.get("STATUS", "unknown"))
            all_providers.add(data.get("FNO", "unknown"))
        
        # Build HTML
        html_content = f"""
        <html>
        <head>
            <title>RPA Callback Listener</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1 {{ color: #2c3e50; }}
                .stats {{ margin-bottom: 20px; }}
                .callbacks {{ margin-top: 20px; }}
                .filters {{ margin-bottom: 20px; padding: 10px; background-color: #f5f5f5; border-radius: 5px; }}
                .filter-group {{ margin-right: 15px; display: inline-block; }}
                .actions {{ margin-top: 10px; margin-bottom: 10px; }}
                .btn {{ padding: 5px 10px; background-color: #3498db; color: white; border: none; 
                       border-radius: 3px; cursor: pointer; text-decoration: none; display: inline-block; margin-right: 5px; }}
                .btn:hover {{ background-color: #2980b9; }}
                .btn-reset {{ background-color: #e74c3c; }}
                .btn-reset:hover {{ background-color: #c0392b; }}
                .btn-export {{ background-color: #2ecc71; }}
                .btn-export:hover {{ background-color: #27ae60; }}
                .refresh-toggle {{ margin-left: 15px; }}
                
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; position: sticky; top: 0; }}
                tr:nth-child(even) {{ background-color: #f9f9f9; }}
                .status-completed {{ color: green; }}
                .status-failed {{ color: red; }}
                .status-pending {{ color: orange; }}
                pre {{ background-color: #f8f8f8; padding: 10px; overflow: auto; max-height: 200px; }}
                .callback-table {{ max-height: 600px; overflow-y: auto; }}
                .meter {{ height: 10px; background: #e74c3c; width: 0%; }}
                
                .card {{ background: white; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); 
                       padding: 15px; margin-bottom: 20px; }}
                .card-metric {{ display: inline-block; width: 23%; margin-right: 1%; text-align: center; }}
                .metric-value {{ font-size: 24px; font-weight: bold; margin: 10px 0; }}
                .metric-label {{ font-size: 14px; color: #7f8c8d; }}
            </style>
            <script>
                function refreshPage() {{
                    if (document.getElementById('autoRefresh').checked) {{
                        location.reload();
                    }}
                }}
                
                function updateFilterUrl() {{
                    const statusFilter = document.getElementById('statusFilter').value;
                    const providerFilter = document.getElementById('providerFilter').value;
                    const limitFilter = document.getElementById('limitFilter').value;
                    const autoRefresh = document.getElementById('autoRefresh').checked;
                    
                    let url = '?';
                    if (statusFilter) url += 'status=' + encodeURIComponent(statusFilter) + '&';
                    if (providerFilter) url += 'provider=' + encodeURIComponent(providerFilter) + '&';
                    if (limitFilter) url += 'limit=' + encodeURIComponent(limitFilter) + '&';
                    url += 'refresh=' + autoRefresh;
                    
                    window.location.href = url;
                }}
                
                window.onload = function() {{
                    // Auto-refresh every 10 seconds if enabled
                    {"setTimeout(refreshPage, 10000);" if auto_refresh else ""}
                    
                    // Update form fields from query params
                    const urlParams = new URLSearchParams(window.location.search);
                    if (urlParams.has('status')) 
                        document.getElementById('statusFilter').value = urlParams.get('status');
                    if (urlParams.has('provider')) 
                        document.getElementById('providerFilter').value = urlParams.get('provider');
                    if (urlParams.has('limit')) 
                        document.getElementById('limitFilter').value = urlParams.get('limit');
                    if (urlParams.has('refresh')) 
                        document.getElementById('autoRefresh').checked = urlParams.get('refresh') === 'true';
                }};
            </script>
        </head>
        <body>
            <h1>RPA Callback Listener</h1>
            
            <!-- Top Metrics Cards -->
            <div class="stats">
                <div class="card card-metric">
                    <div class="metric-label">Total Callbacks</div>
                    <div class="metric-value">{self.stats.total_callbacks}</div>
                </div>
                <div class="card card-metric">
                    <div class="metric-label">Uptime</div>
                    <div class="metric-value" title="{str(datetime.now() - self.stats.start_time)}">{str(datetime.now() - self.stats.start_time).split('.')[0]}</div>
                </div>
                <div class="card card-metric">
                    <div class="metric-label">Success Rate</div>
                    <div class="metric-value">
                    """
        
        # Calculate success rate
        success_count = self.stats.callbacks_by_status.get("Completed", 0)
        total_completed = sum(count for status, count in self.stats.callbacks_by_status.items() 
                         if status.lower() in ["completed", "failed", "error", "cancelled"])
        success_rate = (success_count / total_completed * 100) if total_completed > 0 else 0
                    
        html_content += f"""
                        {success_rate:.1f}%
                        <div class="meter" style="width: {success_rate}%;"></div>
                    </div>
                </div>
                <div class="card card-metric">
                    <div class="metric-label">Callback Rate</div>
                    <div class="metric-value">{self.stats.get_callback_rate():.1f}/hour</div>
                </div>
            </div>
            
            <!-- Filters -->
            <div class="filters">
                <h3>Filters</h3>
                <div class="filter-group">
                    <label for="statusFilter">Status:</label>
                    <select id="statusFilter">
                        <option value="">All Statuses</option>
        """
        
        # Add status options
        for status in sorted(all_statuses):
            selected = 'selected' if status_filter and status.lower() == status_filter.lower() else ''
            html_content += f'<option value="{status}" {selected}>{status}</option>'
        
        html_content += """
                    </select>
                </div>
                
                <div class="filter-group">
                    <label for="providerFilter">Provider:</label>
                    <select id="providerFilter">
                        <option value="">All Providers</option>
        """
        
        # Add provider options
        for provider in sorted(all_providers):
            selected = 'selected' if provider_filter and provider.lower() == provider_filter.lower() else ''
            html_content += f'<option value="{provider}" {selected}>{provider}</option>'
        
        html_content += f"""
                    </select>
                </div>
                
                <div class="filter-group">
                    <label for="limitFilter">Limit:</label>
                    <select id="limitFilter">
                        <option value="10" {"selected" if limit == 10 else ""}>10</option>
                        <option value="25" {"selected" if limit == 25 else ""}>25</option>
                        <option value="50" {"selected" if limit == 50 else ""}>50</option>
                        <option value="100" {"selected" if limit == 100 else ""}>100</option>
                        <option value="200" {"selected" if limit == 200 else ""}>200</option>
                    </select>
                </div>
                
                <div class="filter-group refresh-toggle">
                    <label for="autoRefresh">Auto-refresh:</label>
                    <input type="checkbox" id="autoRefresh" {"checked" if auto_refresh else ""}>
                </div>
                
                <div class="actions">
                    <button class="btn" onclick="updateFilterUrl()">Apply Filters</button>
                    <a href="/" class="btn btn-reset">Reset</a>
                    <a href="/export?format=json" target="_blank" class="btn btn-export">Export JSON</a>
                    <a href="/export?format=csv" target="_blank" class="btn btn-export">Export CSV</a>
                </div>
            </div>
            
            <div class="stats">
                <div class="card">
                    <h3>Statistics</h3>
                    
                    <div style="display: flex; justify-content: space-between;">
                        <div style="flex: 1;">
                            <h4>Callbacks by Status</h4>
                            <ul>
        """
        
        # Add status stats
        for status, count in sorted(self.stats.callbacks_by_status.items(), key=lambda x: x[1], reverse=True):
            status_class = ""
            if status.lower() in ["completed", "success"]:
                status_class = "status-completed"
            elif status.lower() in ["failed", "error"]:
                status_class = "status-failed"
            elif status.lower() in ["pending", "dispatching"]:
                status_class = "status-pending"
                
            percentage = (count / self.stats.total_callbacks) * 100 if self.stats.total_callbacks > 0 else 0
            html_content += f'<li><span class="{status_class}">{status}</span>: {count} ({percentage:.1f}%)</li>'
        
        html_content += """
                            </ul>
                        </div>
                        
                        <div style="flex: 1;">
                            <h4>Callbacks by Provider</h4>
                            <ul>
        """
        
        # Add provider stats
        for provider, count in sorted(self.stats.callbacks_by_provider.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / self.stats.total_callbacks) * 100 if self.stats.total_callbacks > 0 else 0
            html_content += f'<li>{provider}: {count} ({percentage:.1f}%)</li>'
        
        html_content += """
                            </ul>
                        </div>
                        
                        <div style="flex: 1;">
                            <h4>Callbacks by Action</h4>
                            <ul>
        """
        
        # Add action stats
        for action, count in sorted(self.stats.callbacks_by_action.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / self.stats.total_callbacks) * 100 if self.stats.total_callbacks > 0 else 0
            html_content += f'<li>{action}: {count} ({percentage:.1f}%)</li>'
        
        html_content += """
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
                
            <h3>Callbacks</h3>
            <p>Showing {0} filtered callbacks out of {1} total</p>
            
            <div class="callbacks callback-table">
                <table>
                    <tr>
                        <th>Time</th>
                        <th>Job ID</th>
                        <th>External ID</th>
                        <th>Provider</th>
                        <th>Status</th>
                        <th>Details</th>
                    </tr>
        """.format(len(display_callbacks), len(self.callbacks))
        
        # Add callbacks
        for callback in display_callbacks:
            time_str = callback.get("time", "N/A")
            data = callback.get("data", {})
            job_id = data.get("JOB_ID", "N/A")
            ext_id = data.get("EXTERNAL_JOB_ID", "N/A")
            provider = data.get("FNO", "N/A")
            status = data.get("STATUS", "N/A")
            
            # Determine status class
            status_class = ""
            if status.lower() in ["completed", "success"]:
                status_class = "status-completed"
            elif status.lower() in ["failed", "error"]:
                status_class = "status-failed"
            elif status.lower() in ["pending", "dispatching"]:
                status_class = "status-pending"
            
            # Format details as JSON
            details_json = json.dumps(data.get("JOB_EVI", {}), indent=2)
            
            html_content += f"""
                <tr>
                    <td>{time_str}</td>
                    <td>{job_id}</td>
                    <td>{ext_id}</td>
                    <td>{provider}</td>
                    <td class="{status_class}">{status}</td>
                    <td><pre>{details_json}</pre></td>
                </tr>
            """
        
        html_content += """
                </table>
            </div>
            
            <div style="margin-top: 20px; color: #7f8c8d; font-size: 12px;">
                <p>RPA Callback Listener - API endpoints available at:
                <ul>
                    <li>/api/stats - Get all statistics in JSON format</li>
                    <li>/api/callbacks - Get callbacks with optional filters (?status=X&provider=Y&limit=Z)</li>
                    <li>/export?format=json - Export all callbacks as JSON</li>
                    <li>/export?format=csv - Export all callbacks as CSV</li>
                </ul>
                </p>
            </div>
        </body>
        </html>
        """
        
        self.wfile.write(html_content.encode('utf-8'))

def start_stats_display_thread(stats, interval=60):
    """Start a thread to periodically display statistics."""
    def display_thread():
        while True:
            # Sleep first to allow some initial data to be collected
            time.sleep(interval)
            stats.display()
    
    # Start the thread
    thread = threading.Thread(target=display_thread, daemon=True)
    thread.start()
    return thread

def main():
    """Main function to run the callback listener."""
    parser = argparse.ArgumentParser(description='RPA Callback Listener')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, 
                        help=f'Port to listen on (default: {DEFAULT_PORT})')
    parser.add_argument('--log-file', default=DEFAULT_LOG_FILE, 
                        help=f'Log file for callbacks (default: {DEFAULT_LOG_FILE})')
    parser.add_argument('--stats-interval', type=int, default=60, 
                        help='Interval in seconds for displaying statistics (default: 60)')
    parser.add_argument('--no-log', action='store_true', 
                        help='Disable logging callbacks to file')
    
    args = parser.parse_args()
    
    # Setup logging configuration
    file_handler = None
    if not args.no_log:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(file_handler)
        print(f"Logging callbacks to: {args.log_file}")
    
    # Create server
    server = socketserver.TCPServer(("", args.port), CallbackHandler)
    server.log_file = None if args.no_log else args.log_file
    
    # Setup signal handling for graceful shutdown
    def signal_handler(sig, frame):
        print("\nShutting down server...")
        server.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start stats display thread
    stats_thread = start_stats_display_thread(CallbackHandler.stats, interval=args.stats_interval)
    
    # Start server
    print(f"Starting callback listener on port {args.port}")
    print(f"Web interface available at http://localhost:{args.port}")
    print("Press Ctrl+C to stop")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()
        print("Server stopped")

if __name__ == "__main__":
    main()