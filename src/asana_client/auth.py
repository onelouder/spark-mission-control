"""Asana OAuth 2.0 authentication utilities."""
import os
import json
import httpx
from pathlib import Path
from datetime import datetime, timedelta

# OAuth credentials (from task description)
CLIENT_ID = "1213076782739661"
CLIENT_SECRET = "effda28786bcdf32d17228773fb8e0f5"
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"  # Manual copy/paste flow

TOKEN_FILE = Path(__file__).parent.parent.parent / "data" / "asana_tokens.json"


def get_auth_url(state: str = "jarvis-spark") -> str:
    """Generate the OAuth authorization URL for user to visit."""
    return (
        f"https://app.asana.com/-/oauth_authorize"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&state={state}"
    )


async def exchange_code_for_token(code: str) -> dict:
    """Exchange authorization code for access token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://app.asana.com/-/oauth_token",
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "code": code,
            },
        )
        response.raise_for_status()
        tokens = response.json()
        
        # Add expiry timestamp
        tokens["expires_at"] = (
            datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))
        ).isoformat()
        
        # Save tokens
        save_tokens(tokens)
        return tokens


async def refresh_token(refresh_token: str) -> dict:
    """Refresh an expired access token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://app.asana.com/-/oauth_token",
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": refresh_token,
            },
        )
        response.raise_for_status()
        tokens = response.json()
        
        tokens["expires_at"] = (
            datetime.utcnow() + timedelta(seconds=tokens.get("expires_in", 3600))
        ).isoformat()
        
        save_tokens(tokens)
        return tokens


def save_tokens(tokens: dict) -> None:
    """Save tokens to file."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)


def load_tokens() -> dict | None:
    """Load tokens from file if they exist."""
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE) as f:
            return json.load(f)
    return None


async def get_valid_token() -> str | None:
    """Get a valid access token, refreshing if needed."""
    tokens = load_tokens()
    if not tokens:
        return None
    
    # Check if expired
    expires_at = datetime.fromisoformat(tokens.get("expires_at", "2000-01-01"))
    if datetime.utcnow() >= expires_at - timedelta(minutes=5):
        # Refresh
        if "refresh_token" in tokens:
            tokens = await refresh_token(tokens["refresh_token"])
        else:
            return None
    
    return tokens.get("access_token")
