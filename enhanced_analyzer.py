#!/usr/bin/env python3
"""
Enhanced Email Analyzer - Improved task extraction and classification
Builds on analyzer.py with better pattern recognition and context awareness
"""

import json
import re
import httpx
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from analyzer import call_llm, extract_body_text, fallback_analyze_content

class EnhancedAnalyzer:
    """Enhanced email analysis with improved task extraction"""
    
    def __init__(self):
        self.action_patterns = self._load_action_patterns()
        self.urgency_indicators = self._load_urgency_indicators()
        self.deadline_patterns = self._load_deadline_patterns()
    
    def _load_action_patterns(self) -> Dict[str, List[str]]:
        """Load patterns that indicate actionable items"""
        return {
            "high_priority_actions": [
                r"please (?:review|approve|sign|confirm|respond)",
                r"need(?:s)?(?:ed)? (?:your|you to|immediate)",
                r"(?:asap|urgent|critical|important).*(?:action|response|decision)",
                r"by (?:eod|end of day|friday|tomorrow)",
                r"deadline.*(?:approaching|passed|today|tomorrow)",
                r"waiting (?:on|for) you",
                r"requires? (?:your|immediate) (?:attention|approval|input)"
            ],
            "medium_priority_actions": [
                r"can you (?:please )?(?:review|check|look|help)",
                r"would appreciate (?:your|if you)",
                r"please (?:let me know|advise|provide|send)",
                r"when you have (?:a|the) (?:chance|moment|time)",
                r"could you (?:please )?(?:help|assist|provide)"
            ],
            "scheduling_actions": [
                r"(?:schedule|set up|arrange).*(?:meeting|call|discussion)",
                r"(?:available|free).*(?:for|to).*(?:meet|call|discuss)",
                r"calendar (?:invite|invitation|meeting)",
                r"(?:time|slot).*(?:work|available)",
                r"reschedule|postpone|move.*(?:meeting|call)"
            ],
            "decision_actions": [
                r"(?:decide|choose|select).*(?:between|from|which)",
                r"(?:approve|reject|accept|decline).*(?:proposal|request)",
                r"(?:go|no)-?go (?:decision|call)",
                r"sign-?off (?:on|required)",
                r"final (?:decision|approval)"
            ],
            "delegation_actions": [
                r"(?:delegate|assign).*(?:to|this)",
                r"(?:hand|pass).*(?:off|over)",
                r"(?:transfer|move).*(?:to|ownership)",
                r"(?:take|own).*(?:responsibility|ownership)"
            ]
        }
    
    def _load_urgency_indicators(self) -> Dict[str, List[str]]:
        """Load patterns that indicate urgency levels"""
        return {
            "critical": [
                r"critical|emergency|urgent|asap|immediate",
                r"production (?:down|issue|outage)",
                r"escalat(?:e|ion)",
                r"red (?:alert|flag)",
                r"(?:security|data) breach"
            ],
            "high": [
                r"high priority|important",
                r"today|eod|end of day",
                r"deadline.*(?:today|tomorrow|this week)",
                r"(?:legal|compliance).*(?:issue|concern)",
                r"customer (?:complaint|issue|escalation)"
            ],
            "medium": [
                r"medium priority|moderate",
                r"this week|by friday",
                r"when (?:possible|convenient)",
                r"routine (?:review|update)"
            ],
            "low": [
                r"low priority|fyi|for (?:your )?information",
                r"when you (?:have time|get a chance)",
                r"no (?:rush|hurry)",
                r"(?:monthly|quarterly) (?:report|update)"
            ]
        }
    
    def _load_deadline_patterns(self) -> List[Tuple[str, str]]:
        """Load regex patterns for deadline extraction"""
        return [
            (r"by (\w+day,? \w+ \d+)", "by_date"),
            (r"by (\d{1,2}/\d{1,2}/\d{4})", "date_format"),
            (r"by (\d{1,2}-\d{1,2}-\d{4})", "date_format"),
            (r"deadline:?\s*(\w+day,? \w+ \d+)", "deadline_date"),
            (r"due (?:on|by):?\s*(\w+day,? \w+ \d+)", "due_date"),
            (r"eod|end of day", "eod_today"),
            (r"(?:by )?tomorrow", "tomorrow"),
            (r"this (\w+day)", "this_weekday"),
            (r"next (\w+day)", "next_weekday"),
            (r"by (\d{1,2})(?:pm|am)", "time_today")
        ]
    
    async def enhanced_analyze_content(self, email_content: Dict) -> Dict:
        """
        Enhanced analysis with improved pattern recognition
        Returns detailed analysis including complexity scoring and action types
        """
        subject = email_content.get("subject", "")
        body = extract_body_text(email_content)
        from_name = email_content.get("from", {}).get("name", "")
        from_address = email_content.get("from", {}).get("address", "")
        
        # Standard LLM analysis first
        base_analysis = await self._get_base_analysis(email_content)
        
        # Enhanced pattern analysis
        action_analysis = self._analyze_action_patterns(subject, body)
        urgency_analysis = self._analyze_urgency(subject, body)
        deadline_analysis = self._extract_deadlines(subject, body)
        complexity_analysis = self._analyze_complexity(subject, body)
        stakeholder_analysis = self._extract_stakeholders(subject, body)
        
        # Combine analyses
        enhanced_result = {
            **base_analysis,
            "action_types": action_analysis["types"],
            "action_confidence": action_analysis["confidence"],
            "urgency_score": urgency_analysis["score"],
            "urgency_reasons": urgency_analysis["reasons"],
            "deadlines": deadline_analysis,
            "complexity": complexity_analysis,
            "stakeholders": stakeholder_analysis,
            "estimated_time": self._estimate_time_requirement(complexity_analysis, action_analysis),
            "follow_up_needed": self._needs_follow_up(subject, body),
            "blocking_others": self._check_if_blocking(subject, body)
        }
        
        # Override classification if patterns suggest different priority
        enhanced_result["classification"] = self._refine_classification(
            base_analysis.get("classification", "fyi"),
            action_analysis,
            urgency_analysis
        )
        
        return enhanced_result
    
    async def _get_base_analysis(self, email_content: Dict) -> Dict:
        """Get base analysis from LLM or fallback"""
        subject = email_content.get("subject", "")
        body = extract_body_text(email_content)
        from_name = email_content.get("from", {}).get("name", "")
        from_address = email_content.get("from", {}).get("address", "")
        
        prompt = f"""Analyze this email and extract key information:

Subject: {subject}
From: {from_name} <{from_address}>
Body: {body[:1500]}

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
- Extract names mentioned in body (not just sender)
- Be specific about action needed

Return only valid JSON."""

        try:
            result = await call_llm([{"role": "user", "content": prompt}], max_tokens=800, timeout=30)
            
            if result:
                # Clean and parse JSON
                clean_result = result.strip()
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', clean_result, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group(0))
            
        except Exception as e:
            print(f"LLM analysis failed: {e}")
        
        # Fallback to rule-based analysis
        return fallback_analyze_content(email_content)
    
    def _analyze_action_patterns(self, subject: str, body: str) -> Dict:
        """Analyze text for action patterns"""
        combined_text = f"{subject} {body}".lower()
        action_types = []
        max_confidence = 0
        
        for action_category, patterns in self.action_patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, combined_text, re.IGNORECASE)
                match_count = len(list(matches))
                
                if match_count > 0:
                    confidence = min(match_count * 0.3 + 0.4, 1.0)
                    action_types.append({
                        "type": action_category,
                        "confidence": confidence,
                        "matches": match_count
                    })
                    max_confidence = max(max_confidence, confidence)
        
        return {
            "types": action_types,
            "confidence": max_confidence
        }
    
    def _analyze_urgency(self, subject: str, body: str) -> Dict:
        """Analyze urgency indicators"""
        combined_text = f"{subject} {body}".lower()
        urgency_scores = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        reasons = []
        
        for urgency_level, patterns in self.urgency_indicators.items():
            for pattern in patterns:
                matches = list(re.finditer(pattern, combined_text, re.IGNORECASE))
                if matches:
                    urgency_scores[urgency_level] += len(matches)
                    reasons.append({
                        "level": urgency_level,
                        "pattern": pattern,
                        "matches": len(matches)
                    })
        
        # Calculate overall urgency score (0-1)
        weighted_score = (
            urgency_scores["critical"] * 1.0 +
            urgency_scores["high"] * 0.7 +
            urgency_scores["medium"] * 0.4 +
            urgency_scores["low"] * 0.1
        ) / max(sum(urgency_scores.values()), 1)
        
        return {
            "score": min(weighted_score, 1.0),
            "reasons": reasons,
            "breakdown": urgency_scores
        }
    
    def _extract_deadlines(self, subject: str, body: str) -> List[Dict]:
        """Extract deadline information"""
        combined_text = f"{subject} {body}"
        deadlines = []
        
        for pattern, deadline_type in self.deadline_patterns:
            matches = re.finditer(pattern, combined_text, re.IGNORECASE)
            for match in matches:
                deadline_text = match.group(0)
                extracted_date = self._parse_deadline_to_date(deadline_text, deadline_type)
                
                deadlines.append({
                    "text": deadline_text,
                    "type": deadline_type,
                    "date": extracted_date,
                    "days_from_now": self._days_from_now(extracted_date) if extracted_date else None
                })
        
        return deadlines
    
    def _parse_deadline_to_date(self, text: str, deadline_type: str) -> Optional[str]:
        """Parse deadline text to ISO date format"""
        today = datetime.now().date()
        
        if deadline_type == "eod_today":
            return today.isoformat()
        elif deadline_type == "tomorrow":
            return (today + timedelta(days=1)).isoformat()
        elif deadline_type == "this_weekday":
            # Extract weekday and find next occurrence
            weekday_match = re.search(r'this (\w+day)', text, re.IGNORECASE)
            if weekday_match:
                return self._find_this_weekday(weekday_match.group(1))
        elif deadline_type == "next_weekday":
            # Extract weekday and find next week occurrence
            weekday_match = re.search(r'next (\w+day)', text, re.IGNORECASE)
            if weekday_match:
                return self._find_next_weekday(weekday_match.group(1))
        
        # TODO: Add more sophisticated date parsing
        return None
    
    def _find_this_weekday(self, weekday_name: str) -> str:
        """Find the date for 'this Monday', 'this Friday', etc."""
        weekdays = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6
        }
        
        target_weekday = weekdays.get(weekday_name.lower())
        if target_weekday is None:
            return None
        
        today = datetime.now().date()
        days_ahead = target_weekday - today.weekday()
        
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        
        return (today + timedelta(days=days_ahead)).isoformat()
    
    def _find_next_weekday(self, weekday_name: str) -> str:
        """Find the date for 'next Monday', 'next Friday', etc."""
        this_week_date = self._find_this_weekday(weekday_name)
        if this_week_date:
            this_date = datetime.fromisoformat(this_week_date).date()
            return (this_date + timedelta(weeks=1)).isoformat()
        return None
    
    def _days_from_now(self, date_str: str) -> int:
        """Calculate days from now to given date"""
        try:
            target_date = datetime.fromisoformat(date_str).date()
            today = datetime.now().date()
            return (target_date - today).days
        except:
            return None
    
    def _analyze_complexity(self, subject: str, body: str) -> Dict:
        """Analyze task complexity"""
        combined_text = f"{subject} {body}".lower()
        
        complexity_indicators = {
            "high": [
                r"research|analysis|investigation",
                r"multiple (?:stakeholders|teams|departments)",
                r"(?:strategic|long.?term|comprehensive) (?:plan|review)",
                r"(?:budget|financial|legal) (?:review|approval)",
                r"cross.?(?:functional|departmental)",
                r"(?:enterprise|company).?wide"
            ],
            "medium": [
                r"coordination|planning|scheduling",
                r"(?:team|group) (?:meeting|discussion)",
                r"review (?:and|&) (?:approve|comment)",
                r"update (?:status|progress)",
                r"preparation|preparation"
            ],
            "low": [
                r"quick (?:question|check|update)",
                r"(?:simple|straightforward|easy)",
                r"(?:yes|no) (?:response|answer)",
                r"confirmation|acknowledge",
                r"fyi|for (?:your )?information"
            ]
        }
        
        scores = {"high": 0, "medium": 0, "low": 0}
        indicators_found = []
        
        for complexity, patterns in complexity_indicators.items():
            for pattern in patterns:
                matches = list(re.finditer(pattern, combined_text, re.IGNORECASE))
                if matches:
                    scores[complexity] += len(matches)
                    indicators_found.append({
                        "complexity": complexity,
                        "pattern": pattern,
                        "count": len(matches)
                    })
        
        # Determine overall complexity
        if scores["high"] > 0:
            overall = "high"
        elif scores["medium"] > 0:
            overall = "medium"
        else:
            overall = "low"
        
        return {
            "overall": overall,
            "scores": scores,
            "indicators": indicators_found
        }
    
    def _extract_stakeholders(self, subject: str, body: str) -> List[Dict]:
        """Extract stakeholders and their roles"""
        # Look for name patterns in the body
        name_patterns = [
            r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b",  # First Last
            r"\b([A-Z][a-z]+\.?)\s+(?:from|at|with)\b",  # Name context
            r"(?:cc|to|from):\s*([A-Z][a-z]+ [A-Z][a-z]+)",  # Email headers
        ]
        
        stakeholders = []
        seen_names = set()
        
        for pattern in name_patterns:
            matches = re.finditer(pattern, body, re.MULTILINE)
            for match in matches:
                name = match.group(1).strip()
                if name not in seen_names and len(name.split()) == 2:
                    # Simple role detection based on context
                    role = self._infer_role(name, body)
                    stakeholders.append({
                        "name": name,
                        "role": role,
                        "mentioned_in_context": match.group(0)
                    })
                    seen_names.add(name)
        
        return stakeholders[:10]  # Limit to avoid noise
    
    def _infer_role(self, name: str, body: str) -> str:
        """Infer stakeholder role from context"""
        name_context = body.lower()
        
        role_indicators = {
            "manager": ["manager", "director", "vp", "head of"],
            "developer": ["developer", "engineer", "programmer"],
            "designer": ["designer", "ux", "ui"],
            "analyst": ["analyst", "research"],
            "client": ["client", "customer", "customer"],
            "vendor": ["vendor", "supplier", "contractor"]
        }
        
        for role, indicators in role_indicators.items():
            if any(indicator in name_context for indicator in indicators):
                return role
        
        return "stakeholder"
    
    def _estimate_time_requirement(self, complexity: Dict, action_analysis: Dict) -> str:
        """Estimate time requirement for task"""
        complexity_level = complexity.get("overall", "low")
        action_types = action_analysis.get("types", [])
        
        # Base time estimates
        base_times = {
            "low": "15-30 minutes",
            "medium": "1-2 hours", 
            "high": "4+ hours"
        }
        
        # Adjust based on action types
        if any(at["type"] == "high_priority_actions" for at in action_types):
            if complexity_level == "low":
                return "30-60 minutes"
            elif complexity_level == "medium":
                return "2-4 hours"
            else:
                return "1+ days"
        
        return base_times.get(complexity_level, "Unknown")
    
    def _needs_follow_up(self, subject: str, body: str) -> bool:
        """Check if task likely needs follow-up"""
        combined_text = f"{subject} {body}".lower()
        
        follow_up_indicators = [
            r"follow.?up",
            r"check (?:in|back)",
            r"update.*(?:status|progress)",
            r"pending (?:response|approval)",
            r"waiting (?:for|on)"
        ]
        
        return any(re.search(pattern, combined_text) for pattern in follow_up_indicators)
    
    def _check_if_blocking(self, subject: str, body: str) -> bool:
        """Check if this task is blocking others"""
        combined_text = f"{subject} {body}".lower()
        
        blocking_indicators = [
            r"(?:team|others|we) (?:waiting|blocked)",
            r"(?:can.?t|cannot) (?:proceed|continue|start) (?:without|until)",
            r"(?:blocking|prevents?) (?:us|team|progress)",
            r"(?:urgent|critical).*(?:path|blocker)",
            r"(?:everyone|team) (?:waiting|needs)"
        ]
        
        return any(re.search(pattern, combined_text) for pattern in blocking_indicators)
    
    def _refine_classification(self, base_classification: str, action_analysis: Dict, urgency_analysis: Dict) -> str:
        """Refine classification based on pattern analysis"""
        action_confidence = action_analysis.get("confidence", 0)
        urgency_score = urgency_analysis.get("score", 0)
        
        # Override FYI if strong action signals
        if base_classification == "fyi" and action_confidence > 0.6:
            return "action_item"
        
        # Elevate to needs_response if high urgency
        if base_classification == "action_item" and urgency_score > 0.7:
            return "needs_response"
        
        return base_classification