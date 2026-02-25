#!/usr/bin/env python3
"""
Quick authentication module for Mission Control
EMERGENCY IMPLEMENTATION - Secure the public exposure immediately
"""

import os
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Emergency auth configuration
AUTH_USERNAME = os.environ.get("MISSION_CONTROL_USERNAME", "admin")
AUTH_PASSWORD_HASH = os.environ.get("MISSION_CONTROL_PASSWORD_HASH", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", secrets.token_urlsafe(32))

# In-memory session store (for emergency deployment)
active_sessions = {}
SESSION_DURATION = timedelta(hours=8)

def hash_password(password: str) -> str:
    """Hash password using SHA-256 with salt"""
    salt = "mission_control_salt_2025"
    return hashlib.sha256((password + salt).encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash"""
    return hash_password(password) == hashed

def create_session(username: str) -> str:
    """Create new session token"""
    session_token = secrets.token_urlsafe(32)
    active_sessions[session_token] = {
        "username": username,
        "created": datetime.now(),
        "last_access": datetime.now()
    }
    return session_token

def verify_session(request: Request) -> Optional[str]:
    """Verify session from request"""
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in active_sessions:
        return None
    
    session = active_sessions[session_token]
    
    # Check expiry
    if datetime.now() - session["created"] > SESSION_DURATION:
        del active_sessions[session_token]
        return None
    
    # Update last access
    session["last_access"] = datetime.now()
    return session["username"]

def require_auth(request: Request):
    """Dependency to require authentication"""
    username = verify_session(request)
    if not username:
        # Return redirect to login for browser requests
        if request.headers.get("accept", "").startswith("text/html"):
            return RedirectResponse(url="/login", status_code=302)
        else:
            # JSON error for API requests
            raise HTTPException(status_code=401, detail="Authentication required")
    return username

def get_login_page() -> str:
    """Generate emergency login page HTML"""
    return """<!DOCTYPE html>
<html>
<head>
    <title>Mission Control - Login</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
        }
        .login-container {
            background: white;
            padding: 2rem;
            border-radius: 10px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.2);
            width: 100%;
            max-width: 400px;
        }
        .logo {
            text-align: center;
            margin-bottom: 2rem;
        }
        .logo h1 {
            color: #333;
            margin: 0;
            font-size: 1.8rem;
        }
        .form-group {
            margin-bottom: 1rem;
        }
        label {
            display: block;
            margin-bottom: 0.5rem;
            color: #555;
            font-weight: 500;
        }
        input[type="text"], input[type="password"] {
            width: 100%;
            padding: 0.75rem;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 1rem;
            transition: border-color 0.3s;
        }
        input[type="text"]:focus, input[type="password"]:focus {
            outline: none;
            border-color: #667eea;
        }
        .login-btn {
            width: 100%;
            padding: 0.75rem;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 1rem;
            cursor: pointer;
            transition: background 0.3s;
        }
        .login-btn:hover {
            background: #5a67d8;
        }
        .error {
            color: #e53e3e;
            margin-top: 0.5rem;
            font-size: 0.9rem;
        }
        .security-notice {
            background: #fed7d7;
            border: 1px solid #feb2b2;
            color: #c53030;
            padding: 0.75rem;
            border-radius: 5px;
            margin-bottom: 1rem;
            font-size: 0.9rem;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">
            <h1>🎯 Mission Control</h1>
        </div>
        
        <div class="security-notice">
            <strong>Security Notice:</strong> This login was implemented due to public exposure of the system.
        </div>
        
        <form method="post" action="/login">
            <div class="form-group">
                <label for="username">Username:</label>
                <input type="text" name="username" required>
            </div>
            
            <div class="form-group">
                <label for="password">Password:</label>
                <input type="password" name="password" required>
            </div>
            
            <button type="submit" class="login-btn">Login</button>
        </form>
    </div>
</body>
</html>"""

def setup_default_password():
    """Setup default password if none configured"""
    if not AUTH_PASSWORD_HASH:
        default_password = "MissionControl2025!"
        default_hash = hash_password(default_password)
        print(f"⚠️  EMERGENCY AUTH SETUP:")
        print(f"   Username: {AUTH_USERNAME}")
        print(f"   Password: {default_password}")
        print(f"   Hash: {default_hash}")
        print("   ⚠️  CHANGE THIS IMMEDIATELY!")
        print(f"   To set permanently: export MISSION_CONTROL_PASSWORD_HASH='{default_hash}'")
        return default_hash
    return AUTH_PASSWORD_HASH