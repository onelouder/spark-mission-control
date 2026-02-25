#!/usr/bin/env python3
"""
Gmail OAuth Helper - One-time setup for Mission Control
Run this ON ether-spark to complete OAuth flow via localhost redirect.
"""
import json
import webbrowser
import pathlib
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests

# === Config ===
CREDS_PATH = pathlib.Path("/home/jwells/clawd/secrets/google-oauth-jarvis.json")
TOKENS_PATH = pathlib.Path(__file__).parent / "data" / "gmail_tokens.json"
# Localhost redirect for Web Application OAuth
REDIRECT_URI = "http://localhost:8767/auth/callback"
BIND_HOST = "127.0.0.1"
PORT = 8767

# Gmail + Calendar read scopes (add write scopes if needed later)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
]

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handle OAuth callback"""
    auth_code = None
    
    def log_message(self, format, *args):
        pass  # Suppress HTTP logs
    
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/auth/callback":
            params = parse_qs(parsed.query)
            if "code" in params:
                OAuthCallbackHandler.auth_code = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"""
                    <html><body style="font-family: system-ui; padding: 40px; text-align: center;">
                    <h1>&#10004; Authorization Successful</h1>
                    <p>You can close this tab. Tokens are being saved...</p>
                    </body></html>
                """)
            elif "error" in params:
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                error = params.get("error", ["unknown"])[0]
                self.wfile.write(f"<html><body><h1>Error: {error}</h1></body></html>".encode())
            else:
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

def load_credentials():
    """Load OAuth client credentials"""
    if not CREDS_PATH.exists():
        raise FileNotFoundError(f"Missing credentials: {CREDS_PATH}")
    creds = json.loads(CREDS_PATH.read_text())
    # Handle both 'installed' (desktop) and 'web' credential types
    if "installed" in creds:
        return creds["installed"]
    elif "web" in creds:
        return creds["web"]
    return creds

def exchange_code_for_tokens(creds: dict, code: str) -> dict:
    """Exchange authorization code for access + refresh tokens"""
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    })
    resp.raise_for_status()
    return resp.json()

def build_auth_url(creds: dict) -> str:
    """Build Google OAuth authorization URL"""
    from urllib.parse import urlencode
    params = {
        "client_id": creds["client_id"],
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",  # Force refresh token
    }
    return f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"

def main():
    print("=" * 60)
    print("Gmail OAuth Setup for Mission Control")
    print("=" * 60)
    
    # Load credentials
    creds = load_credentials()
    print(f"✓ Loaded credentials: {creds['client_id'][:20]}...")
    
    # Ensure data directory exists
    TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Build auth URL
    auth_url = build_auth_url(creds)
    print(f"\n→ Starting local server on port {PORT}...")
    
    # Start callback server
    server = HTTPServer((BIND_HOST, PORT), OAuthCallbackHandler)
    server_thread = threading.Thread(target=server.handle_request)
    server_thread.start()
    
    # Open browser or print URL
    print(f"\n→ Opening browser for authorization...")
    print(f"\nIf browser doesn't open, visit this URL:\n")
    print(auth_url)
    print()
    
    try:
        webbrowser.open(auth_url)
    except Exception:
        print("(Could not open browser automatically)")
    
    # Wait for callback
    print("Waiting for authorization callback...")
    server_thread.join(timeout=300)  # 5 minute timeout
    server.server_close()
    
    if not OAuthCallbackHandler.auth_code:
        print("\n✗ No authorization code received. Timed out or cancelled.")
        return 1
    
    print("\n→ Exchanging code for tokens...")
    try:
        tokens = exchange_code_for_tokens(creds, OAuthCallbackHandler.auth_code)
    except Exception as e:
        print(f"\n✗ Token exchange failed: {e}")
        return 1
    
    # Save tokens
    TOKENS_PATH.write_text(json.dumps(tokens, indent=2))
    print(f"\n✓ Tokens saved to: {TOKENS_PATH}")
    
    # Show info
    if "refresh_token" in tokens:
        print("✓ Refresh token obtained (good for long-term access)")
    if "expires_in" in tokens:
        print(f"✓ Access token expires in {tokens['expires_in']} seconds")
    
    print("\n" + "=" * 60)
    print("Setup complete! Mission Control can now access Gmail/Calendar.")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    exit(main())
