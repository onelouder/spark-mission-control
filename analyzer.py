#!/usr/bin/env python3
"""
LLM Analyzer - Uses LLM to analyze and classify emails
"""

import json
import httpx
from typing import Dict, Optional
from datetime import datetime


def load_config() -> Dict:
    """Load configuration"""
    try:
        with open("data/config.json", 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


# Use Ollama directly - no gateway contention
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen3:30b-a3b"  # Fast, good at classification


async def call_llm(messages: list, max_tokens: int = 500, timeout: int = 30) -> Optional[str]:
    """Call Ollama LLM API directly - bypasses gateway concurrency limits"""
    
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.1
        }
    }
    
    try:
        tm = httpx.Timeout(connect=5.0, read=float(timeout), write=5.0, pool=5.0)
        async with httpx.AsyncClient(timeout=tm) as client:
            response = await client.post(OLLAMA_URL, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("message", {}).get("content", "")
            else:
                print(f"Ollama API error: {response.status_code} - {response.text[:200]}")
                return None
                
    except httpx.TimeoutException:
        print(f"Ollama call timed out after {timeout}s")
        return None
    except Exception as e:
        print(f"Ollama call failed: {type(e).__name__}: {e}")
        return None


async def classify_email_triage(subject: str, from_address: str, from_name: str = "") -> str:
    """
    Stage 2 - LLM Triage for unknown senders
    Returns: personal_email, action_required, meeting_request, newsletter, sales_outreach, automated_notification
    """
    
    prompt = f"""Classify this email based on the subject line and sender information:

Subject: {subject}
From: {from_name} <{from_address}>

Classify into ONE of these categories:
- personal_email: Personal communication from an individual
- action_required: Email requiring response or action from recipient  
- meeting_request: Meeting invitation, scheduling, or calendar-related
- newsletter: Newsletter, digest, or regular publication
- sales_outreach: Sales emails, marketing, promotional content
- automated_notification: System notifications, automated alerts, confirmations

Return only the category name, nothing else."""

    messages = [{"role": "user", "content": prompt}]
    
    result = await call_llm(messages, max_tokens=50, timeout=15)
    
    if result:
        classification = result.strip().lower()
        valid_categories = [
            "personal_email", "action_required", "meeting_request", 
            "newsletter", "sales_outreach", "automated_notification"
        ]
        if classification in valid_categories:
            return classification
    
    # Fallback to simple keyword-based classification
    return fallback_classify_triage(subject, from_address)


def fallback_classify_triage(subject: str, from_address: str) -> str:
    """Fallback classification when LLM is unavailable"""
    subject_lower = subject.lower()
    from_lower = from_address.lower()
    
    # Meeting requests
    if any(word in subject_lower for word in ["meeting", "call", "schedule", "calendar", "invite", "zoom", "teams"]):
        return "meeting_request"
    
    # Action required
    if any(word in subject_lower for word in ["urgent", "asap", "please reply", "response", "deadline", "approval", "review", "decision"]):
        return "action_required"
    
    # Newsletters
    if any(word in subject_lower for word in ["newsletter", "digest", "weekly", "monthly", "update", "bulletin"]):
        return "newsletter"
    
    # Automated notifications
    if any(pattern in from_lower for pattern in ["no-reply", "noreply", "notification", "system", "automated"]):
        return "automated_notification"
    
    # Sales outreach
    if any(word in subject_lower for word in ["demo", "trial", "offer", "discount", "promotion", "partnership"]):
        return "sales_outreach"
    
    # Default to personal email
    return "personal_email"


def extract_body_text(email_content: Dict) -> str:
    """Extract plain text from email body, handling dict/html formats"""
    body = email_content.get("body", "")
    
    # Body can be a dict with contentType + content (Graph API format)
    if isinstance(body, dict):
        body = body.get("content", "")
    
    if not isinstance(body, str):
        body = str(body) if body else ""
    
    # Strip HTML tags (basic)
    import re
    body = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r'<[^>]+>', ' ', body)
    body = re.sub(r'&nbsp;', ' ', body)
    body = re.sub(r'&[a-zA-Z]+;', ' ', body)
    body = re.sub(r'\s+', ' ', body).strip()
    
    # Fallback to bodyPreview if body is empty or too short
    if len(body) < 20:
        body = email_content.get("bodyPreview", body)
    
    return body[:2000]


async def analyze_email_content(email_content: Dict) -> Dict:
    """
    Stage 3 - Deep Analysis of email content
    Returns detailed analysis including classification, summary, actions, etc.
    """
    
    subject = email_content.get("subject", "")
    body = extract_body_text(email_content)
    from_name = email_content.get("from", {}).get("name", "")
    from_address = email_content.get("from", {}).get("address", "")
    
    prompt = f"""Analyze this email and extract key information:

Subject: {subject}
From: {from_name} <{from_address}>
Body: {body}

Return a JSON object with these fields:
{{
  "classification": "needs_response|action_item|meeting_request|fyi",
  "summary": "One-line summary of the email content",
  "action_needed": "What the recipient needs to do (if anything)",
  "deadline": "Extracted deadline if mentioned, null otherwise",
  "urgency": "high|medium|low",
  "people_mentioned": ["list", "of", "names"],
  "meeting_details": {{"proposed_time": "...", "location": "...", "attendees": []}} // only if meeting_request
}}

Guidelines:
- needs_response: Email explicitly asks for a reply
- action_item: Email contains tasks or requests for action  
- meeting_request: Email about scheduling or meeting coordination
- fyi: Informational only, no action required
- deadline: Extract any mentioned deadlines in YYYY-MM-DD format if possible
- urgency: Based on language, deadlines, and sender importance
- people_mentioned: Extract names mentioned in email body

Return only valid JSON, no other text."""

    messages = [{"role": "user", "content": prompt}]
    
    result = await call_llm(messages, max_tokens=800, timeout=30)
    
    if result:
        try:
            # Clean up the result (remove any markdown formatting)
            clean_result = result.strip()
            
            # Extract JSON from markdown code blocks if present
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', clean_result, re.DOTALL)
            if json_match:
                clean_result = json_match.group(1)
            else:
                # Try to find raw JSON object
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', clean_result, re.DOTALL)
                if json_match:
                    clean_result = json_match.group(0)
            
            analysis = json.loads(clean_result.strip())
            
            # Validate required fields
            required_fields = ["classification", "summary", "urgency"]
            for field in required_fields:
                if field not in analysis:
                    return fallback_analyze_content(email_content)
            
            return analysis
            
        except json.JSONDecodeError as e:
            print(f"Failed to parse LLM analysis: {e}")
            print(f"Raw result: {result}")
            return fallback_analyze_content(email_content)
    
    return fallback_analyze_content(email_content)


def fallback_analyze_content(email_content: Dict) -> Dict:
    """Fallback analysis when LLM is unavailable"""
    subject = email_content.get("subject", "")
    body = extract_body_text(email_content)
    from_name = email_content.get("from", {}).get("name", "")
    
    subject_lower = subject.lower()
    body_lower = body.lower()
    
    # Determine classification
    if any(word in subject_lower or word in body_lower for word in ["reply", "response", "please let me know", "thoughts?"]):
        classification = "needs_response"
    elif any(word in subject_lower for word in ["meeting", "call", "schedule", "calendar"]):
        classification = "meeting_request"
    elif any(word in subject_lower or word in body_lower for word in ["urgent", "asap", "deadline", "please", "can you"]):
        classification = "action_item"
    else:
        classification = "fyi"
    
    # Determine urgency
    if any(word in subject_lower or word in body_lower for word in ["urgent", "asap", "immediate", "critical"]):
        urgency = "high"
    elif any(word in subject_lower or word in body_lower for word in ["soon", "this week", "deadline"]):
        urgency = "medium"
    else:
        urgency = "low"
    
    # Extract basic info
    return {
        "classification": classification,
        "summary": f"Email from {from_name or 'Unknown'}: {subject[:100]}",
        "action_needed": "Review email content" if classification != "fyi" else None,
        "deadline": None,
        "urgency": urgency,
        "people_mentioned": [],
        "meeting_details": None
    }


async def test_llm_connection() -> bool:
    """Test if LLM endpoint is available"""
    try:
        result = await call_llm([{"role": "user", "content": "Reply with 'OK'"}], max_tokens=10, timeout=10)
        return result is not None and "ok" in result.lower()
    except:
        return False


if __name__ == "__main__":
    import asyncio
    
    async def test():
        print("Testing LLM connection...")
        is_connected = await test_llm_connection()
        print(f"LLM Status: {'✅ Connected' if is_connected else '❌ Unavailable'}")
        
        if is_connected:
            # Test triage
            classification = await classify_email_triage(
                "Quick sync meeting tomorrow?", 
                "john.doe@example.com",
                "John Doe"
            )
            print(f"Triage test: {classification}")
            
            # Test analysis
            test_email = {
                "subject": "Q4 planning meeting - need your input",
                "body": "Hi, we need to schedule our Q4 planning meeting. Can you join us next Tuesday at 2pm? Please confirm by Friday.",
                "from": {"name": "Sarah Smith", "address": "sarah@company.com"}
            }
            
            analysis = await analyze_email_content(test_email)
            print(f"Analysis test: {json.dumps(analysis, indent=2)}")
    
    asyncio.run(test())