#!/usr/bin/env python3
"""
Seed Gmail top-senders into contacts.json from the top-sender markdown files.
Run once to initialize; contacts.py handles ongoing updates from Gmail's sent box.
"""

import json
import re
import os
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CONTACTS_FILE = os.path.join(DATA_DIR, "contacts.json")

# === Parse top-sender markdown files ===

TOP40_PATH = "/home/jwells/projects/mail_gateway/top_40_email_addresses novvi.md"
TOP100_PATH = "/home/jwells/projects/mail_gateway/Top 100 Real Contacts gmail.md"

# Own addresses / auto-replies to always exclude from briefing
OWN_ADDRESSES = {
    "cjwells@gmail.com", "cwells@gmail.com", "wells@novvi.com",
    "jwells0044@protonmail.com", "cjwells0044@protonmail.com",
    "arjwells@gmail.com", "wells37151@gmail.com", "cardentwells@gmail.com",
    "mwells.misc@gmail.com",
}

# Craigslist / junk patterns to skip
SKIP_PATTERNS = ["craigslist.org", "godaddy.com", "ccsend.com", "breberrysells"]

EMAIL_RE = re.compile(r'[\w.+%-]+@[\w.-]+\.[a-zA-Z]{2,}')

def parse_contacts_from_md(path: str, tier: str) -> list[dict]:
    """Parse email contacts from the markdown file."""
    contacts = []
    seen = set()

    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"  ⚠️  File not found: {path}")
        return []

    current_section = "unknown"
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Section headers (no email address)
        if not any(c in line for c in ["@"]):
            current_section = line.rstrip(":")
            continue

        emails = EMAIL_RE.findall(line)
        if not emails:
            continue

        # Parse count from line like "- 127+ emails"
        count_match = re.search(r'(\d+)\+?\s*email', line, re.I)
        count = int(count_match.group(1)) if count_match else 1

        # Extract name hint (text before the email, if any)
        name = ""
        # "Eduardo Baralt - baralt@novvi.com (45 emails)"
        name_match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*[-–]', line)
        if name_match:
            name = name_match.group(1).strip()

        for email in emails:
            email_lc = email.lower()
            if email_lc in seen or email_lc in OWN_ADDRESSES:
                continue
            if any(pat in email_lc for pat in SKIP_PATTERNS):
                continue
            seen.add(email_lc)
            contacts.append({
                "email": email_lc,
                "name": name,
                "count": count,
                "domain": email_lc.split("@")[-1],
                "section": current_section,
                "tier": tier,
            })

    return contacts


def load_contacts() -> dict:
    try:
        with open(CONTACTS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_contacts(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONTACTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def main():
    print("🔍 Parsing Gmail top-sender lists...")

    novvi_contacts = parse_contacts_from_md(TOP40_PATH, tier="novvi")
    gmail_contacts = parse_contacts_from_md(TOP100_PATH, tier="personal")

    print(f"   Novvi/work list:    {len(novvi_contacts)} contacts")
    print(f"   Gmail personal list: {len(gmail_contacts)} contacts")

    # High-priority: top 20 by count (family + heavy hitters)
    combined = novvi_contacts + gmail_contacts
    combined_sorted = sorted(combined, key=lambda c: c["count"], reverse=True)

    # Deduplicate across both lists (novvi may include wells@novvi.com etc.)
    seen_emails = set()
    deduped = []
    for c in combined_sorted:
        if c["email"] not in seen_emails:
            seen_emails.add(c["email"])
            deduped.append(c)

    gmail_top20 = deduped[:20]
    gmail_top_senders = deduped  # all contacts for whitelist

    # Load existing contacts.json and merge
    contacts = load_contacts()

    # Preserve existing Exchange-derived top20/top100
    contacts["gmail_top20"] = gmail_top20
    contacts["gmail_top_senders"] = gmail_top_senders
    contacts["gmail_seeded_at"] = datetime.now(timezone.utc).isoformat()

    # Also enrich partner_domains with domains from top contacts (count >= 5)
    existing_domains = set(contacts.get("partner_domains", []))
    for c in deduped:
        if c["count"] >= 5 and not c["domain"].endswith(("gmail.com", "yahoo.com", "hotmail.com", "mac.com", "me.com", "icloud.com", "outlook.com", "protonmail.com")):
            existing_domains.add(c["domain"])
    contacts["partner_domains"] = sorted(existing_domains)

    save_contacts(contacts)

    print(f"\n✅ contacts.json updated:")
    print(f"   gmail_top20:       {len(gmail_top20)} entries")
    print(f"   gmail_top_senders: {len(gmail_top_senders)} entries")
    print(f"   partner_domains:   {len(contacts['partner_domains'])} domains")
    print(f"\nTop 10 Gmail contacts:")
    for c in gmail_top20[:10]:
        print(f"   {c['count']:3d} emails  {c['email']:<45}  ({c['section']})")


if __name__ == "__main__":
    main()
