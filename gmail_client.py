"""
Gmail & Google Calendar Client for Mission Control
Provides similar interface to decapoda-lite (Office365) but for Google APIs

Filtering strategy: dynamic sent-mail whitelist
  - Before each inbox fetch, scan sent mail (last N days) to extract recipients
  - Combine with stable partner domains + pinned contacts from contacts.json
  - This means anyone you actively email is automatically surfaced in your inbox
  - No manual list maintenance needed; the window slides naturally
"""

import json
import os
import re
import time
import base64
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Set, Tuple
import httpx

# === Paths ===
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TOKENS_PATH = os.path.join(DATA_DIR, "gmail_tokens.json")
CONTACTS_PATH = os.path.join(DATA_DIR, "contacts.json")
CREDS_PATH = "/home/jwells/clawd/secrets/google-oauth-jarvis.json"

# === Google API endpoints ===
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

# === Sent-mail cache (module-level, shared across calls) ===
_sent_cache: Dict = {
    "recipients": {},   # email -> last_sent ISO timestamp
    "fetched_at": None, # monotonic time of last fetch
}
SENT_CACHE_TTL = 30 * 60  # 30 minutes


class GmailClient:
    """Gmail and Google Calendar client with automatic token refresh"""
    
    def __init__(self):
        self.tokens = self._load_tokens()
        self.creds = self._load_credentials()
        self._client = None
    
    def _load_tokens(self) -> Dict:
        try:
            with open(TOKENS_PATH, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    
    def _save_tokens(self, tokens: Dict) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(TOKENS_PATH, 'w') as f:
            json.dump(tokens, f, indent=2)
    
    def _load_credentials(self) -> Dict:
        try:
            with open(CREDS_PATH, 'r') as f:
                creds = json.load(f)
                if "installed" in creds:
                    return creds["installed"]
                elif "web" in creds:
                    return creds["web"]
                return creds
        except FileNotFoundError:
            return {}
    
    def is_configured(self) -> bool:
        return bool(self.tokens.get("refresh_token"))
    
    async def _refresh_token_if_needed(self) -> bool:
        if not self.tokens.get("refresh_token"):
            return False
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(OAUTH_TOKEN_URL, data={
                    "client_id": self.creds.get("client_id"),
                    "client_secret": self.creds.get("client_secret"),
                    "refresh_token": self.tokens["refresh_token"],
                    "grant_type": "refresh_token"
                })
                if response.status_code == 200:
                    new_tokens = response.json()
                    if "refresh_token" not in new_tokens:
                        new_tokens["refresh_token"] = self.tokens["refresh_token"]
                    self.tokens = new_tokens
                    self._save_tokens(self.tokens)
                    return True
                else:
                    print(f"Token refresh failed: {response.status_code} {response.text}")
                    return False
        except Exception as e:
            print(f"Token refresh error: {e}")
            return False
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.tokens.get('access_token', '')}",
            "Content-Type": "application/json"
        }
    
    async def _request(self, method: str, url: str, **kwargs) -> Optional[Dict]:
        headers = self._get_headers()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
            if response.status_code == 401:
                if await self._refresh_token_if_needed():
                    headers = self._get_headers()
                    response = await client.request(method, url, headers=headers, **kwargs)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Gmail API error: {response.status_code} {response.text[:200]}")
                return None
    
    async def get_profile(self) -> Optional[Dict]:
        return await self._request("GET", f"{GMAIL_API}/users/me/profile")
    
    async def get_messages(self, max_results: int = 50, query: str = None,
                           include_spam_trash: bool = False) -> List[Dict]:
        params = {"maxResults": max_results}
        if query:
            params["q"] = query
        if not include_spam_trash:
            params["includeSpamTrash"] = "false"
        result = await self._request("GET", f"{GMAIL_API}/users/me/messages", params=params)
        return result.get("messages", []) if result else []
    
    async def get_message(self, message_id: str, format: str = "metadata") -> Optional[Dict]:
        params = {"format": format}
        if format == "metadata":
            # Only fetch the headers we need — much faster than full metadata
            params["metadataHeaders"] = ["From", "To", "Cc", "Subject", "Date"]
        return await self._request("GET", f"{GMAIL_API}/users/me/messages/{message_id}", params=params)

    # -------------------------------------------------------------------------
    # Sent-mail recipient extraction
    # -------------------------------------------------------------------------

    async def get_sent_recipients(
        self,
        days_back: int = 30,
        max_messages: int = 300,
    ) -> Dict[str, str]:
        """
        Scan sent mail and return {email_address: last_sent_iso} for all recipients.
        
        This is the core of the dynamic whitelist approach:
        anyone you've actively emailed recently is automatically surfaced.
        
        Args:
            days_back: how far back to scan (default 30 days)
            max_messages: cap on sent messages to scan (default 300)
        
        Returns:
            dict mapping lowercase email address -> ISO timestamp of most recent sent
        """
        await self._refresh_token_if_needed()

        after_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y/%m/%d")
        query = f"in:sent after:{after_date}"

        messages = await self.get_messages(max_results=max_messages, query=query)
        if not messages:
            return {}

        recipients: Dict[str, str] = {}  # email -> most recent sent timestamp

        for msg in messages:
            details = await self.get_message(msg["id"], format="metadata")
            if not details:
                continue

            headers = {
                h["name"].lower(): h["value"]
                for h in details.get("payload", {}).get("headers", [])
            }

            # Extract timestamp
            internal_date = int(details.get("internalDate", 0)) / 1000
            sent_dt = datetime.fromtimestamp(internal_date, tz=timezone.utc).isoformat()

            # Parse To + Cc (not Bcc — not visible in metadata)
            for field in ("to", "cc"):
                raw = headers.get(field, "")
                if not raw:
                    continue
                for addr in self._extract_addresses(raw):
                    addr_lower = addr.lower()
                    # Keep the most recent sent timestamp for each address
                    if addr_lower not in recipients or sent_dt > recipients[addr_lower]:
                        recipients[addr_lower] = sent_dt

        return recipients

    def _extract_addresses(self, header_value: str) -> List[str]:
        """
        Extract bare email addresses from a header like:
          "Alice <alice@example.com>, bob@example.com, \"C, D\" <cd@example.com>"
        Returns list of lowercase email addresses.
        """
        addresses = []
        # Match anything inside <...> first
        for match in re.finditer(r'<([^>]+)>', header_value):
            addresses.append(match.group(1).strip().lower())
        # If no angle-bracket form found, try comma-split plain addresses
        if not addresses:
            for part in header_value.split(","):
                part = part.strip()
                if "@" in part:
                    addresses.append(part.lower())
        return addresses

    # -------------------------------------------------------------------------
    # Inbox fetch — targeted sender queries
    # -------------------------------------------------------------------------

    async def get_emails_from_senders(
        self,
        allowed_emails: Set[str],
        allowed_domains: Set[str],
        max_results: int = 50,
        days_back: int = 14,
        unread_only: bool = False,
    ) -> List[Dict]:
        """
        Fetch inbox emails from a specific set of senders/domains.
        Uses chunked `from:(a OR b OR ...)` queries + per-domain queries.
        Applies a strict post-filter to ensure no leakage.
        
        Args:
            allowed_emails: set of lowercase email addresses
            allowed_domains: set of lowercase domain names
            max_results: max emails to return
            days_back: how far back to look
            unread_only: only return unread messages
        """
        await self._refresh_token_if_needed()

        date_filter = ""
        if days_back:
            after_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y/%m/%d")
            date_filter = f"after:{after_date} "
        unread_filter = "is:unread " if unread_only else ""

        collected: Dict[str, Dict] = {}  # id -> normalized email

        # --- Part 1: email address queries (chunked) ---
        if allowed_emails:
            email_list = sorted(allowed_emails)
            # Gmail query max ~500 chars for the from() clause; keep chunks small
            CHUNK_SIZE = 20
            chunks = [email_list[i:i+CHUNK_SIZE] for i in range(0, len(email_list), CHUNK_SIZE)]

            for chunk in chunks:
                sender_query = " OR ".join(chunk)
                query = f"{unread_filter}{date_filter}from:({sender_query})"
                per_chunk = max(max_results // max(len(chunks), 1) + 5, 10)
                messages = await self.get_messages(max_results=per_chunk, query=query)

                for msg in messages:
                    if msg["id"] not in collected:
                        details = await self.get_message(msg["id"], format="metadata")
                        if details:
                            collected[msg["id"]] = self._normalize_email(details)

                if len(collected) >= max_results * 2:  # fetch headroom before dedup
                    break

        # --- Part 2: domain queries ---
        if allowed_domains:
            for domain in sorted(allowed_domains):
                query = f"{unread_filter}{date_filter}from:@{domain}"
                messages = await self.get_messages(max_results=15, query=query)
                for msg in messages:
                    if msg["id"] not in collected:
                        details = await self.get_message(msg["id"], format="metadata")
                        if details:
                            collected[msg["id"]] = self._normalize_email(details)

        # --- Post-filter: belt-and-suspenders ---
        # Gmail `from:()` queries sometimes have fuzzy matching edge cases.
        # Verify every result actually came from an allowed sender.
        verified = []
        for email in collected.values():
            sender_addr = email.get("from", {}).get("address", "").lower().strip()
            sender_domain = sender_addr.split("@")[-1] if "@" in sender_addr else ""
            if sender_addr in allowed_emails or sender_domain in allowed_domains:
                verified.append(email)
            else:
                print(f"[gmail_filter] REJECTED post-filter: {sender_addr}")

        verified.sort(key=lambda e: e.get("received", ""), reverse=True)
        return verified[:max_results]

    async def get_recent_emails(self, max_results: int = 50,
                                days_back: int = 7,
                                unread_only: bool = False) -> List[Dict]:
        """Unfiltered recent emails — use for diagnostics only."""
        query_parts = []
        if days_back:
            after_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y/%m/%d")
            query_parts.append(f"after:{after_date}")
        if unread_only:
            query_parts.append("is:unread")
        query = " ".join(query_parts) if query_parts else None
        messages = await self.get_messages(max_results=max_results, query=query)
        emails = []
        for msg in messages:
            details = await self.get_message(msg["id"], format="metadata")
            if details:
                emails.append(self._normalize_email(details))
        return emails

    def _normalize_email(self, gmail_msg: Dict) -> Dict:
        headers = {h["name"].lower(): h["value"] for h in gmail_msg.get("payload", {}).get("headers", [])}
        from_raw = headers.get("from", "")
        from_name, from_email = self._parse_email_header(from_raw)
        to_raw = headers.get("to", "")
        to_list = self._parse_recipient_list(to_raw)
        internal_date = int(gmail_msg.get("internalDate", 0)) / 1000
        received_dt = datetime.fromtimestamp(internal_date, tz=timezone.utc)
        labels = gmail_msg.get("labelIds", [])
        is_read = "UNREAD" not in labels
        return {
            "id": gmail_msg["id"],
            "threadId": gmail_msg.get("threadId"),
            "subject": headers.get("subject", "(no subject)"),
            "from": {"name": from_name, "address": from_email},
            "to": to_list,
            "received": received_dt.isoformat(),
            "isRead": is_read,
            "snippet": gmail_msg.get("snippet", ""),
            "labels": labels,
            "webLink": f"https://mail.google.com/mail/u/0/#inbox/{gmail_msg['id']}",
            "_source": "gmail",
            "_account": "jwells@gmail.com"
        }

    def _parse_email_header(self, header: str) -> Tuple[str, str]:
        match = re.match(r'^(.+?)\s*<(.+?)>$', header.strip())
        if match:
            return match.group(1).strip().strip('"'), match.group(2).strip().lower()
        addr = header.strip().lower()
        return addr, addr

    def _parse_recipient_list(self, header: str) -> List[Dict]:
        if not header:
            return []
        recipients = []
        for part in header.split(","):
            name, email = self._parse_email_header(part.strip())
            recipients.append({"name": name, "address": email})
        return recipients

    # === Calendar Methods ===

    async def get_calendars(self) -> List[Dict]:
        result = await self._request("GET", f"{CALENDAR_API}/users/me/calendarList")
        return result.get("items", []) if result else []

    async def get_events(self, calendar_id: str = "primary",
                         time_min: datetime = None,
                         time_max: datetime = None,
                         max_results: int = 50,
                         single_events: bool = True) -> List[Dict]:
        if time_min is None:
            time_min = datetime.now(timezone.utc)
        if time_max is None:
            time_max = time_min + timedelta(days=7)
        params = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "maxResults": max_results,
            "singleEvents": str(single_events).lower(),
            "orderBy": "startTime"
        }
        result = await self._request("GET", f"{CALENDAR_API}/calendars/{calendar_id}/events", params=params)
        return result.get("items", []) if result else []

    async def get_upcoming_events(self, days: int = 7, max_results: int = 50) -> List[Dict]:
        now = datetime.now(timezone.utc)
        events = await self.get_events(
            time_min=now,
            time_max=now + timedelta(days=days),
            max_results=max_results
        )
        return [self._normalize_event(e) for e in events]

    def _normalize_event(self, event: Dict) -> Dict:
        start = event.get("start", {})
        end = event.get("end", {})
        if "dateTime" in start:
            start_time = start["dateTime"]
            end_time = end.get("dateTime", start_time)
            all_day = False
        else:
            start_time = start.get("date", "")
            end_time = end.get("date", start_time)
            all_day = True
        attendees = []
        for att in event.get("attendees", []):
            attendees.append({
                "name": att.get("displayName", att.get("email", "")),
                "address": att.get("email", ""),
                "responseStatus": att.get("responseStatus", "needsAction"),
                "self": att.get("self", False)
            })
        return {
            "id": event["id"],
            "subject": event.get("summary", "(no title)"),
            "start": start_time,
            "end": end_time,
            "allDay": all_day,
            "location": event.get("location", ""),
            "description": event.get("description", ""),
            "attendees": attendees,
            "webLink": event.get("htmlLink", ""),
            "status": event.get("status", "confirmed"),
            "organizer": event.get("organizer", {}),
            "_source": "google_calendar",
            "_account": "jwells@gmail.com"
        }


# === Module-level convenience functions ===

_client: Optional[GmailClient] = None

def get_client() -> GmailClient:
    global _client
    if _client is None:
        _client = GmailClient()
    return _client


async def get_sent_recipients_cached(days_back: int = 30) -> Dict[str, str]:
    """
    Return sent-mail recipients, using the module-level cache (30-min TTL).
    Returns {email_address: last_sent_iso}.
    """
    global _sent_cache
    now = time.monotonic()
    if (
        _sent_cache["fetched_at"] is None
        or (now - _sent_cache["fetched_at"]) > SENT_CACHE_TTL
    ):
        print(f"[gmail] Refreshing sent-mail cache (days_back={days_back})...")
        client = get_client()
        if client.is_configured():
            _sent_cache["recipients"] = await client.get_sent_recipients(days_back=days_back)
            _sent_cache["fetched_at"] = now
            print(f"[gmail] Sent cache: {len(_sent_cache['recipients'])} recipients")
        else:
            _sent_cache["recipients"] = {}
            _sent_cache["fetched_at"] = now
    return _sent_cache["recipients"]


def build_stable_whitelist() -> Dict[str, set]:
    """
    Load the stable (non-dynamic) whitelist from contacts.json:
      - partner_domains: key business domains (always included)
      - pinned_contacts: manually pinned individual addresses
      - top20/top100: Exchange-derived professional contacts (Novvi business)
    
    Intentionally EXCLUDES gmail_top_senders (124 bulk contacts — too noisy).
    Dynamic sent-mail recipients are handled separately.
    """
    if not os.path.exists(CONTACTS_PATH):
        return {"emails": set(), "domains": set()}
    try:
        with open(CONTACTS_PATH, 'r') as f:
            data = json.load(f)

        emails: Set[str] = set()
        domains: Set[str] = set(data.get("partner_domains", []))

        for addr in data.get("pinned_contacts", []):
            emails.add(addr.lower())

        # Exchange-derived professional contacts (Novvi business relationships)
        for contact in data.get("top20", []) + data.get("top100", []):
            if "email" in contact:
                emails.add(contact["email"].lower())

        return {"emails": emails, "domains": domains}
    except Exception as e:
        print(f"[gmail] Error loading stable whitelist: {e}")
        return {"emails": set(), "domains": set()}


async def get_filtered_emails(
    days_back: int = 14,
    max_results: int = 50,
    unread_only: bool = False,
    sent_days_back: int = 30,
) -> List[Dict]:
    """
    Fetch inbox emails using a dynamic sent-mail whitelist.

    Whitelist = sent recipients (last sent_days_back days)
              + partner domains (stable)
              + pinned contacts (stable)
              + Exchange top20/top100 professional contacts (stable)

    Anyone you've actively emailed recently is automatically surfaced.
    Real estate agents, contractors, vendors — they appear the day you
    email them and fade out naturally when the window lapses.
    """
    client = get_client()
    if not client.is_configured():
        print("[gmail] Not configured — run gmail_auth.py first")
        return []

    # 1. Stable whitelist (partner domains, pinned, Exchange contacts)
    stable = build_stable_whitelist()

    # 2. Dynamic sent-mail recipients (cached, 30-min TTL)
    sent_recipients = await get_sent_recipients_cached(days_back=sent_days_back)

    # 3. Merge: emails = stable pinned + exchange contacts + sent recipients
    all_emails = stable["emails"] | set(sent_recipients.keys())
    all_domains = stable["domains"]

    print(
        f"[gmail] Whitelist: {len(stable['emails'])} stable emails, "
        f"{len(sent_recipients)} sent recipients, "
        f"{len(all_domains)} domains"
    )

    if not all_emails and not all_domains:
        print("[gmail] Whitelist empty — nothing to fetch")
        return []

    # 4. Fetch inbox from whitelisted senders (with strict post-filter)
    return await client.get_emails_from_senders(
        allowed_emails=all_emails,
        allowed_domains=all_domains,
        max_results=max_results,
        days_back=days_back,
        unread_only=unread_only,
    )


async def get_whitelist_summary() -> Dict:
    """
    Return a summary of the current dynamic whitelist — useful for debugging
    and for the /api/gmail/whitelist endpoint.
    """
    stable = build_stable_whitelist()
    sent_recipients = await get_sent_recipients_cached()

    # Identify recently active senders (sent in last 7 days)
    cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    recent = {
        addr: ts for addr, ts in sent_recipients.items()
        if ts >= cutoff_7d
    }

    return {
        "stable_emails": len(stable["emails"]),
        "stable_domains": list(sorted(stable["domains"])),
        "sent_recipients_total": len(sent_recipients),
        "sent_recipients_last_7d": len(recent),
        "sent_recipients_recent": sorted(recent.keys()),
        "cache_age_seconds": (
            int(time.monotonic() - _sent_cache["fetched_at"])
            if _sent_cache["fetched_at"] else None
        ),
    }


async def get_recent_emails(**kwargs) -> List[Dict]:
    """Unfiltered recent emails — diagnostic use only."""
    client = get_client()
    if not client.is_configured():
        return []
    return await client.get_recent_emails(**kwargs)


async def get_upcoming_events(**kwargs) -> List[Dict]:
    client = get_client()
    if not client.is_configured():
        return []
    return await client.get_upcoming_events(**kwargs)


async def test_connection() -> Dict:
    client = get_client()
    if not client.is_configured():
        return {"status": "not_configured", "message": "Run gmail_auth.py to set up"}
    try:
        profile = await client.get_profile()
        if profile:
            return {
                "status": "ok",
                "email": profile.get("emailAddress"),
                "messages_total": profile.get("messagesTotal"),
                "threads_total": profile.get("threadsTotal")
            }
        return {"status": "error", "message": "Could not fetch profile"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# Legacy alias — kept so existing imports don't break
class WhitelistFilter:
    """Legacy shim — use build_stable_whitelist() + get_filtered_emails() instead."""
    def __init__(self):
        stable = build_stable_whitelist()
        self.allowed = stable

    def is_allowed(self, email_address: str) -> bool:
        if not email_address:
            return False
        addr = email_address.lower().strip()
        if addr in self.allowed["emails"]:
            return True
        domain = addr.split("@")[-1]
        return domain in self.allowed["domains"]

    def filter(self, emails: List[Dict]) -> List[Dict]:
        return [e for e in emails if self.is_allowed(e.get("from", {}).get("address", ""))]
