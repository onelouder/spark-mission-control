#!/usr/bin/env python3
"""
Contact Ranker - Builds and maintains contact rankings for email filtering
"""

import json
import os
import time
from datetime import datetime, timezone
from collections import Counter, defaultdict
from typing import Dict, List, Optional
import httpx

# Configuration
DATA_DIR = "data"
CONTACTS_FILE = os.path.join(DATA_DIR, "contacts.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
DECAPODA_BASE_URL = "http://localhost:8766"


def load_config() -> Dict:
    """Load configuration from config.json"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "company_domain": "novvi.com",
            "pinned_domains": [],
            "blocked_domains": [],
            "blocked_senders": [],
        }


def load_contacts() -> Dict:
    """Load existing contact rankings"""
    try:
        with open(CONTACTS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "last_updated": None,
            "top20": [],
            "top100": [],
            "partner_domains": [],
            "pinned_domains": [],
            "blocked_senders": [],
            "blocked_domains": []
        }


def save_contacts(contacts: Dict) -> None:
    """Save contact rankings to file"""
    with open(CONTACTS_FILE, 'w') as f:
        json.dump(contacts, f, indent=2)


async def fetch_sent_emails(limit: int = 1000) -> List[Dict]:
    """
    Fetch sent emails from Decapoda API to analyze contact patterns
    Try sent folder first, fallback to inbox if not available
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Try to fetch sent items first
            response = await client.get(f"{DECAPODA_BASE_URL}/v1/email/search", params={
                "q": "folder:Sent",
                "limit": limit
            })
            
            if response.status_code == 200:
                sent_data = response.json()
                if sent_data.get("value"):
                    return sent_data["value"]
            
            # Fallback: fetch inbox and look for emails from company domain
            response = await client.get(f"{DECAPODA_BASE_URL}/v1/email/inbox", params={
                "limit": limit,
                "unread_only": False
            })
            
            if response.status_code == 200:
                inbox_data = response.json()
                return inbox_data.get("value", [])
            
        except Exception as e:
            print(f"Error fetching emails: {e}")
            
    return []


async def analyze_email_patterns(emails: List[Dict]) -> Dict:
    """Analyze email patterns to build contact rankings"""
    config = load_config()
    company_domain = config.get("company_domain", "novvi.com")
    
    # Count email interactions by recipient
    contact_counts = Counter()
    domain_counts = Counter()
    
    for email in emails:
        try:
            # Extract recipient information - handle various formats
            from_addr = email.get("from")
            email_addr = None
            name = ""
            
            if isinstance(from_addr, dict) and from_addr:
                email_addr = from_addr.get("address", "")
                name = from_addr.get("name", "")
            elif isinstance(from_addr, str) and from_addr:
                email_addr = from_addr
                name = ""
            else:
                # Skip emails with no sender information
                print(f"Skipping email with invalid from field: {from_addr}")
                continue
            
            if not email_addr or "@" not in str(email_addr):
                print(f"Skipping email with invalid email address: {email_addr}")
                continue
                
            email_addr = str(email_addr).lower().strip()
            domain = email_addr.split("@")[1]
            
            # Skip company domain emails for external contact ranking
            if domain != company_domain:
                contact_counts[email_addr] += 1
                domain_counts[domain] += 1
                
        except Exception as e:
            print(f"Error processing email: {e}")
            print(f"Email data: {email}")
            continue
    
    # Get top contacts
    top_contacts = contact_counts.most_common(100)
    
    # Build contact list with metadata
    contact_list = []
    for email_addr, count in top_contacts:
        domain = email_addr.split("@")[1]
        contact_list.append({
            "email": email_addr,
            "name": extract_name_from_email(email_addr),
            "count": count,
            "domain": domain
        })
    
    # Auto-discover partner domains (domains with multiple contacts in top 100)
    partner_domains = []
    domain_contact_counts = defaultdict(int)
    
    for contact in contact_list:
        domain_contact_counts[contact["domain"]] += 1
    
    # Consider domains with 3+ contacts as potential partners
    for domain, contact_count in domain_contact_counts.items():
        if contact_count >= 3 and domain != company_domain:
            partner_domains.append(domain)
    
    # Add company domain to partners
    partner_domains.insert(0, company_domain)
    
    return {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "top20": contact_list[:20],
        "top100": contact_list,
        "partner_domains": sorted(set(partner_domains)),
        "pinned_domains": config.get("pinned_domains", []),
        "blocked_senders": config.get("blocked_senders", []),
        "blocked_domains": config.get("blocked_domains", [])
    }


def extract_name_from_email(email_addr: str) -> str:
    """Extract a human-readable name from email address"""
    local_part = email_addr.split("@")[0]
    
    # Handle common patterns
    if "." in local_part:
        parts = local_part.split(".")
        name = " ".join(part.capitalize() for part in parts)
    else:
        name = local_part.capitalize()
    
    return name


async def refresh_contact_rankings() -> Dict:
    """Main function to refresh contact rankings"""
    print("🔄 Refreshing contact rankings...")
    
    # Fetch recent emails
    emails = await fetch_sent_emails(limit=2000)
    print(f"📧 Analyzed {len(emails)} emails")
    
    if not emails:
        print("⚠️  No emails found - using inbox as fallback")
        return load_contacts()
    
    # Analyze patterns and build rankings
    contacts = await analyze_email_patterns(emails)
    
    # Save to file
    save_contacts(contacts)
    
    print(f"✅ Contact rankings updated:")
    print(f"   - Top 20: {len(contacts['top20'])} contacts")
    print(f"   - Top 100: {len(contacts['top100'])} contacts")
    print(f"   - Partner domains: {len(contacts['partner_domains'])} domains")
    
    return contacts


def get_contact_tier(email_addr: str, contacts: Dict) -> Optional[str]:
    """
    Determine contact tier for an email address
    Returns: 'internal', 'tier1', 'tier2', 'partner', or None
    """
    email_addr = email_addr.lower().strip()
    domain = email_addr.split("@")[1] if "@" in email_addr else ""
    
    config = load_config()
    company_domain = config.get("company_domain", "novvi.com")
    
    # Check company domain
    if domain == company_domain:
        return "internal"
    
    # Check pinned contacts (specific addresses, e.g. personal gmail)
    pinned_contacts = {c.lower() for c in contacts.get("pinned_contacts", [])}
    if email_addr in pinned_contacts:
        return "tier1"
    
    # Check top 20 (Exchange-derived)
    top20_emails = {contact["email"].lower() for contact in contacts.get("top20", [])}
    if email_addr in top20_emails:
        return "tier1"

    # Check Gmail top 20 (personal/family top senders)
    gmail_top20_emails = {contact["email"].lower() for contact in contacts.get("gmail_top20", [])}
    if email_addr in gmail_top20_emails:
        return "tier1"

    # Check top 100 (Exchange-derived)
    top100_emails = {contact["email"].lower() for contact in contacts.get("top100", [])}
    if email_addr in top100_emails:
        return "tier2"

    # Check Gmail top senders (full list)
    gmail_senders = {contact["email"].lower() for contact in contacts.get("gmail_top_senders", [])}
    if email_addr in gmail_senders:
        return "tier2"
    
    # Check partner/pinned domains (from both contacts file and config)
    partner_domains = set(contacts.get("partner_domains", []))
    config_pinned = set(config.get("pinned_domains", []))
    all_partner_domains = partner_domains.union(config_pinned)
    
    if domain in all_partner_domains:
        return "partner"
    
    return None


if __name__ == "__main__":
    import asyncio
    
    async def main():
        contacts = await refresh_contact_rankings()
        print(f"\n📊 Contact Rankings Summary:")
        print(f"Last updated: {contacts['last_updated']}")
        print(f"Top 5 contacts:")
        for i, contact in enumerate(contacts['top20'][:5], 1):
            print(f"  {i}. {contact['name']} ({contact['email']}) - {contact['count']} emails")
    
    asyncio.run(main())