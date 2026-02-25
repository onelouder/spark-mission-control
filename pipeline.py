#!/usr/bin/env python3
"""
Email Processing Pipeline - Handles email filtering and analysis
"""

import json
import os
import re
import httpx
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from contacts import load_contacts, get_contact_tier
from analyzer import classify_email_triage, analyze_email_content
from gmail_client import get_filtered_emails


# Configuration
DATA_DIR = "data"
PROCESSED_EMAILS_FILE = os.path.join(DATA_DIR, "processed_emails.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
DECAPODA_BASE_URL = "http://localhost:8766"


def load_config() -> Dict:
    """Load pipeline configuration"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def load_processed_emails() -> Dict:
    """Load processed emails from cache"""
    try:
        with open(PROCESSED_EMAILS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "last_sync": None,
            "emails": {},
            "filtered": {}
        }


def save_processed_emails(data: Dict) -> None:
    """Save processed emails to cache"""
    with open(PROCESSED_EMAILS_FILE, 'w') as f:
        json.dump(data, f, indent=2)


async def fetch_emails_from_decapoda(limit: int = 100, unread_only: bool = False) -> List[Dict]:
    """Fetch emails from Decapoda API"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(f"{DECAPODA_BASE_URL}/v1/email/inbox", params={
                "limit": limit,
                "unread_only": unread_only
            })
            
            if response.status_code == 200:
                data = response.json()
                return data.get("value", [])
            else:
                print(f"Decapoda API error: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"Failed to fetch emails: {e}")
            return []


async def fetch_email_content(email_id: str) -> Optional[Dict]:
    """Fetch full email content by ID"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(f"{DECAPODA_BASE_URL}/v1/email/message/{email_id}")
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Failed to fetch email {email_id}: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"Error fetching email content: {e}")
            return None


def stage1_fast_filter(email: Dict, contacts: Dict, config: Dict) -> Tuple[bool, str, str]:
    """
    Stage 1: Fast Filter (no LLM)
    Returns: (should_pass, tag, reason)
    """
    
    from_info = email.get("from", {})
    if isinstance(from_info, dict):
        from_address = from_info.get("address", "").lower()
        from_name = from_info.get("name", "")
    else:
        from_address = str(from_info).lower()
        from_name = ""
    
    if not from_address or "@" not in from_address:
        return False, "invalid", "Invalid sender address"
    
    domain = from_address.split("@")[1]
    company_domain = config.get("company_domain", "novvi.com")
    
    # Check blocked patterns first
    blocked_patterns = config.get("blocked_patterns", [])
    for pattern in blocked_patterns:
        if pattern.lower() in from_address:
            return False, "blocked_pattern", f"Matches blocked pattern: {pattern}"
    
    # Check blocked domains
    blocked_domains = config.get("blocked_domains", [])
    if domain in blocked_domains:
        return False, "blocked_domain", f"Domain blocked: {domain}"
    
    # Check blocked senders
    blocked_senders = config.get("blocked_senders", [])
    if from_address in blocked_senders:
        return False, "blocked_sender", f"Sender blocked: {from_address}"
    
    # Company domain - always pass
    if domain == company_domain:
        return True, "internal", f"Company domain: {domain}"
    
    # Check contact tiers
    contact_tier = get_contact_tier(from_address, contacts)
    if contact_tier == "tier1":
        return True, "tier1", "Top 20 contact"
    elif contact_tier == "tier2":
        return True, "tier2", "Top 100 contact"
    elif contact_tier == "partner":
        return True, "partner", f"Partner domain: {domain}"
    
    # Unknown sender - pass to Stage 2
    return True, "unknown", "Unknown sender - needs LLM triage"


async def stage2_llm_triage(email: Dict) -> Tuple[bool, str, str]:
    """
    Stage 2: LLM Triage for unknown senders
    Returns: (should_pass, classification, reason)
    """
    
    subject = email.get("subject", "")
    from_info = email.get("from", {})
    
    if isinstance(from_info, dict):
        from_address = from_info.get("address", "")
        from_name = from_info.get("name", "")
    else:
        from_address = str(from_info)
        from_name = ""
    
    try:
        classification = await classify_email_triage(subject, from_address, from_name)
        
        # Determine if email should pass
        pass_categories = ["personal_email", "action_required", "meeting_request"]
        should_pass = classification in pass_categories
        
        reason = f"LLM classified as: {classification}"
        return should_pass, classification, reason
        
    except Exception as e:
        print(f"LLM triage failed: {e}")
        # Fallback - be conservative and pass unknown emails
        return True, "unknown_error", f"LLM error, passed by default: {e}"


async def stage3_deep_analysis(email: Dict) -> Dict:
    """
    Stage 3: Deep Analysis for all passed emails
    Returns: analysis results
    """
    
    try:
        # Get full email content if we don't have body/bodyPreview
        email_content = dict(email)
        if "body" not in email_content and "bodyPreview" not in email_content:
            try:
                full_content = await fetch_email_content(email["id"])
                if full_content:
                    email_content = full_content
            except Exception as fetch_err:
                print(f"   ⚠️ Could not fetch full email: {fetch_err}")
                # Continue with what we have (subject + from)
        
        analysis = await analyze_email_content(email_content)
        return analysis
        
    except Exception as e:
        print(f"   ⚠️ Deep analysis failed: {type(e).__name__}: {e}")
        # Return minimal analysis
        from_info = email.get('from', {})
        from_name = from_info.get('name', 'Unknown') if isinstance(from_info, dict) else str(from_info)
        return {
            "classification": "fyi",
            "summary": f"Email from {from_name}: {email.get('subject', 'No subject')}",
            "action_needed": None,
            "deadline": None,
            "urgency": "low",
            "people_mentioned": [],
            "meeting_details": None,
            "analysis_error": str(e)
        }


async def process_single_email(email: Dict, contacts: Dict, config: Dict) -> Tuple[bool, Dict]:
    """
    Process a single email through the full pipeline
    Returns: (was_processed, email_with_metadata)
    """
    
    email_id = email["id"]
    processing_start = datetime.now(timezone.utc)
    
    # Check if already processed
    processed_data = load_processed_emails()
    if email_id in processed_data.get("emails", {}):
        return False, processed_data["emails"][email_id]
    
    # Start processing
    result = {
        "email_data": email,
        "processed_at": processing_start.isoformat(),
        "pipeline_version": "1.0",
        "stages": {}
    }
    
    print(f"📧 Processing: {email.get('subject', 'No subject')[:50]}...")
    
    # Stage 1: Fast Filter
    stage1_pass, stage1_tag, stage1_reason = stage1_fast_filter(email, contacts, config)
    result["stages"]["stage1"] = {
        "passed": stage1_pass,
        "tag": stage1_tag,
        "reason": stage1_reason
    }
    
    if not stage1_pass:
        # Email filtered out
        result["final_decision"] = "filtered"
        result["filter_reason"] = stage1_reason
        print(f"   ❌ Filtered: {stage1_reason}")
        return True, result
    
    # Stage 2: LLM Triage (only for unknown senders)
    if stage1_tag == "unknown":
        stage2_pass, stage2_class, stage2_reason = await stage2_llm_triage(email)
        result["stages"]["stage2"] = {
            "passed": stage2_pass,
            "classification": stage2_class,
            "reason": stage2_reason
        }
        
        if not stage2_pass:
            result["final_decision"] = "filtered"
            result["filter_reason"] = stage2_reason
            print(f"   ❌ Filtered by LLM: {stage2_reason}")
            return True, result
    
    # Email passed filtering - proceed to Stage 3
    result["final_decision"] = "passed"
    result["contact_tier"] = stage1_tag
    print(f"   ✅ Passed ({stage1_tag})")
    
    # Stage 3: Deep Analysis
    print(f"   🔍 Analyzing content...")
    analysis = await stage3_deep_analysis(email)
    result["analysis"] = analysis
    
    print(f"   📊 Analysis: {analysis['classification']} ({analysis['urgency']} urgency)")
    
    return True, result


async def fetch_emails_from_gmail(limit: int = 100, unread_only: bool = False) -> List[Dict]:
    """Fetch emails from Gmail using whitelist"""
    try:
        # Note: whitelist is already applied by get_filtered_emails
        emails = await get_filtered_emails(max_results=limit, unread_only=unread_only)
        
        # Normalize to match Decapoda format expected by pipeline
        normalized = []
        for email in emails:
            norm = {
                "id": email.get("id"),
                "subject": email.get("subject", "(no subject)"),
                "from": email.get("from", {}), # structure matches {name, address}
                "received": email.get("received"), # ISO string
                "isRead": email.get("isRead", True),
                "snippet": email.get("snippet", ""),
                "webLink": email.get("webLink", ""),
                "hasAttachments": False, # Gmail API metadata doesn't easily give this without full fetch
                "_source": "gmail",
                "_account": "jwells@gmail.com"
            }
            normalized.append(norm)
        return normalized
    except Exception as e:
        print(f"Failed to fetch Gmail: {e}")
        return []


async def sync_and_process_emails(max_emails: int = 100) -> Dict:
    """
    Main pipeline function - sync and process new emails
    """
    
    print("🚀 Starting email sync and processing...")
    
    # Load dependencies
    contacts = load_contacts()
    config = load_config()
    processed_data = load_processed_emails()
    
    # Fetch emails
    emails = []
    
    if config.get("enable_office365", True):
        print(f"📥 Fetching up to {max_emails} emails from Office365...")
        o365_emails = await fetch_emails_from_decapoda(limit=max_emails)
        emails.extend(o365_emails)
    
    if config.get("enable_gmail", False):
        print(f"📥 Fetching up to {max_emails} emails from Gmail...")
        gmail_emails = await fetch_emails_from_gmail(limit=max_emails)
        emails.extend(gmail_emails)
    
    print(f"📧 Retrieved {len(emails)} emails total")
    
    if not emails:
        print("❌ No emails retrieved")
        return {"new_processed": 0, "filtered": 0, "passed": 0, "errors": ["No emails found"]}
    
    # Process emails
    new_processed = 0
    newly_filtered = 0
    newly_passed = 0
    errors = []
    
    current_emails = processed_data.get("emails", {})
    current_filtered = processed_data.get("filtered", {})
    
    for email in emails:
        try:
            was_new, result = await process_single_email(email, contacts, config)
            
            if was_new:
                new_processed += 1
                
                if result["final_decision"] == "filtered":
                    current_filtered[email["id"]] = result
                    newly_filtered += 1
                else:
                    current_emails[email["id"]] = result
                    newly_passed += 1
                    
        except Exception as e:
            error_msg = f"Failed to process email {email.get('id', 'unknown')}: {e}"
            print(f"   ❌ {error_msg}")
            errors.append(error_msg)
    
    # Update processed data
    processed_data.update({
        "last_sync": datetime.now(timezone.utc).isoformat(),
        "emails": current_emails,
        "filtered": current_filtered
    })
    
    save_processed_emails(processed_data)
    
    # Summary
    summary = {
        "new_processed": new_processed,
        "filtered": newly_filtered,
        "passed": newly_passed,
        "total_emails": len(current_emails),
        "total_filtered": len(current_filtered),
        "errors": errors
    }
    
    print(f"✅ Processing complete:")
    print(f"   📧 New processed: {new_processed}")
    print(f"   ✅ Passed: {newly_passed}")
    print(f"   ❌ Filtered: {newly_filtered}")
    print(f"   📊 Total in system: {len(current_emails)} passed, {len(current_filtered)} filtered")
    
    return summary


def get_dashboard_data() -> Dict:
    """Get processed emails organized for dashboard display"""
    processed_data = load_processed_emails()
    emails = processed_data.get("emails", {})
    
    # Organize by classification
    dashboard = {
        "needs_response": [],
        "action_items": [],
        "meeting_requests": [],
        "fyi": [],
        "stats": {
            "total_passed": len(emails),
            "total_filtered": len(processed_data.get("filtered", {})),
            "last_sync": processed_data.get("last_sync")
        }
    }
    
    for email_id, email_data in emails.items():
        # Skip emails that have been actioned (archived, deleted, snoozed)
        action = email_data.get("action")
        if action in ("archive", "delete", "archived", "deleted"):
            continue
        if action == "snooze":
            # Check if snooze has expired (default 1 hour)
            action_at = email_data.get("action_at")
            if action_at:
                snooze_until = datetime.fromisoformat(action_at.replace('Z', '+00:00')) + timedelta(hours=1)
                if datetime.now(timezone.utc) < snooze_until:
                    continue  # Still snoozed
        
        analysis = email_data.get("analysis", {})
        classification = analysis.get("classification", "fyi")
        
        # Prepare email card data
        email_card = {
            "id": email_id,
            "subject": email_data["email_data"].get("subject", "No subject"),
            "from": email_data["email_data"].get("from", {}),
            "received": email_data["email_data"].get("received"),
            "webLink": email_data["email_data"].get("webLink"),
            "contact_tier": email_data.get("contact_tier", "unknown"),
            "urgency": analysis.get("urgency", "low"),
            "summary": analysis.get("summary", ""),
            "action_needed": analysis.get("action_needed"),
            "deadline": analysis.get("deadline"),
            "people_mentioned": analysis.get("people_mentioned", []),
            "meeting_details": analysis.get("meeting_details"),
            "processed_at": email_data.get("processed_at")
        }
        
        # Add to appropriate category
        if classification == "needs_response":
            dashboard["needs_response"].append(email_card)
        elif classification == "action_item":
            dashboard["action_items"].append(email_card)
        elif classification == "meeting_request":
            dashboard["meeting_requests"].append(email_card)
        else:
            dashboard["fyi"].append(email_card)
    
    # Sort by urgency and recency
    for category in ["needs_response", "action_items", "meeting_requests", "fyi"]:
        dashboard[category].sort(key=lambda x: (
            {"high": 0, "medium": 1, "low": 2}.get(x["urgency"], 2),
            x["received"] or ""
        ), reverse=True)
    
    return dashboard


if __name__ == "__main__":
    import asyncio
    
    async def main():
        # Test the pipeline
        result = await sync_and_process_emails(max_emails=20)
        print(f"\n📊 Pipeline Results:")
        print(json.dumps(result, indent=2))
        
        # Show dashboard data
        dashboard = get_dashboard_data()
        print(f"\n📧 Dashboard Summary:")
        print(f"Needs Response: {len(dashboard['needs_response'])}")
        print(f"Action Items: {len(dashboard['action_items'])}")
        print(f"Meeting Requests: {len(dashboard['meeting_requests'])}")
        print(f"FYI: {len(dashboard['fyi'])}")
    
    asyncio.run(main())