#!/usr/bin/env python3
"""
Bot Activity Monitor - Anomalous Bot Usage Detection & Alerting

Monitors for unusual bot behavior patterns:
- Unexpected message volumes and spikes
- Authentication failures and suspicious patterns
- API calls from unknown/suspicious IPs
- Rate limit spikes and quota exhaustion
- Integration with existing rate-limit-proxy at port 18790

This module provides real-time monitoring, threshold-based alerting,
and integration with Mission Control's health system.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, NamedTuple
from dataclasses import dataclass, asdict
from collections import defaultdict, deque
import re
import ipaddress
from statistics import mean, median, stdev

import httpx
import aiohttp

# Configuration
RATE_LIMIT_PROXY_URL = "http://localhost:18790"
MISSION_CONTROL_URL = "http://localhost:3000"
DATA_DIR = Path("data")
MONITOR_STATE_FILE = DATA_DIR / "bot_activity_state.json"
ALERTS_FILE = DATA_DIR / "bot_activity_alerts.json"
LOG_FILE = Path("logs") / "bot_activity_monitor.log"

# Create directories
DATA_DIR.mkdir(exist_ok=True)
LOG_FILE.parent.mkdir(exist_ok=True)

# Monitoring thresholds (configurable)
THRESHOLDS = {
    "message_volume_spike_factor": 3.0,  # Alert if volume > 3x moving average
    "message_volume_window_minutes": 30,   # Moving average window
    "rate_limit_warning_pct": 80.0,       # Warn at 80% of rate limit
    "rate_limit_critical_pct": 95.0,      # Critical at 95% of rate limit  
    "auth_failure_max_per_hour": 10,      # Max auth failures before alert
    "suspicious_ip_threshold": 5,         # Alert if >5 requests from unknown IP
    "ip_geolocation_timeout": 5,          # Seconds to wait for IP geo lookup
    "alert_cooldown_minutes": 15,         # Minutes between duplicate alerts
    "stats_retention_hours": 24,          # Hours to keep detailed stats
}

# Known/trusted IP ranges (customize for your environment)
TRUSTED_IP_RANGES = [
    "127.0.0.0/8",      # localhost
    "10.0.0.0/8",       # Private Class A
    "172.16.0.0/12",    # Private Class B  
    "192.168.0.0/16",   # Private Class C
    "::1/128",          # IPv6 localhost
]

# Alert severity levels
class AlertSeverity:
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

@dataclass
class ActivityMetrics:
    """Current activity metrics snapshot"""
    timestamp: str
    message_count_1min: int
    message_count_5min: int
    message_count_15min: int
    message_count_1hour: int
    rate_limit_requests_used_pct: Optional[float]
    rate_limit_tokens_used_pct: Optional[float]
    auth_failures_1hour: int
    unique_ips_1hour: int
    suspicious_ips_1hour: int
    active_alerts: int

@dataclass  
class Alert:
    """Activity alert record"""
    id: str
    timestamp: str
    severity: str
    category: str  # "volume", "rate_limit", "auth", "suspicious_ip" 
    title: str
    description: str
    metrics: Dict[str, Any]
    resolved: bool = False
    resolved_at: Optional[str] = None

class RateLimitData(NamedTuple):
    """Rate limit data from proxy"""
    requests_used_pct: Optional[float]
    tokens_used_pct: Optional[float]
    total_requests: int
    total_429s: int
    last_429: Optional[str]


class BotActivityMonitor:
    """Main bot activity monitoring class"""
    
    def __init__(self):
        self.running = False
        self.message_timestamps = deque(maxlen=10000)  # Recent message timestamps
        self.auth_failures = deque(maxlen=1000)        # Recent auth failures
        self.ip_requests = defaultdict(deque)          # Requests by IP
        self.alerts = {}                               # Active alerts by ID
        self.alert_history = deque(maxlen=1000)        # Alert history
        self.last_rate_limit_check = 0
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=[
                logging.FileHandler(LOG_FILE),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger("bot_monitor")
        
        # Load persisted state
        self._load_state()

    def _load_state(self):
        """Load persisted monitoring state"""
        try:
            if MONITOR_STATE_FILE.exists():
                data = json.loads(MONITOR_STATE_FILE.read_text())
                
                # Load message timestamps (last hour only)
                cutoff = time.time() - 3600
                timestamps = [t for t in data.get("message_timestamps", []) if t > cutoff]
                self.message_timestamps.extend(timestamps)
                
                # Load auth failures (last hour only) 
                failures = [f for f in data.get("auth_failures", []) if f > cutoff]
                self.auth_failures.extend(failures)
                
                # Load IP requests (last hour only)
                for ip, requests in data.get("ip_requests", {}).items():
                    recent = [r for r in requests if r > cutoff]
                    if recent:
                        self.ip_requests[ip].extend(recent)
                        
            if ALERTS_FILE.exists():
                alerts_data = json.loads(ALERTS_FILE.read_text())
                self.alerts = {aid: Alert(**alert) for aid, alert in alerts_data.get("active", {}).items()}
                self.alert_history.extend([Alert(**alert) for alert in alerts_data.get("history", [])])
                
        except Exception as e:
            self.logger.error(f"Failed to load state: {e}")

    def _save_state(self):
        """Persist monitoring state"""
        try:
            # Save only recent data to avoid bloat
            cutoff = time.time() - THRESHOLDS["stats_retention_hours"] * 3600
            
            state = {
                "message_timestamps": [t for t in self.message_timestamps if t > cutoff],
                "auth_failures": [t for t in self.auth_failures if t > cutoff],
                "ip_requests": {
                    ip: [t for t in timestamps if t > cutoff]
                    for ip, timestamps in self.ip_requests.items()
                    if any(t > cutoff for t in timestamps)
                },
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            MONITOR_STATE_FILE.write_text(json.dumps(state, indent=2))
            
            # Save alerts
            alerts_data = {
                "active": {aid: asdict(alert) for aid, alert in self.alerts.items()},
                "history": [asdict(alert) for alert in list(self.alert_history)[-100:]],
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            ALERTS_FILE.write_text(json.dumps(alerts_data, indent=2))
            
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")

    async def _get_rate_limit_status(self) -> Optional[RateLimitData]:
        """Get current rate limit status from proxy"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{RATE_LIMIT_PROXY_URL}/_status")
                if response.status_code == 200:
                    data = response.json()
                    
                    requests_used = None
                    if data["requests"]["limit"] and data["requests"]["remaining"] is not None:
                        requests_used = 100 - (data["requests"]["remaining"] / data["requests"]["limit"] * 100)
                    
                    tokens_used = None  
                    if data["tokens"]["limit"] and data["tokens"]["remaining"] is not None:
                        tokens_used = 100 - (data["tokens"]["remaining"] / data["tokens"]["limit"] * 100)
                    
                    return RateLimitData(
                        requests_used_pct=requests_used,
                        tokens_used_pct=tokens_used, 
                        total_requests=data["stats"]["total_requests"],
                        total_429s=data["stats"]["total_429s"],
                        last_429=data["stats"]["last_429"]
                    )
        except Exception as e:
            self.logger.error(f"Failed to get rate limit status: {e}")
        
        return None

    def _is_trusted_ip(self, ip_str: str) -> bool:
        """Check if IP is in trusted ranges"""
        try:
            ip = ipaddress.ip_address(ip_str)
            for range_str in TRUSTED_IP_RANGES:
                if ip in ipaddress.ip_network(range_str):
                    return True
        except Exception:
            pass
        return False

    def _create_alert(self, severity: str, category: str, title: str, 
                     description: str, metrics: Dict[str, Any] = None) -> Alert:
        """Create and track a new alert"""
        alert_id = f"{category}_{int(time.time())}"
        alert = Alert(
            id=alert_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            severity=severity,
            category=category,
            title=title,
            description=description,
            metrics=metrics or {}
        )
        
        # Check for alert cooldown
        recent_alerts = [
            a for a in self.alert_history 
            if a.category == category and 
               datetime.fromisoformat(a.timestamp.replace('Z', '+00:00')) > 
               datetime.now(timezone.utc) - timedelta(minutes=THRESHOLDS["alert_cooldown_minutes"])
        ]
        
        if not recent_alerts:  # Only add if not in cooldown
            self.alerts[alert_id] = alert
            self.alert_history.append(alert)
            self.logger.warning(f"ALERT [{severity}] {title}: {description}")
            return alert
        else:
            self.logger.debug(f"Alert in cooldown period: {title}")
            return None

    def record_message(self, timestamp: Optional[float] = None, ip: Optional[str] = None):
        """Record a bot message/API call"""
        ts = timestamp or time.time()
        self.message_timestamps.append(ts)
        
        if ip and not self._is_trusted_ip(ip):
            self.ip_requests[ip].append(ts)

    def record_auth_failure(self, timestamp: Optional[float] = None):
        """Record an authentication failure"""
        ts = timestamp or time.time()  
        self.auth_failures.append(ts)

    def get_current_metrics(self) -> ActivityMetrics:
        """Get current activity metrics"""
        now = time.time()
        
        # Message counts in different windows
        count_1min = sum(1 for ts in self.message_timestamps if now - ts <= 60)
        count_5min = sum(1 for ts in self.message_timestamps if now - ts <= 300)  
        count_15min = sum(1 for ts in self.message_timestamps if now - ts <= 900)
        count_1hour = sum(1 for ts in self.message_timestamps if now - ts <= 3600)
        
        # Auth failures in last hour
        auth_failures_1h = sum(1 for ts in self.auth_failures if now - ts <= 3600)
        
        # IP statistics
        unique_ips_1h = len([
            ip for ip, requests in self.ip_requests.items()
            if any(now - ts <= 3600 for ts in requests)
        ])
        
        suspicious_ips_1h = len([
            ip for ip, requests in self.ip_requests.items()
            if not self._is_trusted_ip(ip) and 
               sum(1 for ts in requests if now - ts <= 3600) >= THRESHOLDS["suspicious_ip_threshold"]
        ])
        
        return ActivityMetrics(
            timestamp=datetime.now(timezone.utc).isoformat(),
            message_count_1min=count_1min,
            message_count_5min=count_5min,
            message_count_15min=count_15min,
            message_count_1hour=count_1hour,
            rate_limit_requests_used_pct=None,  # Will be filled by check_activity
            rate_limit_tokens_used_pct=None,
            auth_failures_1hour=auth_failures_1h,
            unique_ips_1hour=unique_ips_1h,
            suspicious_ips_1hour=suspicious_ips_1h,
            active_alerts=len(self.alerts)
        )

    async def check_activity(self) -> List[Alert]:
        """Check for anomalous activity and generate alerts"""
        new_alerts = []
        now = time.time()
        
        # Get rate limit status
        rate_limit = await self._get_rate_limit_status()
        
        # 1. Check message volume spikes
        if len(self.message_timestamps) >= 10:  # Need some history
            recent_counts = []
            for i in range(min(10, len(self.message_timestamps))):
                window_start = now - (i + 1) * THRESHOLDS["message_volume_window_minutes"] * 60
                window_end = now - i * THRESHOLDS["message_volume_window_minutes"] * 60
                count = sum(1 for ts in self.message_timestamps if window_start <= ts < window_end)
                recent_counts.append(count)
            
            if recent_counts:
                current_count = recent_counts[0]
                avg_count = mean(recent_counts[1:]) if len(recent_counts) > 1 else 0
                
                if avg_count > 0 and current_count > avg_count * THRESHOLDS["message_volume_spike_factor"]:
                    alert = self._create_alert(
                        AlertSeverity.WARNING,
                        "volume",
                        "Message Volume Spike Detected",
                        f"Current volume: {current_count} msgs/{THRESHOLDS['message_volume_window_minutes']}min, "
                        f"Average: {avg_count:.1f} ({current_count/avg_count:.1f}x spike)",
                        {"current_count": current_count, "average_count": avg_count, "spike_factor": current_count/avg_count}
                    )
                    if alert:
                        new_alerts.append(alert)

        # 2. Check rate limit usage
        if rate_limit:
            if rate_limit.requests_used_pct and rate_limit.requests_used_pct >= THRESHOLDS["rate_limit_critical_pct"]:
                alert = self._create_alert(
                    AlertSeverity.CRITICAL,
                    "rate_limit",
                    "Critical Rate Limit Usage",
                    f"Request rate limit at {rate_limit.requests_used_pct:.1f}% capacity",
                    {"requests_used_pct": rate_limit.requests_used_pct, "total_429s": rate_limit.total_429s}
                )
                if alert:
                    new_alerts.append(alert)
                    
            elif rate_limit.requests_used_pct and rate_limit.requests_used_pct >= THRESHOLDS["rate_limit_warning_pct"]:
                alert = self._create_alert(
                    AlertSeverity.WARNING,
                    "rate_limit", 
                    "High Rate Limit Usage",
                    f"Request rate limit at {rate_limit.requests_used_pct:.1f}% capacity",
                    {"requests_used_pct": rate_limit.requests_used_pct}
                )
                if alert:
                    new_alerts.append(alert)

            if rate_limit.tokens_used_pct and rate_limit.tokens_used_pct >= THRESHOLDS["rate_limit_critical_pct"]:
                alert = self._create_alert(
                    AlertSeverity.CRITICAL,
                    "rate_limit",
                    "Critical Token Limit Usage", 
                    f"Token rate limit at {rate_limit.tokens_used_pct:.1f}% capacity",
                    {"tokens_used_pct": rate_limit.tokens_used_pct}
                )
                if alert:
                    new_alerts.append(alert)

        # 3. Check authentication failures
        auth_failures_1h = sum(1 for ts in self.auth_failures if now - ts <= 3600)
        if auth_failures_1h >= THRESHOLDS["auth_failure_max_per_hour"]:
            alert = self._create_alert(
                AlertSeverity.WARNING,
                "auth",
                "High Authentication Failure Rate",
                f"{auth_failures_1h} authentication failures in the last hour",
                {"auth_failures_1h": auth_failures_1h}
            )
            if alert:
                new_alerts.append(alert)

        # 4. Check suspicious IP activity
        for ip, requests in self.ip_requests.items():
            if self._is_trusted_ip(ip):
                continue
                
            recent_requests = sum(1 for ts in requests if now - ts <= 3600)
            if recent_requests >= THRESHOLDS["suspicious_ip_threshold"]:
                alert = self._create_alert(
                    AlertSeverity.WARNING,
                    "suspicious_ip",
                    f"High Activity from Unknown IP: {ip}",
                    f"{recent_requests} requests from {ip} in the last hour",
                    {"ip": ip, "requests_1h": recent_requests}
                )
                if alert:
                    new_alerts.append(alert)

        # Update metrics with rate limit data
        metrics = self.get_current_metrics()
        if rate_limit:
            metrics.rate_limit_requests_used_pct = rate_limit.requests_used_pct
            metrics.rate_limit_tokens_used_pct = rate_limit.tokens_used_pct

        return new_alerts

    async def start_monitoring(self, check_interval: int = 60):
        """Start continuous monitoring"""
        self.running = True
        self.logger.info("Starting bot activity monitoring")
        
        while self.running:
            try:
                await self.check_activity()
                self._save_state()
                await asyncio.sleep(check_interval)
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(check_interval)

    def stop_monitoring(self):
        """Stop monitoring"""
        self.running = False
        self._save_state()
        self.logger.info("Bot activity monitoring stopped")

    def resolve_alert(self, alert_id: str) -> bool:
        """Resolve an active alert"""
        if alert_id in self.alerts:
            alert = self.alerts[alert_id]
            alert.resolved = True
            alert.resolved_at = datetime.now(timezone.utc).isoformat()
            del self.alerts[alert_id]
            self.logger.info(f"Resolved alert: {alert.title}")
            return True
        return False

    def get_alert_summary(self) -> Dict[str, Any]:
        """Get summary of current alerts and recent activity"""
        metrics = self.get_current_metrics()
        
        alerts_by_severity = defaultdict(list)
        for alert in self.alerts.values():
            alerts_by_severity[alert.severity].append(asdict(alert))
        
        recent_history = [
            asdict(alert) for alert in list(self.alert_history)[-10:]
        ]
        
        return {
            "current_metrics": asdict(metrics),
            "active_alerts": {
                "total": len(self.alerts),
                "by_severity": dict(alerts_by_severity),
            },
            "recent_history": recent_history,
            "thresholds": THRESHOLDS,
            "monitoring_status": "active" if self.running else "stopped"
        }


# Global monitor instance
_monitor = None

def get_monitor() -> BotActivityMonitor:
    """Get the global monitor instance"""
    global _monitor
    if _monitor is None:
        _monitor = BotActivityMonitor()
    return _monitor


# API functions for Mission Control integration
async def get_bot_activity_status() -> Dict[str, Any]:
    """Get current bot activity status for API"""
    monitor = get_monitor()
    return monitor.get_alert_summary()

async def record_bot_message(ip: str = None):
    """Record a bot message for monitoring"""
    monitor = get_monitor()
    monitor.record_message(ip=ip)

async def record_bot_auth_failure():
    """Record an authentication failure"""  
    monitor = get_monitor()
    monitor.record_auth_failure()

async def resolve_bot_alert(alert_id: str) -> bool:
    """Resolve a bot activity alert"""
    monitor = get_monitor()
    return monitor.resolve_alert(alert_id)


# CLI for testing
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "daemon":
        # Run as daemon
        monitor = BotActivityMonitor()
        try:
            asyncio.run(monitor.start_monitoring())
        except KeyboardInterrupt:
            monitor.stop_monitoring()
    else:
        # Test/status mode
        async def test():
            monitor = BotActivityMonitor()
            
            # Simulate some activity
            for i in range(5):
                monitor.record_message()
            
            monitor.record_auth_failure()
            
            # Check activity
            alerts = await monitor.check_activity()
            print(f"Generated {len(alerts)} alerts")
            
            # Show summary
            summary = monitor.get_alert_summary()
            print(json.dumps(summary, indent=2))
        
        asyncio.run(test())