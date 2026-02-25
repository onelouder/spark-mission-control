"""
Context Aggregator for Mission Control
Pulls from multiple sources (Office365, Gmail) and tags with life domain context
Supports two-tier filtering: Context (life domain) + Account (email source)
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
import httpx

# === Paths ===
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CONTEXTS_PATH = os.path.join(DATA_DIR, "contexts.json")
ACCOUNTS_PATH = os.path.join(DATA_DIR, "accounts.json")

# === Import source clients ===
from gmail_client import get_client as get_gmail_client, GmailClient, WhitelistFilter


class ContextAggregator:
    """
    Aggregates emails and events from multiple sources,
    classifies them into life domain contexts.
    
    Two-tier filtering:
    - Context: Life domain (Novvi, Personal, Academic, Startup)
    - Account: Email source (wells@novvi.com, jwells@gmail.com, etc.)
    """
    
    def __init__(self):
        self.contexts = self._load_contexts()
        self.accounts = self._load_accounts()
        self.gmail = get_gmail_client()
        self._active_filter: Optional[str] = None
    
    def _load_contexts(self) -> Dict:
        """Load context definitions"""
        try:
            with open(CONTEXTS_PATH, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {"contexts": {}, "active_context": None}
    
    def _load_accounts(self) -> Dict:
        """Load account definitions"""
        try:
            with open(ACCOUNTS_PATH, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {"accounts": {}, "active_account_filter": None}
    
    def save_contexts(self) -> None:
        """Save context definitions"""
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CONTEXTS_PATH, 'w') as f:
            json.dump(self.contexts, f, indent=2)
    
    def save_accounts(self) -> None:
        """Save account definitions"""
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ACCOUNTS_PATH, 'w') as f:
            json.dump(self.accounts, f, indent=2)
    
    def get_context_list(self) -> List[Dict]:
        """Get list of all contexts with enabled status"""
        contexts = []
        for ctx_id, ctx in self.contexts.get("contexts", {}).items():
            contexts.append({
                "id": ctx_id,
                "name": ctx.get("name", ctx_id),
                "icon": ctx.get("icon", "📁"),
                "color": ctx.get("color", "#6b7280"),
                "enabled": ctx.get("enabled", False),
                "user_email": ctx.get("user_email", "")
            })
        return contexts
    
    def get_active_filter(self) -> Optional[str]:
        """Get current context filter (None = show all)"""
        return self.contexts.get("active_context")
    
    def set_active_filter(self, context_id: Optional[str]) -> None:
        """Set context filter (None = show all)"""
        self.contexts["active_context"] = context_id
        self.save_contexts()
    
    # === Account Methods ===
    
    def get_account_list(self) -> List[Dict]:
        """Get list of all accounts with enabled status"""
        accounts = []
        for acc_id, acc in self.accounts.get("accounts", {}).items():
            accounts.append({
                "id": acc_id,
                "name": acc.get("name", acc_id),
                "email": acc.get("email", ""),
                "provider": acc.get("provider", "unknown"),
                "icon": acc.get("icon", "📧"),
                "color": acc.get("color", "#6b7280"),
                "enabled": acc.get("enabled", False),
                "contexts": acc.get("contexts", [])
            })
        return accounts
    
    def get_active_account_filter(self) -> Optional[str]:
        """Get current account filter (None = show all)"""
        return self.accounts.get("active_account_filter")
    
    def set_active_account_filter(self, account_id: Optional[str]) -> None:
        """Set account filter (None = show all)"""
        self.accounts["active_account_filter"] = account_id
        self.save_accounts()
    
    def get_accounts_for_context(self, context_id: str) -> List[Dict]:
        """Get accounts that feed into a specific context"""
        accounts = []
        for acc_id, acc in self.accounts.get("accounts", {}).items():
            if context_id in acc.get("contexts", []) and acc.get("enabled", False):
                accounts.append({
                    "id": acc_id,
                    "name": acc.get("name", acc_id),
                    "email": acc.get("email", ""),
                    "icon": acc.get("icon", "📧"),
                    "color": acc.get("color", "#6b7280")
                })
        return accounts
    
    def classify_email(self, email: Dict) -> str:
        """
        Classify an email into a context based on matching rules
        Returns context_id
        """
        from_addr = email.get("from", {}).get("address", "").lower()
        from_name = email.get("from", {}).get("name", "").lower()
        subject = email.get("subject", "").lower()
        source = email.get("_source", "")
        account = email.get("_account", "").lower()
        
        # Extract domain from sender
        from_domain = from_addr.split("@")[-1] if "@" in from_addr else ""
        
        # Score each context
        scores: Dict[str, int] = {}
        default_context = None
        
        for ctx_id, ctx in self.contexts.get("contexts", {}).items():
            if not ctx.get("enabled", False):
                continue
                
            rules = ctx.get("match_rules", {})
            score = 0
            
            # Check if this is the default for the provider/account
            if rules.get("is_default_for_provider") and account == ctx.get("user_email", "").lower():
                default_context = ctx_id
            
            # Check account match (highest priority)
            if account in [a.lower() for a in rules.get("accounts", [])]:
                score += 100
            
            # Check domain match
            for domain in rules.get("domains", []):
                if from_domain.endswith(domain.lower()):
                    score += 50
                    break
            
            # Check keywords in from
            for kw in rules.get("keywords_from", []):
                if kw.lower() in from_addr or kw.lower() in from_name:
                    score += 30
                    break
            
            # Check keywords in subject
            for kw in rules.get("keywords_subject", []):
                if kw.lower() in subject:
                    score += 20
                    break
            
            if score > 0:
                scores[ctx_id] = score
        
        # Return highest scoring context, or default, or 'unknown'
        if scores:
            return max(scores.keys(), key=lambda k: scores[k])
        elif default_context:
            return default_context
        else:
            return "unknown"
    
    def classify_event(self, event: Dict) -> str:
        """
        Classify a calendar event into a context
        """
        source = event.get("_source", "")
        account = event.get("_account", "").lower()
        
        # For events, primarily use the source account
        for ctx_id, ctx in self.contexts.get("contexts", {}).items():
            if not ctx.get("enabled", False):
                continue
            
            rules = ctx.get("match_rules", {})
            
            # Check account match
            if account == ctx.get("user_email", "").lower():
                return ctx_id
            
            if account in [a.lower() for a in rules.get("accounts", [])]:
                return ctx_id
        
        # Check for default
        for ctx_id, ctx in self.contexts.get("contexts", {}).items():
            rules = ctx.get("match_rules", {})
            if rules.get("is_default_for_provider") and ctx.get("enabled", False):
                return ctx_id
        
        return "unknown"
    
    async def fetch_office365_emails(self, days_back: int = 7, max_results: int = 100) -> List[Dict]:
        """Fetch emails from Office365 via decapoda-lite"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"http://localhost:8766/v1/email/inbox",
                    params={"count": max_results}
                )
                response.raise_for_status()
                data = response.json()
                
                emails = []
                for msg in data.get("value", []):
                    # Normalize to common format
                    email = {
                        "id": msg.get("id"),
                        "subject": msg.get("subject", "(no subject)"),
                        "from": {
                            "name": msg.get("from", {}).get("emailAddress", {}).get("name", ""),
                            "address": msg.get("from", {}).get("emailAddress", {}).get("address", "")
                        },
                        "received": msg.get("receivedDateTime"),
                        "isRead": msg.get("isRead", True),
                        "snippet": msg.get("bodyPreview", ""),
                        "webLink": msg.get("webLink", ""),
                        "hasAttachments": msg.get("hasAttachments", False),
                        "_source": "office365",
                        "_account": "wells@novvi.com"
                    }
                    email["context_id"] = self.classify_email(email)
                    emails.append(email)
                
                return emails
        except Exception as e:
            print(f"Office365 fetch error: {e}")
            return []
    
    async def fetch_gmail_emails(self, days_back: int = 7, max_results: int = 100) -> List[Dict]:
        """Fetch emails from Gmail"""
        if not self.gmail.is_configured():
            return []
        
        try:
            # Fetch raw (fetch more to accommodate filtering)
            raw_emails = await self.gmail.get_recent_emails(
                days_back=days_back,
                max_results=max_results * 4
            )
            
            # Filter against whitelist
            wf = WhitelistFilter()
            emails = wf.filter(raw_emails)
            
            # Trim to requested limit
            emails = emails[:max_results]
            
            # Add context classification
            for email in emails:
                email["context_id"] = self.classify_email(email)
            
            return emails
        except Exception as e:
            print(f"Gmail fetch error: {e}")
            return []
    
    async def fetch_office365_events(self, days: int = 7, max_results: int = 50) -> List[Dict]:
        """Fetch calendar events from Office365 via decapoda-lite"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"http://localhost:8766/v1/calendar/next",
                    params={"days": days, "limit": max_results}
                )
                response.raise_for_status()
                data = response.json()
                
                events = []
                for evt in data.get("value", []):
                    event = {
                        "id": evt.get("id"),
                        "subject": evt.get("subject", "(no title)"),
                        "start": evt.get("start", {}).get("dateTime"),
                        "end": evt.get("end", {}).get("dateTime"),
                        "location": evt.get("location", {}).get("displayName", ""),
                        "attendees": evt.get("attendees", []),
                        "webLink": evt.get("webLink", ""),
                        "isCancelled": evt.get("isCancelled", False),
                        "_source": "office365",
                        "_account": "wells@novvi.com"
                    }
                    event["context_id"] = self.classify_event(event)
                    events.append(event)
                
                return events
        except Exception as e:
            print(f"Office365 calendar fetch error: {e}")
            return []
    
    async def fetch_gmail_events(self, days: int = 7, max_results: int = 50) -> List[Dict]:
        """Fetch calendar events from Google Calendar"""
        if not self.gmail.is_configured():
            return []
        
        try:
            events = await self.gmail.get_upcoming_events(
                days=days,
                max_results=max_results
            )
            
            # Add context classification
            for event in events:
                event["context_id"] = self.classify_event(event)
            
            return events
        except Exception as e:
            print(f"Google Calendar fetch error: {e}")
            return []
    
    async def get_all_emails(self, days_back: int = 7, max_results: int = 100,
                             context_filter: Optional[str] = None,
                             account_filter: Optional[str] = None) -> List[Dict]:
        """
        Get emails from all sources, optionally filtered by context and/or account
        """
        all_emails = []
        
        # Get active filters
        active_context = context_filter or self.get_active_filter()
        active_account = account_filter or self.get_active_account_filter()
        
        # Determine which accounts to fetch from
        accounts_to_fetch = []
        for acc_id, acc in self.accounts.get("accounts", {}).items():
            if not acc.get("enabled", False):
                continue
            # If account filter is set, only fetch from that account
            if active_account and acc_id != active_account:
                continue
            # If context filter is set, only fetch from accounts in that context
            if active_context and active_context not in acc.get("contexts", []):
                continue
            accounts_to_fetch.append(acc)
        
        # Fetch from each account
        for acc in accounts_to_fetch:
            if acc.get("provider") == "office365":
                emails = await self.fetch_office365_emails(days_back, max_results)
                for e in emails:
                    e["account_id"] = acc.get("id", "novvi-outlook")
                all_emails.extend(emails)
            elif acc.get("provider") == "gmail":
                # For now, only personal-gmail is configured
                if acc.get("id") == "personal-gmail":
                    emails = await self.fetch_gmail_emails(days_back, max_results)
                    for e in emails:
                        e["account_id"] = acc.get("id", "personal-gmail")
                    all_emails.extend(emails)
        
        # Apply context filter (double-check after classification)
        if active_context:
            all_emails = [e for e in all_emails if e.get("context_id") == active_context]
        
        # Sort by received date (newest first); handle None values from failed fetches
        all_emails.sort(key=lambda x: x.get("received") or "", reverse=True)
        
        return all_emails
    
    async def get_all_events(self, days: int = 7, max_results: int = 50,
                             context_filter: Optional[str] = None,
                             account_filter: Optional[str] = None) -> List[Dict]:
        """
        Get calendar events from all sources, optionally filtered by context and/or account
        """
        all_events = []
        
        # Get active filters
        active_context = context_filter or self.get_active_filter()
        active_account = account_filter or self.get_active_account_filter()
        
        # Determine which accounts to fetch from
        accounts_to_fetch = []
        for acc_id, acc in self.accounts.get("accounts", {}).items():
            if not acc.get("enabled", False):
                continue
            if active_account and acc_id != active_account:
                continue
            if active_context and active_context not in acc.get("contexts", []):
                continue
            accounts_to_fetch.append(acc)
        
        # Fetch from each account
        for acc in accounts_to_fetch:
            if acc.get("provider") == "office365":
                events = await self.fetch_office365_events(days, max_results)
                for e in events:
                    e["account_id"] = acc.get("id", "novvi-outlook")
                all_events.extend(events)
            elif acc.get("provider") == "gmail":
                if acc.get("id") == "personal-gmail":
                    events = await self.fetch_gmail_events(days, max_results)
                    for e in events:
                        e["account_id"] = acc.get("id", "personal-gmail")
                    all_events.extend(events)
        
        # Filter cancelled events
        all_events = [e for e in all_events if not e.get("isCancelled", False)]
        
        # Apply context filter
        if active_context:
            all_events = [e for e in all_events if e.get("context_id") == active_context]
        
        # Sort by start time; handle None values from events missing dateTime
        all_events.sort(key=lambda x: x.get("start") or "")
        
        return all_events
    
    async def get_aggregated_data(self, context_filter: Optional[str] = None,
                                   account_filter: Optional[str] = None) -> Dict:
        """
        Get aggregated data from all sources with context and account info
        """
        emails = await self.get_all_emails(context_filter=context_filter, 
                                           account_filter=account_filter)
        events = await self.get_all_events(context_filter=context_filter,
                                           account_filter=account_filter)
        
        # Group by context for stats
        context_stats = {}
        for email in emails:
            ctx = email.get("context_id", "unknown")
            if ctx not in context_stats:
                context_stats[ctx] = {"emails": 0, "unread": 0, "events": 0}
            context_stats[ctx]["emails"] += 1
            if not email.get("isRead", True):
                context_stats[ctx]["unread"] += 1
        
        for event in events:
            ctx = event.get("context_id", "unknown")
            if ctx not in context_stats:
                context_stats[ctx] = {"emails": 0, "unread": 0, "events": 0}
            context_stats[ctx]["events"] += 1
        
        # Group by account for stats
        account_stats = {}
        for email in emails:
            acc = email.get("account_id", "unknown")
            if acc not in account_stats:
                account_stats[acc] = {"emails": 0, "unread": 0, "events": 0}
            account_stats[acc]["emails"] += 1
            if not email.get("isRead", True):
                account_stats[acc]["unread"] += 1
        
        for event in events:
            acc = event.get("account_id", "unknown")
            if acc not in account_stats:
                account_stats[acc] = {"emails": 0, "unread": 0, "events": 0}
            account_stats[acc]["events"] += 1
        
        return {
            "emails": emails,
            "events": events,
            "contexts": self.get_context_list(),
            "accounts": self.get_account_list(),
            "active_context_filter": self.get_active_filter(),
            "active_account_filter": self.get_active_account_filter(),
            "context_stats": context_stats,
            "account_stats": account_stats,
            "fetched_at": datetime.now(timezone.utc).isoformat()
        }


# === Module-level convenience ===

_aggregator: Optional[ContextAggregator] = None

def get_aggregator() -> ContextAggregator:
    """Get or create aggregator singleton"""
    global _aggregator
    if _aggregator is None:
        _aggregator = ContextAggregator()
    return _aggregator

async def get_all_emails(**kwargs) -> List[Dict]:
    """Convenience function to get all emails"""
    return await get_aggregator().get_all_emails(**kwargs)

async def get_all_events(**kwargs) -> List[Dict]:
    """Convenience function to get all events"""
    return await get_aggregator().get_all_events(**kwargs)

def get_contexts() -> List[Dict]:
    """Get list of contexts"""
    return get_aggregator().get_context_list()

def set_context_filter(context_id: Optional[str]) -> None:
    """Set active context filter"""
    get_aggregator().set_active_filter(context_id)

def get_context_filter() -> Optional[str]:
    """Get active context filter"""
    return get_aggregator().get_active_filter()

def get_accounts() -> List[Dict]:
    """Get list of accounts"""
    return get_aggregator().get_account_list()

def set_account_filter(account_id: Optional[str]) -> None:
    """Set active account filter"""
    get_aggregator().set_active_account_filter(account_id)

def get_account_filter() -> Optional[str]:
    """Get active account filter"""
    return get_aggregator().get_active_account_filter()

def get_accounts_for_context(context_id: str) -> List[Dict]:
    """Get accounts that feed into a context"""
    return get_aggregator().get_accounts_for_context(context_id)
