# Mission Control: Performance & Stability Improvements

**Date:** 2026-01-29  
**Status:** Implemented / Ready for Testing

---

## Issues Identified

### 1. Memory Leaks
- Global singleton pattern for aggregator/gmail_client could accumulate state
- Background task for briefing refresh runs forever without cleanup
- MSAL token cache in decapoda-lite grows unbounded

### 2. Performance Bottlenecks
- Aggregator fetches all sources sequentially
- No connection pooling for HTTP clients
- Full briefing regeneration on every request (mitigated by cache)

### 3. Stability Concerns
- No retry logic for failed API calls
- Gmail token refresh happens synchronously, blocking requests
- No health check endpoints

---

## Fixes Applied

### 1. Connection Pooling & Async Improvements

```python
# Before: New client per request
async with httpx.AsyncClient() as client:
    response = await client.get(...)

# After: Reusable client with connection pooling
_http_client: Optional[httpx.AsyncClient] = None

def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=10)
        )
    return _http_client
```

### 2. Parallel Source Fetching

```python
# Before: Sequential
o365_emails = await self.fetch_office365_emails(...)
gmail_emails = await self.fetch_gmail_emails(...)

# After: Parallel with asyncio.gather
o365_task = asyncio.create_task(self.fetch_office365_emails(...))
gmail_task = asyncio.create_task(self.fetch_gmail_emails(...))
o365_emails, gmail_emails = await asyncio.gather(o365_task, gmail_task)
```

### 3. Health Check Endpoint

```python
@app.get("/api/health")
async def health_check():
    """Health check endpoint for monitoring"""
    checks = {
        "mission_control": "ok",
        "decapoda_lite": "unknown",
        "gmail": "unknown"
    }
    
    # Check decapoda-lite
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://localhost:8766/admin")
            checks["decapoda_lite"] = "ok" if resp.status_code == 200 else "degraded"
    except:
        checks["decapoda_lite"] = "down"
    
    # Check Gmail
    try:
        from gmail_client import test_connection
        result = await test_connection()
        checks["gmail"] = result.get("status", "unknown")
    except:
        checks["gmail"] = "error"
    
    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}
```

### 4. Graceful Degradation

```python
# If one source fails, still return data from working sources
async def get_all_emails(...):
    results = []
    errors = []
    
    try:
        results.extend(await self.fetch_office365_emails(...))
    except Exception as e:
        errors.append({"source": "office365", "error": str(e)})
    
    try:
        results.extend(await self.fetch_gmail_emails(...))
    except Exception as e:
        errors.append({"source": "gmail", "error": str(e)})
    
    return {"emails": results, "errors": errors, "partial": len(errors) > 0}
```

---

## Aesthetic Improvements

### CSS Polish

1. **Smoother animations**
```css
/* Subtle transitions */
.context-btn, .account-btn, .briefing-block {
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

/* Smoother loading spinner */
@keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}
.loading-spinner {
    animation: spin 1s linear infinite;
}
```

2. **Better visual hierarchy**
```css
/* More prominent urgency indicators */
.decision-item[data-urgency="high"] {
    border-left: 3px solid var(--urgency-high);
    background: linear-gradient(90deg, rgba(229, 62, 62, 0.1) 0%, transparent 20%);
}

/* Subtle card shadows */
.briefing-block {
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
}
```

3. **Improved typography**
```css
/* Slightly larger, more readable */
body {
    font-size: 14px;
    line-height: 1.5;
    letter-spacing: 0.01em;
}

/* Better monospace for data */
.data-text {
    font-family: "JetBrains Mono", "SF Mono", monospace;
    font-feature-settings: "liga" 0;
}
```

---

## Files Modified

- `/static/briefing.css` — Visual polish
- `/context_aggregator.py` — Connection pooling, parallel fetch
- `/app.py` — Health endpoint, graceful degradation
- `/gmail_client.py` — Retry logic for token refresh

---

## Testing Checklist

- [ ] Load briefing page with Office365 down → should show Gmail data only
- [ ] Load briefing page with Gmail down → should show Office365 data only
- [ ] Hit `/api/health` → should show status of all services
- [ ] Rapid refresh clicks → should not create connection storms
- [ ] Leave page open for 1hr → should not accumulate memory

---

## Monitoring Recommendations

1. **Add to heartbeat checks:**
   - `/api/health` endpoint status
   - Memory usage of uvicorn process
   - Response time for `/api/briefing`

2. **Log aggregation:**
   - Capture errors from background refresh task
   - Track Gmail token refresh frequency
   - Monitor cache hit rate

