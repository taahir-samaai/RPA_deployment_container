#!/usr/bin/env python3
"""Enhanced Health Reporter for OGGIES_LOG Integration"""

import json
import requests
import psutil
import socket
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Alert:
    """Alert threshold configuration"""
    warn: float
    crit: float
    op: str = "gt"  # gt=greater than, lt=less than
    
    def check(self, val: float) -> Optional[str]:
        if self.op == "gt":
            return "critical" if val >= self.crit else "warning" if val >= self.warn else None
        return "critical" if val <= self.crit else "warning" if val <= self.warn else None


@dataclass 
class HealthReporter:
    """Streamlined health reporter with categorized metrics and alerting"""
    endpoint: str
    server_type: str = "Worker"
    hostname: str = field(default_factory=socket.gethostname)
    db_path: Optional[str] = None  # Will auto-detect if not provided
    
    def __post_init__(self):
        self.alerts = {
            "sys_cpu": Alert(80, 95),
            "sys_mem": Alert(85, 95),
            "sys_disk": Alert(85, 95),
            "sys_load1": Alert(4, 8),
            "net_errors": Alert(100, 1000),
            "job_failed_rate": Alert(10, 25),  # Warning at 10%, critical at 25%
            "job_queue_depth": Alert(50, 100),  # Warning at 50 jobs, critical at 100
        }
        self.errors = []
        
        # Auto-detect database path if not provided
        if not self.db_path:
            if self.server_type == "Orchestrator":
                # Standard orchestrator DB location
                self.db_path = "./data/db/orchestrator.db"
            else:
                # Standard worker DB location
                self.db_path = "./worker_data/job_status.sqlite"
    
    def _safe(self, func, name: str) -> Any:
        """Safe metric collection wrapper"""
        try:
            return func()
        except Exception as e:
            self.errors.append(f"{name}: {e}")
            return None
    
    def collect_job_metrics(self) -> Dict[str, Any]:
        """Collect job-related metrics from database"""
        m = {}
        
        if self.server_type == "Orchestrator":
            # Query orchestrator database for comprehensive job stats
            try:
                if Path(self.db_path).exists():
                    with sqlite3.connect(self.db_path) as conn:
                        # Current job status counts
                        cursor = conn.execute("""
                            SELECT status, COUNT(*) 
                            FROM job_queue 
                            GROUP BY status
                        """)
                        status_counts = dict(cursor.fetchall())
                        
                        m["job_pending"] = status_counts.get("pending", 0)
                        m["job_running"] = status_counts.get("running", 0) + status_counts.get("dispatching", 0)
                        m["job_completed"] = status_counts.get("completed", 0)
                        m["job_failed"] = status_counts.get("failed", 0) + status_counts.get("error", 0)
                        m["job_retry_pending"] = status_counts.get("retry_pending", 0)
                        m["job_cancelled"] = status_counts.get("cancelled", 0)
                        
                        # Total jobs for calculating rates
                        total = sum(status_counts.values())
                        m["job_total"] = total
                        
                        # Queue depth (pending + retry_pending)
                        m["job_queue_depth"] = m["job_pending"] + m["job_retry_pending"]
                        
                        # Failure rate
                        if total > 0:
                            m["job_failed_rate"] = round((m["job_failed"] / total) * 100, 2)
                        
                        # Recent job activity (last hour)
                        cursor = conn.execute("""
                            SELECT COUNT(*) 
                            FROM job_queue 
                            WHERE datetime(created_at) > datetime('now', '-1 hour')
                        """)
                        m["job_created_1h"] = cursor.fetchone()[0]
                        
                        cursor = conn.execute("""
                            SELECT COUNT(*) 
                            FROM job_queue 
                            WHERE datetime(completed_at) > datetime('now', '-1 hour')
                        """)
                        m["job_completed_1h"] = cursor.fetchone()[0]
                        
                        # Average job duration (completed jobs in last 24h)
                        cursor = conn.execute("""
                            SELECT AVG(
                                (julianday(completed_at) - julianday(started_at)) * 86400
                            ) 
                            FROM job_queue 
                            WHERE status = 'completed' 
                            AND completed_at IS NOT NULL 
                            AND started_at IS NOT NULL
                            AND datetime(completed_at) > datetime('now', '-24 hours')
                        """)
                        avg_duration = cursor.fetchone()[0]
                        if avg_duration:
                            m["job_avg_duration_sec"] = round(avg_duration, 2)
                        
                        # Job throughput per hour
                        if m["job_completed_1h"] > 0:
                            m["job_throughput_per_hour"] = m["job_completed_1h"]
                        
                        # Worker assignments
                        cursor = conn.execute("""
                            SELECT assigned_worker, COUNT(*) 
                            FROM job_queue 
                            WHERE status IN ('running', 'dispatching')
                            AND assigned_worker IS NOT NULL
                            GROUP BY assigned_worker
                        """)
                        worker_loads = dict(cursor.fetchall())
                        m["job_active_workers"] = len(worker_loads)
                        
            except Exception as e:
                self.errors.append(f"job_metrics_orch: {e}")
        
        else:  # Worker
            # Query worker database for local job execution stats
            try:
                if Path(self.db_path).exists():
                    with sqlite3.connect(self.db_path) as conn:
                        # Count job statuses
                        cursor = conn.execute("""
                            SELECT status, COUNT(*) 
                            FROM job_status 
                            GROUP BY status
                        """)
                        status_counts = dict(cursor.fetchall())
                        
                        m["job_local_success"] = status_counts.get("success", 0)
                        m["job_local_error"] = status_counts.get("error", 0)
                        m["job_local_in_progress"] = status_counts.get("in_progress", 0)
                        
                        total = sum(status_counts.values())
                        m["job_local_total"] = total
                        
                        # Local failure rate
                        if total > 0:
                            m["job_local_error_rate"] = round((m["job_local_error"] / total) * 100, 2)
                        
                        # Recent activity (last hour)
                        cursor = conn.execute("""
                            SELECT COUNT(*) 
                            FROM job_status 
                            WHERE datetime(start_time) > datetime('now', '-1 hour')
                        """)
                        m["job_local_started_1h"] = cursor.fetchone()[0]
                        
                        # Average execution time
                        cursor = conn.execute("""
                            SELECT AVG(
                                (julianday(end_time) - julianday(start_time)) * 86400
                            )
                            FROM job_status 
                            WHERE status = 'success' 
                            AND end_time IS NOT NULL 
                            AND start_time IS NOT NULL
                        """)
                        avg_exec = cursor.fetchone()[0]
                        if avg_exec:
                            m["job_local_avg_exec_sec"] = round(avg_exec, 2)
                        
            except Exception as e:
                self.errors.append(f"job_metrics_worker: {e}")
        
        return m
    
    def collect_metrics(self) -> Dict[str, Any]:
        """Collect all system, network, and job metrics"""
        m = {}
        
        # System metrics
        cpu = self._safe(lambda: psutil.cpu_percent(interval=1), "cpu")
        if cpu is not None:
            m["sys_cpu"] = round(cpu, 2)
        
        load = self._safe(psutil.getloadavg, "load")
        if load:
            m.update({f"sys_load{i}": round(v, 2) for i, v in zip([1, 5, 15], load)})
        
        mem = self._safe(psutil.virtual_memory, "memory")
        if mem:
            m.update({
                "sys_mem": round(mem.percent, 2),
                "sys_mem_used_gb": round(mem.used / 1073741824, 2),
                "sys_mem_avail_gb": round(mem.available / 1073741824, 2),
            })
        
        disk = self._safe(lambda: psutil.disk_usage('/'), "disk")
        if disk:
            m.update({
                "sys_disk": round(disk.percent, 2),
                "sys_disk_free_gb": round(disk.free / 1073741824, 2),
            })
        
        # Network metrics
        net = self._safe(psutil.net_io_counters, "network")
        if net:
            m.update({
                "net_bytes_recv_mb": round(net.bytes_recv / 1048576, 2),
                "net_bytes_sent_mb": round(net.bytes_sent / 1048576, 2),
                "net_packets_recv": net.packets_recv,
                "net_packets_sent": net.packets_sent,
                "net_errors": net.errin + net.errout + net.dropin + net.dropout,
            })
        
        # Basic app metrics
        m.update({
            "app_uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 2),
            "app_processes": len(psutil.pids()),
        })
        
        # Job metrics from database
        job_metrics = self.collect_job_metrics()
        m.update(job_metrics)
        
        # Orchestrator-specific extras
        if self.server_type == "Orchestrator" and "job_active_workers" in m:
            m["orch_workers"] = m["job_active_workers"]
            m["orch_queue"] = m.get("job_queue_depth", 0)
        
        return m
    
    def check_alerts(self, metrics: Dict[str, Any]) -> list:
        """Check metrics against alert thresholds"""
        alerts = []
        for key, threshold in self.alerts.items():
            if key in metrics:
                level = threshold.check(metrics[key])
                if level:
                    alerts.append(f"{key}_{level}")
        return alerts
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate complete health report for OGGIES_LOG"""
        start = time.time()
        self.errors = []
        
        metrics = self.collect_metrics()
        alerts = self.check_alerts(metrics)
        
        # Build OBJ_EVI JSON
        evi = {
            "Object_name": self.hostname,
            "Object_type": self.server_type,
            "Object_date": datetime.now().strftime("%Y/%m/%d %H:%M"),
            "Action": "Heartbeat",
            "Status": "Degraded" if alerts else "Up",
            "Comment": f"{len(metrics)} metrics collected",
            "health_status": "partial" if self.errors else "success",
            "health_errors": self.errors,
            "collection_time": round(time.time() - start, 3),
            "alerts": alerts,
            "alert_count": len(alerts),
            **metrics
        }
        
        # ORDS payload
        return {
            "job_id": f"HB_{self.hostname}_{int(datetime.now().timestamp())}",
            "obj_name": self.hostname,
            "obj_type": self.server_type,
            "evidence": json.dumps(evi)
        }
    
    def send(self) -> bool:
        """Send report to ORDS endpoint"""
        try:
            payload = self.generate_report()
            resp = requests.post(
                self.endpoint,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            if resp.status_code == 200:
                print(f"✓ Report sent: {payload['job_id']}")
                return True
            else:
                print(f"✗ ORDS error {resp.status_code}: {resp.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"✗ Connection error: {e}")
            return False
        except Exception as e:
            print(f"✗ Unexpected error: {e}")
            return False
    
    def test(self) -> Dict[str, Any]:
        """Generate report for local testing"""
        return self.generate_report()


if __name__ == "__main__":
    # Test locally
    import sys
    
    # Allow command line override of server type
    server_type = sys.argv[1] if len(sys.argv) > 1 else "Worker"
    
    reporter = HealthReporter(
        endpoint="http://localhost:8080/ords/endpoint",
        server_type=server_type
    )
    report = reporter.test()
    
    evidence = json.loads(report["evidence"])
    
    print(f"\n=== Health Report Test ({server_type}) ===")
    print(f"Job ID: {report['job_id']}")
    print(f"Status: {evidence['Status']}")
    print(f"Alerts: {evidence.get('alerts', [])}")
    print(f"Metrics: {evidence['Comment']}")
    
    # Show categorized metrics
    for prefix in ['sys_', 'net_', 'app_', 'job_', 'orch_']:
        metrics = {k: v for k, v in evidence.items() if k.startswith(prefix)}
        if metrics:
            print(f"\n{prefix.rstrip('_').title()} Metrics:")
            for k, v in metrics.items():
                print(f"  {k}: {v}")
    
    if evidence.get('health_errors'):
        print(f"\nCollection Errors: {evidence['health_errors']}")
    
    print(f"\n=== Full JSON ===")
    print(json.dumps(evidence, indent=2))