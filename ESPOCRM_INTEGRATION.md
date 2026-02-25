# EspoCRM Integration with Mission Control

## Overview ✅ COMPLETE

EspoCRM has been successfully integrated into Mission Control and is accessible through the existing Cloudflare tunnel. The integration provides both iframe and direct proxy access to the CRM system.

## Access Points

### Local Development
- **EspoCRM Direct**: `http://localhost:8081`
- **Mission Control CRM**: `http://localhost:3000/crm`
- **Mission Control Main**: `http://localhost:3000`

### Production (via Cloudflare Tunnel)
- **CRM Access**: `https://[your-domain]/crm`
- **Direct Proxy**: `https://[your-domain]/_crm/`

*Note: Replace `[your-domain]` with your actual Cloudflare tunnel domain*

## Login Credentials

**EspoCRM Admin Access:**
- **Username**: `admin`
- **Password**: `NovviAdmin2026!CRM#Secure`
- **URL**: `http://localhost:8081` (or via Mission Control)

## Technical Implementation

### Architecture
```
[Cloudflare Tunnel] → [Mission Control:3000] → [EspoCRM:8081]
                                      ↓
                               [Proxy Routes]
                               • /crm (iframe)
                               • /_crm/* (API proxy)
```

### Integration Code Location
**File**: `/home/jwells/projects/mission-control/app.py`
**Lines**: 3275-3320

```python
# EspoCRM Integration
CRM_UPSTREAM = "http://localhost:8081"
_crm_client = httpx.AsyncClient(base_url=CRM_UPSTREAM, timeout=60.0, follow_redirects=True)

@app.get("/crm")
async def crm_page(request: Request):
    # Returns iframe wrapper for EspoCRM
    
@app.get("/_crm/")
@app.get("/_crm")
async def crm_root(request: Request):
    # Proxies EspoCRM root with CSP fixes
    
@app.api_route("/_crm/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def crm_proxy(request: Request, path: str):
    # Full API proxy for all EspoCRM requests
```

## Features Implemented

### ✅ Full Integration
- **Iframe Interface**: Clean, full-screen EspoCRM access at `/crm`
- **API Proxy**: Complete proxy of all EspoCRM functionality at `/_crm/*`
- **Security**: CSP headers stripped for iframe compatibility
- **Error Handling**: Graceful fallback when EspoCRM is unavailable
- **Methods Support**: GET, POST, PUT, PATCH, DELETE all proxied

### ✅ Header Management
- Removes problematic headers for iframe embedding
- Strips CSP nonces for script compatibility
- Excludes frame-busting headers (X-Frame-Options)

## Services Status

### Current Running Services
```bash
# Check service status
ps aux | grep -E "python.*app\.py|uvicorn.*mission"  # Mission Control
ps aux | grep -E "espocrm|apache|nginx"               # EspoCRM
ps aux | grep cloudflared                             # Tunnel
```

### Tunnel Information
- **Tunnel ID**: `1442de76-98ca-41bf-8dc0-e200a421f11b`
- **Tunnel Name**: `ether-spark-tunnel`
- **Status**: Active with 3 connections (2xsjc06, 1xsjc07, 1xsjc08)

## Testing Checklist ✅

All tests passing:

- ✅ EspoCRM direct access (`localhost:8081`)
- ✅ Mission Control running (`localhost:3000`)
- ✅ CRM iframe endpoint (`/crm`)
- ✅ CRM proxy endpoint (`/_crm/`)
- ✅ Cloudflare tunnel active

## Usage Instructions

### For End Users
1. **Access Mission Control**: Navigate to your Cloudflare tunnel domain
2. **Open CRM**: Click on CRM section or navigate to `/crm`
3. **Login**: Use admin credentials listed above
4. **Full Functionality**: All EspoCRM features available through the proxy

### For Developers
1. **Local Testing**: Use `localhost:3000/crm` for development
2. **API Integration**: All EspoCRM API calls work through `/_crm/*` prefix
3. **Direct Access**: EspoCRM still available at `localhost:8081`

## Troubleshooting

### Common Issues
1. **502 Bad Gateway**: EspoCRM not running on port 8081
   ```bash
   # Check EspoCRM status
   curl http://localhost:8081
   ```

2. **Mission Control not responding**: Check if running on port 3000
   ```bash
   # Restart Mission Control
   cd /home/jwells/projects/mission-control
   ./start.sh
   ```

3. **Iframe not loading**: CSP or X-Frame-Options issues
   - Check browser console for security errors
   - Verify proxy is stripping problematic headers

### Logs and Debugging
```bash
# Mission Control logs
cd /home/jwells/projects/mission-control
tail -f logs/*.log  # if logging enabled

# EspoCRM logs
# Check EspoCRM installation logs (typically in data/logs/)

# Cloudflare tunnel logs
sudo journalctl -u cloudflared -f
```

## Security Considerations

### Headers Removed
- `content-security-policy`
- `x-frame-options` 
- CSP nonces stripped for iframe compatibility

### Access Control
- EspoCRM authentication still enforced
- Mission Control acts as reverse proxy
- No additional authentication layer (relies on EspoCRM)

## Next Steps

The integration is complete and functional. Consider:

1. **SSL/TLS**: Ensure tunnel uses HTTPS for production
2. **Monitoring**: Set up health checks for both services
3. **Backup**: Regular database backups for EspoCRM
4. **Users**: Create additional EspoCRM users as needed

---

**Integration completed successfully!** 🎉

EspoCRM is now accessible through Mission Control via the existing Cloudflare tunnel infrastructure.