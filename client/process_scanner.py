import hashlib
import psutil

def scan_for_forbidden_processes(log_data, forbidden_processes, reported_alerts):
    """
    log_data: dict from get_activity_log
    forbidden_processes: list of {process_name, severity, description}
    reported_alerts: set of alert identity hashes already sent
    Returns: list of new alert candidates, updated reported_alerts
    """
    new_alerts = []
    
    for fb in forbidden_processes:
        process_name = fb["process_name"]
        
        # 1. Scan activity log
        if log_data and "activity" in log_data:
            for entry in log_data["activity"]:
                if process_name.lower() in entry["detail"].lower() or process_name.lower() in entry["type"].lower():
                    time_str = entry["time"]
                    detail = entry.get("detail", "")
                    alert_id = hashlib.sha256(
                        f"{process_name}\0{time_str}\0{detail}".encode()
                    ).hexdigest()
                    if alert_id not in reported_alerts:
                        reported_alerts.add(alert_id)
                        new_alerts.append({
                            "alert_type": "FORBIDDEN_PROCESS",
                            "severity": fb["severity"],
                            "title": f"Forbidden process detected: {process_name}",
                            "description": fb.get("description", f"Forbidden process '{process_name}' was detected in activity log."),
                            "process_name": process_name,
                            "activity_time": time_str
                        })
        
        # 2. Scan running processes
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = proc.info["name"]
                if name and process_name.lower() in name.lower():
                    # For running processes, use current hour as time context to avoid spamming
                    time_str = "CURRENTLY_RUNNING"
                    alert_id = hashlib.md5(f"{process_name}_{time_str}".encode()).hexdigest()
                    if alert_id not in reported_alerts:
                        reported_alerts.add(alert_id)
                        new_alerts.append({
                            "alert_type": "FORBIDDEN_PROCESS",
                            "severity": fb["severity"],
                            "title": f"Forbidden process running: {process_name}",
                            "description": fb.get("description", f"Forbidden process '{process_name}' is currently running."),
                            "process_name": process_name,
                            "activity_time": None
                        })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
                
    # Limit set size
    if len(reported_alerts) > 1000:
        reported_alerts = set(list(reported_alerts)[-500:])
        
    return new_alerts, reported_alerts
