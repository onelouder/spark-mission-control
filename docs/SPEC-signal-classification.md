# Signal Classification Logic Specification

**Version:** 1.0  
**Updated:** 2026-01-28

This document defines the logic for classifying incoming interactions into signal levels.

---

## Signal Levels

| Level | Score | UI Treatment | Examples |
|-------|-------|--------------|----------|
| **CRITICAL** | 0.9-1.0 | Red highlight, always visible, notification | T1 person needs response, explicit deadline |
| **ACTIONABLE** | 0.6-0.9 | Normal Runway visibility | Reply needed, task to complete |
| **LOG** | 0.3-0.6 | Collapsed into "Log" group | Receipts, confirmations, FYI |
| **NOISE** | 0.0-0.3 | Auto-archived, not shown | Spam, marketing, unsubscribe |

---

## Classification Pipeline

```
┌─────────────────┐
│  Raw Email      │
│  (from API)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Stage 1:       │
│  Fast Filters   │──── NOISE → Archive
│  (Rules-based)  │
└────────┬────────┘
         │ Pass
         ▼
┌─────────────────┐
│  Stage 2:       │
│  Entity Lookup  │──── Update Person.last_interaction
│                 │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Stage 3:       │
│  Signal Scoring │──── Compute base score
│  (Weighted)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Stage 4:       │
│  LLM Refinement │──── Adjust score, extract metadata
│  (Optional)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Classified     │
│  Interaction    │
└─────────────────┘
```

---

## Stage 1: Fast Filters (Rules-Based)

Immediate classification without LLM. Runs on every email.

### Auto-NOISE Rules

```python
NOISE_PATTERNS = {
    # Marketing/Promotional
    "sender_patterns": [
        r".*@.*\.marketing\..*",
        r"noreply@.*",
        r"no-reply@.*",
        r".*@email\..*\.com",  # email.company.com patterns
        r".*@news\..*",
        r".*@promo\..*",
    ],
    
    # Subject patterns
    "subject_patterns": [
        r"^unsubscribe",
        r"^\[?spam\]?",
        r"your weekly digest",
        r"your .* summary",
        r"^sale:",
        r"% off",
        r"limited time",
        r"act now",
    ],
    
    # Known spam domains
    "spam_domains": [
        "mailchimp.com",
        "sendgrid.net",
        "constantcontact.com",
        "hubspot.com",
        # Add as discovered
    ],
    
    # Unsubscribe presence (strong spam signal)
    "body_signals": [
        "unsubscribe",
        "opt-out",
        "email preferences",
        "manage subscriptions",
    ]
}

def fast_filter_noise(email: dict) -> bool:
    """Return True if email should be classified as NOISE."""
    
    sender = email["from"]["address"].lower()
    subject = email["subject"].lower()
    
    # Check sender patterns
    for pattern in NOISE_PATTERNS["sender_patterns"]:
        if re.match(pattern, sender):
            return True
    
    # Check spam domains
    domain = sender.split("@")[-1]
    if domain in NOISE_PATTERNS["spam_domains"]:
        return True
    
    # Check subject patterns
    for pattern in NOISE_PATTERNS["subject_patterns"]:
        if re.search(pattern, subject, re.IGNORECASE):
            return True
    
    # Check for unsubscribe (only in body, not just footer)
    body = email.get("body", "").lower()
    unsubscribe_count = sum(1 for s in NOISE_PATTERNS["body_signals"] if s in body)
    if unsubscribe_count >= 2:  # Multiple signals = likely marketing
        return True
    
    return False
```

### Auto-LOG Rules

```python
LOG_PATTERNS = {
    # Transactional emails
    "subject_patterns": [
        r"^(re:\s*)?order confirmation",
        r"^(re:\s*)?shipping confirmation",
        r"^(re:\s*)?your receipt",
        r"^(re:\s*)?payment received",
        r"^(re:\s*)?reservation confirmed",
        r"^calendar:.*accepted",
        r"^calendar:.*declined",
        r"^automatic reply:",
        r"^out of office:",
    ],
    
    # Automated senders (but not spam)
    "sender_patterns": [
        r".*@calendar\.google\.com",
        r".*@amazonses\.com",
        r".*@github\.com",
        r".*@notifications\..*",
    ]
}

def fast_filter_log(email: dict) -> bool:
    """Return True if email should be classified as LOG."""
    
    subject = email["subject"].lower()
    sender = email["from"]["address"].lower()
    
    for pattern in LOG_PATTERNS["subject_patterns"]:
        if re.search(pattern, subject, re.IGNORECASE):
            return True
    
    for pattern in LOG_PATTERNS["sender_patterns"]:
        if re.match(pattern, sender):
            return True
    
    return False
```

---

## Stage 2: Entity Lookup

After fast filters, resolve the sender to a Person entity.

```python
def lookup_entity(email: dict, context_id: str) -> tuple[Person, bool]:
    """
    Returns (person, is_new) tuple.
    Creates provisional Person if not found.
    """
    sender_address = email["from"]["address"].lower()
    sender_name = email["from"].get("name", "")
    
    # Look up in email_addresses table
    person = get_person_by_email(sender_address)
    
    if person:
        # Update interaction stats
        person.relationship.last_interaction = datetime.now()
        person.relationship.total_interactions += 1
        
        # Update email-specific stats
        email_record = person.get_email(sender_address)
        email_record.interaction_count += 1
        
        save_person(person)
        return (person, False)
    
    # Create provisional person
    person = Person(
        id=uuid4(),
        display_name=sender_name or sender_address,
        emails=[EmailAddress(
            address=sender_address,
            context_id=context_id,
            is_primary=True,
            discovered_at=datetime.now(),
            interaction_count=1
        )],
        tier="T4",  # Default to lowest tier
        tags=["provisional"],
        contexts=[context_id]
    )
    
    save_person(person)
    return (person, True)
```

---

## Stage 3: Signal Scoring (Weighted)

Compute a base signal score from 0.0 to 1.0.

```python
SIGNAL_WEIGHTS = {
    # Sender factors
    "sender_tier": {
        "T1": 0.40,  # Critical people get huge boost
        "T2": 0.25,
        "T3": 0.10,
        "T4": 0.00,
    },
    
    # Content factors
    "has_question": 0.15,          # Contains "?" directed at recipient
    "has_deadline": 0.20,          # Mentions date/deadline
    "has_urgency_words": 0.15,     # "urgent", "ASAP", "EOD"
    "has_action_request": 0.15,    # "please", "can you", "would you"
    "is_reply_to_me": 0.10,        # They're replying to my email
    "has_attachment": 0.05,        # Often needs review
    
    # Negative factors
    "is_bulk_recipient": -0.20,    # Sent to many people
    "is_forwarded": -0.10,         # FW: often FYI
    "is_newsletter": -0.30,        # Detected newsletter format
    
    # Project factors
    "matches_active_project": 0.15,  # Matches a tracked project
}

URGENCY_WORDS = [
    "urgent", "asap", "immediately", "critical", "deadline",
    "eod", "end of day", "cob", "time sensitive", "priority"
]

ACTION_WORDS = [
    "please", "can you", "could you", "would you", "need you to",
    "your thoughts", "your feedback", "let me know", "respond",
    "reply", "confirm", "approve", "review", "sign"
]

def compute_signal_score(email: dict, person: Person, context_id: str) -> dict:
    """Compute signal score and return scoring details."""
    
    score = 0.5  # Base score
    reasons = []
    
    subject = email["subject"].lower()
    body = email.get("body", "").lower()
    text = f"{subject} {body}"
    
    # Sender tier
    tier_boost = SIGNAL_WEIGHTS["sender_tier"].get(person.tier, 0)
    if tier_boost > 0:
        score += tier_boost
        reasons.append(f"{person.tier} sender")
    
    # Question detection
    if "?" in text and any(w in text for w in ["you", "your"]):
        score += SIGNAL_WEIGHTS["has_question"]
        reasons.append("question directed at you")
    
    # Deadline detection
    deadline_patterns = [
        r"by (monday|tuesday|wednesday|thursday|friday|tomorrow|end of)",
        r"due (date|by)",
        r"deadline",
        r"\d{1,2}/\d{1,2}",  # Date pattern
    ]
    if any(re.search(p, text) for p in deadline_patterns):
        score += SIGNAL_WEIGHTS["has_deadline"]
        reasons.append("deadline mentioned")
    
    # Urgency words
    if any(word in text for word in URGENCY_WORDS):
        score += SIGNAL_WEIGHTS["has_urgency_words"]
        reasons.append("urgency language")
    
    # Action request
    if any(word in text for word in ACTION_WORDS):
        score += SIGNAL_WEIGHTS["has_action_request"]
        reasons.append("action requested")
    
    # Reply to my email
    if email.get("in_reply_to") and is_my_email(email.get("in_reply_to"), context_id):
        score += SIGNAL_WEIGHTS["is_reply_to_me"]
        reasons.append("reply to your email")
    
    # Attachment
    if email.get("attachments"):
        score += SIGNAL_WEIGHTS["has_attachment"]
        reasons.append("has attachment")
    
    # Bulk recipient (negative)
    recipients = email.get("to", []) + email.get("cc", [])
    if len(recipients) > 5:
        score += SIGNAL_WEIGHTS["is_bulk_recipient"]
        reasons.append("bulk recipient")
    
    # Forwarded (negative)
    if subject.startswith("fw:") or subject.startswith("fwd:"):
        score += SIGNAL_WEIGHTS["is_forwarded"]
        reasons.append("forwarded")
    
    # Project match
    matching_projects = find_matching_projects(email, person)
    if matching_projects:
        score += SIGNAL_WEIGHTS["matches_active_project"]
        reasons.append(f"matches project: {matching_projects[0].name}")
    
    # Clamp to 0-1
    score = max(0.0, min(1.0, score))
    
    # Determine level
    if score >= 0.9:
        level = "critical"
    elif score >= 0.6:
        level = "actionable"
    elif score >= 0.3:
        level = "log"
    else:
        level = "noise"
    
    return {
        "level": level,
        "score": round(score, 3),
        "reasons": reasons,
        "project_ids": [p.id for p in matching_projects]
    }
```

---

## Stage 4: LLM Refinement (Optional)

For borderline cases or new senders, use LLM to refine classification.

```python
LLM_CLASSIFICATION_PROMPT = """
You are classifying an email for a busy executive's attention management system.

Email Details:
- From: {sender_name} <{sender_email}>
- Subject: {subject}
- Preview: {preview}
- Context: {context_name} ({context_description})
- Sender History: {sender_history}

Current Classification:
- Level: {current_level}
- Score: {current_score}
- Reasons: {current_reasons}

Your task:
1. Confirm or adjust the signal level (critical/actionable/log/noise)
2. Identify if this needs a response and by when
3. Suggest relationship type if sender is new

Response format (JSON):
{{
  "level": "actionable",
  "score_adjustment": 0.1,
  "adjustment_reason": "Sender appears to be a vendor following up on proposal",
  "response_needed": true,
  "response_urgency": "this_week",
  "inferred_relationship": "vendor",
  "suggested_tier": "T3",
  "project_suggestion": null
}}
"""

async def llm_refine_classification(
    email: dict,
    person: Person,
    context: Context,
    current_signal: dict
) -> dict:
    """Use LLM to refine classification for borderline cases."""
    
    # Only use LLM for:
    # - New/provisional senders
    # - Borderline scores (0.55-0.65 or 0.85-0.95)
    # - Long emails that might have buried action items
    
    if not should_use_llm(person, current_signal, email):
        return current_signal
    
    prompt = LLM_CLASSIFICATION_PROMPT.format(
        sender_name=person.display_name,
        sender_email=email["from"]["address"],
        subject=email["subject"],
        preview=email.get("preview", "")[:500],
        context_name=context.name,
        context_description=get_context_description(context.id),
        sender_history=format_sender_history(person),
        current_level=current_signal["level"],
        current_score=current_signal["score"],
        current_reasons=", ".join(current_signal["reasons"])
    )
    
    response = await call_llm(prompt)
    refinement = json.loads(response)
    
    # Apply adjustments
    new_score = current_signal["score"] + refinement.get("score_adjustment", 0)
    new_score = max(0.0, min(1.0, new_score))
    
    # Update person if suggestions provided
    if refinement.get("suggested_tier") and "provisional" in person.tags:
        person.tier = refinement["suggested_tier"]
        if refinement.get("inferred_relationship"):
            person.tags.append(refinement["inferred_relationship"])
        person.tags.remove("provisional")
        save_person(person)
    
    return {
        "level": refinement.get("level", current_signal["level"]),
        "score": new_score,
        "reasons": current_signal["reasons"] + [refinement.get("adjustment_reason", "")],
        "response_needed": refinement.get("response_needed", False),
        "response_urgency": refinement.get("response_urgency"),
        "project_ids": current_signal.get("project_ids", [])
    }
```

---

## Project Matching

```python
def find_matching_projects(email: dict, person: Person) -> list[Project]:
    """Find projects that this email might belong to."""
    
    matches = []
    subject = email["subject"].lower()
    body = email.get("body", "").lower()
    sender = email["from"]["address"].lower()
    sender_domain = sender.split("@")[-1]
    
    for project in get_active_projects():
        score = 0
        
        # Keyword matching
        for keyword in project.rules.get("keywords", []):
            if keyword.lower() in subject:
                score += 2  # Subject match worth more
            elif keyword.lower() in body:
                score += 1
        
        # Person matching
        if person.id in project.rules.get("people_ids", []):
            score += 3
        
        # Domain matching
        if sender_domain in project.rules.get("sender_domains", []):
            score += 2
        
        # Subject pattern matching
        for pattern in project.rules.get("subject_patterns", []):
            if re.search(pattern, subject, re.IGNORECASE):
                score += 2
        
        if score >= 2:  # Threshold for match
            matches.append((project, score))
    
    # Return sorted by score
    matches.sort(key=lambda x: x[1], reverse=True)
    return [m[0] for m in matches]
```

---

## Response Detection

Determine if an email needs a response and estimate urgency.

```python
RESPONSE_INDICATORS = {
    "explicit_request": [
        r"please (reply|respond|confirm|let me know)",
        r"can you (send|provide|confirm|let me know)",
        r"(need|waiting for) your (response|reply|feedback|input)",
        r"get back to me",
        r"your thoughts\??",
    ],
    
    "question_to_me": [
        r"(do|does|can|could|would|will|are|is) you",
        r"what do you think",
        r"how (do|would|should) you",
    ],
    
    "deadline_indicators": [
        r"by (end of day|eod|cob|tomorrow|monday|tuesday|wednesday|thursday|friday)",
        r"deadline[:\s]",
        r"due[:\s]",
        r"need.*(by|before)",
    ]
}

def detect_response_needed(email: dict, signal: dict) -> dict:
    """Detect if response is needed and estimate urgency."""
    
    subject = email["subject"].lower()
    body = email.get("body", "").lower()
    text = f"{subject} {body}"
    
    response_signals = 0
    urgency = "none"
    
    # Check explicit requests
    for pattern in RESPONSE_INDICATORS["explicit_request"]:
        if re.search(pattern, text):
            response_signals += 2
    
    # Check questions directed at recipient
    for pattern in RESPONSE_INDICATORS["question_to_me"]:
        if re.search(pattern, text):
            response_signals += 1
    
    # Check deadlines
    for pattern in RESPONSE_INDICATORS["deadline_indicators"]:
        if re.search(pattern, text):
            response_signals += 1
            urgency = "soon"  # Has deadline = soon
    
    # T1 sender always warrants response consideration
    if signal.get("sender_tier") == "T1":
        response_signals += 1
    
    response_needed = response_signals >= 2
    
    # Determine urgency
    if response_needed:
        if "urgent" in text or "asap" in text:
            urgency = "immediate"
        elif urgency != "soon":
            urgency = "this_week"
    
    return {
        "response_needed": response_needed,
        "response_urgency": urgency,
        "response_signals": response_signals
    }
```

---

## Full Classification Flow

```python
async def classify_interaction(email: dict, context_id: str) -> Interaction:
    """Full classification pipeline for an incoming email."""
    
    # Stage 1: Fast filters
    if fast_filter_noise(email):
        return create_interaction(email, context_id, signal={
            "level": "noise",
            "score": 0.1,
            "reasons": ["auto-filtered as noise"]
        })
    
    is_log = fast_filter_log(email)
    
    # Stage 2: Entity lookup
    person, is_new_person = lookup_entity(email, context_id)
    
    # Stage 3: Signal scoring
    if is_log:
        signal = {
            "level": "log",
            "score": 0.4,
            "reasons": ["auto-classified as log"]
        }
    else:
        signal = compute_signal_score(email, person, context_id)
    
    # Stage 4: LLM refinement (if needed)
    context = get_context(context_id)
    signal = await llm_refine_classification(email, person, context, signal)
    
    # Detect response needs
    response_info = detect_response_needed(email, signal)
    
    # Create interaction
    interaction = Interaction(
        id=uuid4(),
        type="email",
        context_id=context_id,
        external_id=email["id"],
        external_url=email.get("webLink"),
        subject=email["subject"],
        preview=email.get("preview", "")[:200],
        from_person_id=person.id,
        from_email=email["from"]["address"],
        timestamp=email["received"],
        signal=signal,
        state={
            "is_read": email.get("isRead", False),
            "response_status": "pending" if response_info["response_needed"] else "none_needed",
            "response_urgency": response_info["response_urgency"]
        },
        project_ids=signal.get("project_ids", [])
    )
    
    save_interaction(interaction)
    return interaction
```

---

## Changelog

- 2026-01-28: Initial signal classification specification
