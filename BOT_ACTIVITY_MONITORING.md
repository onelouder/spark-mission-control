# Bot Activity Monitoring System

## Overview

The Bot Activity Monitoring System provides real-time detection and alerting for anomalous bot usage patterns across your OpenClaw/Mission Control infrastructure. It integrates with the existing rate-limit-proxy at port 18790 and provides comprehensive monitoring for:

- **Message Volume Spikes**: Detects unusual increases in bot API activity
- **Authentication Failures**: Tracks failed auth attempts and suspicious patterns  
- **Suspicious IP Activity**: Monitors API calls from unknown/untrusted IPs
- **Rate Limit Management**: Alerts on approaching API rate limits
- **Real-time Alerting**: Configurable thresholds with severity levels

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   OpenClaw      │    │  Rate Limit      │    │  Bot Activity   │
│   Gateway       │───▶│  Proxy           │───▶│  Monitor        │
│   :18789        │    │  :18790          │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                                         │
┌─────────────────┐    ┌──────────────────┐             │
│   Mission       │◀───│  API Endpoints   │◀────────────┘
│   Control       │    │  /api/bot-       │
│   :3000         │    │  activity/*      │
└─────────────────┘    └──────────────────┘
```

## Features

### Real-time Monitoring
- **Message Volume Tracking**: Monitors API calls per minute/hour with spike detection
- **Rate Limit Integration**: Direct integration with Anthropic rate-limit-proxy  
- **IP Geo-location**: Identifies suspicious traffic from unknown locations
- **Authentication Monitoring**: Tracks failed login attempts and patterns

### Intelligent Alerting  
- **Configurable Thresholds**: Customizable alert triggers for different scenarios
- **Severity Levels**: INFO, WARNING, CRITICAL with different response actions
- **Alert Cooldowns**: Prevents alert spam with configurable cooldown periods
- **Auto-resolution**: Optional automatic alert resolution for transient issues

### Integration Points
- **Mission Control Dashboard**: Real-time widget with metrics and alerts
- **Health Check Integration**: Status included in system health endpoint
- **API Endpoints**: RESTful API for external integrations
- **CLI Management**: Command-line tools for testing and administration

## Installation & Setup

### 1. Dependencies
The monitoring system is already integrated into Mission Control. Ensure these are installed:

```bash
cd ~/projects/mission-control
pip install httpx aiohttp ipaddress
```

### 2. Configuration
Edit `bot_monitor_config.json` to customize thresholds:

```json
{
  "monitoring_thresholds": {
    "message_volume_spike_factor": 3.0,
    "rate_limit_warning_pct": 80.0,
    "suspicious_ip_threshold": 5
  }
}
```

### 3. Start Monitoring
The monitor starts automatically with Mission Control, or run standalone:

```bash
# Via Mission Control (recommended)
cd ~/projects/mission-control
python app.py

# Standalone daemon
./bot_monitor_cli.py daemon

# As systemd service  
sudo cp bot-activity-monitor.service /etc/systemd/system/
sudo systemctl enable --now bot-activity-monitor
```

## API Endpoints

### Status & Metrics
- `GET /api/bot-activity/status` - Current monitoring status and alerts
- `GET /api/bot-activity/metrics` - Detailed activity metrics
- `GET /api/bot-activity/alerts` - Active alerts and history

### Activity Recording
- `POST /api/bot-activity/message` - Record bot message/API call
- `POST /api/bot-activity/auth-failure` - Record authentication failure

### Alert Management
- `POST /api/bot-activity/resolve-alert/{id}` - Resolve an alert
- `POST /api/bot-activity/test-alert` - Generate test alerts

## CLI Usage

The `bot_monitor_cli.py` tool provides command-line management:

### Check Status
```bash
./bot_monitor_cli.py status
```
Output:
```
🛡️ Bot Activity Monitor Status
==================================================
Messages (1min): 12
Rate limit (requests): 23%
Active Alerts: 0
Monitoring Status: active
```

### View Alerts
```bash
./bot_monitor_cli.py alerts
```

### Simulate Activity (for testing)
```bash
./bot_monitor_cli.py simulate messages --count 20
./bot_monitor_cli.py simulate auth_failures --count 5
./bot_monitor_cli.py simulate volume_spike
```

### Resolve Alerts
```bash
./bot_monitor_cli.py resolve alert_id_12345
```

## Alert Types & Thresholds

### 1. Message Volume Spikes
- **Trigger**: Current volume > 3x moving average
- **Window**: 30-minute moving average  
- **Severity**: WARNING → CRITICAL based on spike magnitude

### 2. Rate Limit Usage
- **Warning**: 80% of API rate limit consumed
- **Critical**: 95% of API rate limit consumed
- **Tracks**: Both request and token limits from Anthropic

### 3. Authentication Failures
- **Threshold**: >10 failures per hour
- **Severity**: WARNING → CRITICAL based on failure rate
- **Patterns**: Detects brute force and credential stuffing

### 4. Suspicious IP Activity  
- **Threshold**: >5 requests from unknown IP per hour
- **Trusted Ranges**: Configurable private/local IP ranges
- **Severity**: WARNING for unknown IPs, CRITICAL for attack patterns

## Dashboard Integration

The monitoring system includes a real-time dashboard widget:

### Widget Features
- **Real-time Metrics**: Messages/min, rate limit usage, alert count
- **Alert Display**: Expandable list of active alerts with resolution actions
- **Status Indicator**: Color-coded system health (green/yellow/red)
- **Auto-refresh**: Updates every 30 seconds

### Integration Code
Add to your Mission Control dashboard:

```html
{% include 'bot_activity_widget.html' %}
```

## Configuration Options

### Monitoring Thresholds
| Setting | Default | Description |
|---------|---------|-------------|
| `message_volume_spike_factor` | 3.0 | Spike detection multiplier |
| `rate_limit_warning_pct` | 80.0 | Warning threshold for rate limits |
| `rate_limit_critical_pct` | 95.0 | Critical threshold for rate limits |
| `auth_failure_max_per_hour` | 10 | Max auth failures before alert |
| `suspicious_ip_threshold` | 5 | Requests from unknown IP threshold |
| `alert_cooldown_minutes` | 15 | Minutes between duplicate alerts |

### Trusted IP Ranges
Default trusted ranges (no alerts generated):
- `127.0.0.0/8` (localhost)
- `10.0.0.0/8` (Private Class A)
- `172.16.0.0/12` (Private Class B)
- `192.168.0.0/16` (Private Class C)

## Monitoring Best Practices

### 1. Baseline Establishment
- Run for 24-48 hours to establish normal activity patterns
- Adjust thresholds based on your typical usage patterns
- Monitor alert frequency and tune to reduce false positives

### 2. Alert Response
- **INFO**: Log and monitor, no immediate action required
- **WARNING**: Review within 1 hour, investigate if patterns continue
- **CRITICAL**: Immediate investigation required, potential security issue

### 3. Regular Maintenance
- Review alert history weekly to identify trends
- Update trusted IP ranges as infrastructure changes
- Adjust thresholds seasonally based on usage patterns

## Troubleshooting

### Monitor Not Starting
```bash
# Check Mission Control logs
tail -f ~/projects/mission-control/logs/bot_activity_monitor.log

# Verify rate-limit-proxy connectivity
curl http://localhost:18790/_health
```

### No Alerts Generated
```bash
# Test alert generation
./bot_monitor_cli.py test

# Check current activity
./bot_monitor_cli.py status
```

### High False Positives
1. Increase `message_volume_spike_factor` in config
2. Add legitimate IPs to trusted ranges  
3. Increase `alert_cooldown_minutes`

## Security Considerations

### Data Privacy
- IP addresses are hashed for privacy in logs
- No message content is stored, only metadata
- Alert data retained for 24 hours by default

### Access Control
- API endpoints use Mission Control authentication
- CLI tools require local filesystem access
- Service runs with minimal privileges

### Monitoring Security
- Monitor the monitor: Set up external health checks
- Secure configuration files with appropriate permissions  
- Regular security updates for dependencies

## Future Enhancements

### Planned Features
- **Machine Learning**: Anomaly detection using ML models
- **Geographic Analysis**: Enhanced IP geolocation and threat intelligence
- **Integration**: Webhook alerts, email notifications, Slack integration  
- **Forensics**: Detailed request logging and analysis tools
- **Auto-mitigation**: Automatic rate limiting and IP blocking

### Extension Points
- Custom alert handlers via plugin system
- External threat intelligence feed integration
- Custom metrics and dashboards via API
- Integration with SIEM systems

## Support

For issues, questions, or feature requests:
1. Check the logs: `~/projects/mission-control/logs/bot_activity_monitor.log`  
2. Test with CLI: `./bot_monitor_cli.py status`
3. Review configuration: `bot_monitor_config.json`
4. Submit issues to the project repository

---

**Last Updated**: 2026-02-19  
**Version**: 1.0.0  
**Compatibility**: OpenClaw 2026.2.15+, Mission Control 2.0+