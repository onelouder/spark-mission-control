#!/usr/bin/env python3
"""
Enhanced Email Processing Pipeline
Integrates enhanced analyzer for better task extraction and classification
"""

import json
import os
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# Import base pipeline functionality
from pipeline import (
    load_config, load_processed_emails, save_processed_emails,
    fetch_emails_from_decapoda, fetch_email_content, stage1_fast_filter,
    stage2_llm_triage, fetch_emails_from_gmail, DATA_DIR
)

# Import enhanced analyzer
from enhanced_analyzer import EnhancedAnalyzer

class EnhancedPipeline:
    """Enhanced email processing pipeline with improved intelligence"""
    
    def __init__(self):
        self.analyzer = EnhancedAnalyzer()
        self.smart_filter = SmartFilter()
        self.task_extractor = TaskExtractor()
        
    async def process_emails_with_intelligence(self, max_emails: int = 100) -> Dict:
        """
        Enhanced email processing with intelligent task extraction
        """
        print("🚀 Starting enhanced email processing...")
        
        # Load dependencies
        contacts = self._load_contacts()
        config = load_config()
        processed_data = load_processed_emails()
        
        # Fetch emails from all sources
        emails = await self._fetch_all_emails(max_emails, config)
        print(f"📧 Retrieved {len(emails)} emails total")
        
        if not emails:
            return {"new_processed": 0, "filtered": 0, "passed": 0, "tasks_created": 0, "errors": []}
        
        # Process with enhanced pipeline
        results = await self._process_with_enhanced_analysis(emails, contacts, config, processed_data)
        
        # Extract tasks from analyzed emails
        task_results = await self._extract_and_create_tasks(results["passed_emails"])
        
        # Update processed data
        processed_data.update({
            "last_sync": datetime.now(timezone.utc).isoformat(),
            "emails": results["emails"],
            "filtered": results["filtered"],
            "enhancement_stats": results["enhancement_stats"]
        })
        
        save_processed_emails(processed_data)
        
        # Generate summary
        summary = {
            **results["summary"],
            "tasks_created": task_results["tasks_created"],
            "task_errors": task_results["errors"],
            "enhancement_stats": results["enhancement_stats"]
        }
        
        self._print_enhanced_summary(summary)
        return summary
    
    def _load_contacts(self) -> Dict:
        """Load contacts with fallback"""
        try:
            contacts_file = os.path.join(DATA_DIR, "contacts.json")
            with open(contacts_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {"top20": [], "top100": [], "partners": []}
    
    async def _fetch_all_emails(self, max_emails: int, config: Dict) -> List[Dict]:
        """Fetch emails from all configured sources"""
        all_emails = []
        
        # Office 365 via Decapoda
        if config.get("enable_office365", True):
            print(f"📥 Fetching Office365 emails...")
            o365_emails = await fetch_emails_from_decapoda(limit=max_emails)
            all_emails.extend(o365_emails)
        
        # Gmail
        if config.get("enable_gmail", False):
            print(f"📥 Fetching Gmail emails...")
            gmail_emails = await fetch_emails_from_gmail(limit=max_emails)
            all_emails.extend(gmail_emails)
        
        return all_emails
    
    async def _process_with_enhanced_analysis(self, emails: List[Dict], contacts: Dict, config: Dict, processed_data: Dict) -> Dict:
        """Process emails with enhanced analysis"""
        
        current_emails = processed_data.get("emails", {})
        current_filtered = processed_data.get("filtered", {})
        
        new_processed = 0
        newly_filtered = 0
        newly_passed = 0
        passed_emails = []
        errors = []
        enhancement_stats = {
            "enhanced_analysis_count": 0,
            "task_extraction_count": 0,
            "complexity_analysis_count": 0,
            "stakeholder_analysis_count": 0
        }
        
        for email in emails:
            try:
                email_id = email["id"]
                
                # Skip if already processed
                if email_id in current_emails or email_id in current_filtered:
                    continue
                
                # Process with enhanced pipeline
                was_new, result = await self._process_single_email_enhanced(
                    email, contacts, config
                )
                
                if was_new:
                    new_processed += 1
                    
                    if result["final_decision"] == "filtered":
                        current_filtered[email_id] = result
                        newly_filtered += 1
                    else:
                        current_emails[email_id] = result
                        newly_passed += 1
                        passed_emails.append(result)
                        
                        # Update enhancement stats
                        if "enhanced_analysis" in result:
                            enhancement_stats["enhanced_analysis_count"] += 1
                        if result.get("enhanced_analysis", {}).get("complexity"):
                            enhancement_stats["complexity_analysis_count"] += 1
                        if result.get("enhanced_analysis", {}).get("stakeholders"):
                            enhancement_stats["stakeholder_analysis_count"] += 1
                            
            except Exception as e:
                error_msg = f"Failed to process email {email.get('id', 'unknown')}: {e}"
                print(f"   ❌ {error_msg}")
                errors.append(error_msg)
        
        return {
            "emails": current_emails,
            "filtered": current_filtered,
            "passed_emails": passed_emails,
            "enhancement_stats": enhancement_stats,
            "summary": {
                "new_processed": new_processed,
                "filtered": newly_filtered,
                "passed": newly_passed,
                "total_emails": len(current_emails),
                "total_filtered": len(current_filtered),
                "errors": errors
            }
        }
    
    async def _process_single_email_enhanced(self, email: Dict, contacts: Dict, config: Dict) -> Tuple[bool, Dict]:
        """Process single email with enhanced analysis"""
        
        email_id = email["id"]
        processing_start = datetime.now(timezone.utc)
        
        result = {
            "email_data": email,
            "processed_at": processing_start.isoformat(),
            "pipeline_version": "2.0_enhanced",
            "stages": {}
        }
        
        print(f"📧 Enhanced processing: {email.get('subject', 'No subject')[:50]}...")
        
        # Stage 1: Enhanced Fast Filter
        stage1_pass, stage1_tag, stage1_reason = await self._enhanced_fast_filter(email, contacts, config)
        result["stages"]["stage1"] = {
            "passed": stage1_pass,
            "tag": stage1_tag,
            "reason": stage1_reason
        }
        
        if not stage1_pass:
            result["final_decision"] = "filtered"
            result["filter_reason"] = stage1_reason
            print(f"   ❌ Filtered: {stage1_reason}")
            return True, result
        
        # Stage 2: Enhanced LLM Triage (for unknown senders)
        if stage1_tag == "unknown":
            stage2_pass, stage2_class, stage2_reason = await self._enhanced_llm_triage(email)
            result["stages"]["stage2"] = {
                "passed": stage2_pass,
                "classification": stage2_class,
                "reason": stage2_reason
            }
            
            if not stage2_pass:
                result["final_decision"] = "filtered"
                result["filter_reason"] = stage2_reason
                print(f"   ❌ Filtered by enhanced LLM: {stage2_reason}")
                return True, result
        
        # Email passed filtering - proceed to Stage 3: Enhanced Analysis
        result["final_decision"] = "passed"
        result["contact_tier"] = stage1_tag
        print(f"   ✅ Passed ({stage1_tag})")
        
        # Stage 3: Enhanced Deep Analysis
        print(f"   🔍 Enhanced analysis...")
        enhanced_analysis = await self.analyzer.enhanced_analyze_content(email)
        result["enhanced_analysis"] = enhanced_analysis
        
        # Legacy analysis for compatibility
        result["analysis"] = {
            "classification": enhanced_analysis.get("classification", "fyi"),
            "summary": enhanced_analysis.get("summary", ""),
            "action_needed": enhanced_analysis.get("action_needed"),
            "deadline": enhanced_analysis.get("deadline"),
            "urgency": enhanced_analysis.get("urgency", "low"),
            "people_mentioned": enhanced_analysis.get("people_mentioned", []),
            "meeting_details": enhanced_analysis.get("meeting_details")
        }
        
        print(f"   📊 Enhanced: {enhanced_analysis['classification']} ({enhanced_analysis['urgency']} urgency)")
        if enhanced_analysis.get("complexity"):
            print(f"   🎯 Complexity: {enhanced_analysis['complexity']['overall']}")
        if enhanced_analysis.get("estimated_time"):
            print(f"   ⏱️ Estimated time: {enhanced_analysis['estimated_time']}")
        
        return True, result
    
    async def _enhanced_fast_filter(self, email: Dict, contacts: Dict, config: Dict) -> Tuple[bool, str, str]:
        """Enhanced fast filter with additional intelligence"""
        
        # Use base fast filter first
        base_pass, base_tag, base_reason = stage1_fast_filter(email, contacts, config)
        
        if not base_pass:
            return base_pass, base_tag, base_reason
        
        # Additional smart filtering
        smart_pass, smart_reason = await self.smart_filter.additional_filtering(email, contacts, config)
        
        if not smart_pass:
            return False, "smart_filter", smart_reason
        
        return base_pass, base_tag, base_reason
    
    async def _enhanced_llm_triage(self, email: Dict) -> Tuple[bool, str, str]:
        """Enhanced LLM triage with better prompts"""
        
        subject = email.get("subject", "")
        from_info = email.get("from", {})
        
        if isinstance(from_info, dict):
            from_address = from_info.get("address", "")
            from_name = from_info.get("name", "")
        else:
            from_address = str(from_info)
            from_name = ""
        
        # Enhanced prompt for better classification
        enhanced_prompt = f"""Classify this email from an unknown sender with enhanced context awareness:

Subject: {subject}
From: {from_name} <{from_address}>

Classify into ONE category:
- personal_email: Personal communication from individual (respond)
- action_required: Email requiring response/action (respond)  
- meeting_request: Meeting/scheduling related (respond)
- newsletter: Newsletter/digest/publication (archive)
- sales_outreach: Sales/marketing/promotional (archive)
- automated_notification: System notifications/alerts (archive)

Consider:
- Subject line language patterns
- Sender domain and format
- Professional vs personal tone indicators
- Urgency or action language

Return only the category name."""
        
        try:
            from analyzer import call_llm
            result = await call_llm([{"role": "user", "content": enhanced_prompt}], max_tokens=50, timeout=20)
            
            if result:
                classification = result.strip().lower()
                valid_categories = [
                    "personal_email", "action_required", "meeting_request", 
                    "newsletter", "sales_outreach", "automated_notification"
                ]
                if classification in valid_categories:
                    # Determine if should pass
                    pass_categories = ["personal_email", "action_required", "meeting_request"]
                    should_pass = classification in pass_categories
                    return should_pass, classification, f"Enhanced LLM: {classification}"
        
        except Exception as e:
            print(f"Enhanced LLM triage failed: {e}")
        
        # Fallback to base triage
        return await stage2_llm_triage(email)
    
    async def _extract_and_create_tasks(self, passed_emails: List[Dict]) -> Dict:
        """Extract tasks from analyzed emails"""
        tasks_created = 0
        errors = []
        
        try:
            # Load existing tasks
            tasks_file = os.path.join(DATA_DIR, "tasks.json")
            existing_tasks = []
            if os.path.exists(tasks_file):
                with open(tasks_file, 'r') as f:
                    existing_tasks = json.load(f)
            
            existing_email_ids = {
                task["source_id"] for task in existing_tasks 
                if task.get("source_type") == "email"
            }
            
            new_tasks = []
            
            for email_result in passed_emails:
                try:
                    email_data = email_result["email_data"]
                    email_id = email_data["id"]
                    
                    # Skip if task already exists for this email
                    if email_id in existing_email_ids:
                        continue
                    
                    # Check if email warrants task creation
                    enhanced_analysis = email_result.get("enhanced_analysis", {})
                    task_candidates = await self.task_extractor.extract_tasks_from_email(
                        email_data, enhanced_analysis
                    )
                    
                    for task_candidate in task_candidates:
                        task = await self._create_task_from_candidate(email_data, enhanced_analysis, task_candidate)
                        if task:
                            new_tasks.append(task)
                            tasks_created += 1
                            
                except Exception as e:
                    errors.append(f"Failed to extract task from email {email_data.get('id', 'unknown')}: {e}")
            
            # Save new tasks
            if new_tasks:
                all_tasks = existing_tasks + new_tasks
                with open(tasks_file, 'w') as f:
                    json.dump(all_tasks, f, indent=2)
                
                print(f"✅ Created {tasks_created} new tasks from emails")
            
        except Exception as e:
            errors.append(f"Task extraction failed: {e}")
        
        return {
            "tasks_created": tasks_created,
            "errors": errors
        }
    
    async def _create_task_from_candidate(self, email_data: Dict, enhanced_analysis: Dict, task_candidate: Dict) -> Optional[Dict]:
        """Create task from task candidate"""
        try:
            import uuid
            
            task = {
                "id": str(uuid.uuid4()),
                "title": task_candidate["title"],
                "description": task_candidate["description"], 
                "column": "todo",
                "complexity": task_candidate.get("complexity", "medium"),
                "energy": task_candidate.get("energy", "medium"),
                "source_type": "email",
                "source_id": email_data["id"],
                "source_url": email_data.get("webLink", ""),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "stuck_since": datetime.now(timezone.utc).isoformat(),
                "priority_contact": True,
                "enhanced_extraction": True,
                "estimated_time": enhanced_analysis.get("estimated_time"),
                "deadline": enhanced_analysis.get("deadline"),
                "stakeholders": [s["name"] for s in enhanced_analysis.get("stakeholders", [])],
                "blocking_others": enhanced_analysis.get("blocking_others", False)
            }
            
            return task
            
        except Exception as e:
            print(f"Failed to create task: {e}")
            return None
    
    def _print_enhanced_summary(self, summary: Dict) -> None:
        """Print enhanced summary"""
        print(f"\n✅ Enhanced processing complete:")
        print(f"   📧 New processed: {summary['new_processed']}")
        print(f"   ✅ Passed: {summary['passed']}")
        print(f"   ❌ Filtered: {summary['filtered']}")
        print(f"   🎯 Tasks created: {summary['tasks_created']}")
        print(f"   📊 Total in system: {summary['total_emails']} passed, {summary['total_filtered']} filtered")
        
        enhancement_stats = summary.get("enhancement_stats", {})
        if enhancement_stats:
            print(f"\n🚀 Enhancement Stats:")
            print(f"   🔍 Enhanced analysis: {enhancement_stats['enhanced_analysis_count']}")
            print(f"   🎯 Complexity analysis: {enhancement_stats['complexity_analysis_count']}")
            print(f"   👥 Stakeholder analysis: {enhancement_stats['stakeholder_analysis_count']}")


class SmartFilter:
    """Smart filtering with ML-like pattern recognition"""
    
    async def additional_filtering(self, email: Dict, contacts: Dict, config: Dict) -> Tuple[bool, str]:
        """Apply additional intelligent filtering"""
        
        subject = email.get("subject", "").lower()
        from_info = email.get("from", {})
        from_address = from_info.get("address", "").lower() if isinstance(from_info, dict) else ""
        
        # Pattern-based filtering
        spam_indicators = [
            "congratulations you have won",
            "click here now",
            "limited time offer",
            "act now",
            "free trial",
            "unsubscribe",
            "newsletter",
            "promotional"
        ]
        
        for indicator in spam_indicators:
            if indicator in subject:
                return False, f"Spam pattern detected: {indicator}"
        
        # Domain reputation check
        if "@" in from_address:
            domain = from_address.split("@")[1]
            suspicious_domains = [
                "noreply",
                "donotreply", 
                "no-reply",
                "notification"
            ]
            
            if any(suspicious in domain for suspicious in suspicious_domains):
                return False, f"Suspicious domain: {domain}"
        
        return True, "Passed smart filter"


class TaskExtractor:
    """Intelligent task extraction from emails"""
    
    async def extract_tasks_from_email(self, email_data: Dict, enhanced_analysis: Dict) -> List[Dict]:
        """Extract tasks from email based on enhanced analysis"""
        
        classification = enhanced_analysis.get("classification", "fyi")
        action_types = enhanced_analysis.get("action_types", [])
        complexity = enhanced_analysis.get("complexity", {})
        
        # Only create tasks for actionable emails
        if classification in ["fyi"]:
            return []
        
        tasks = []
        
        # Main task from email
        if classification in ["needs_response", "action_item", "meeting_request"]:
            main_task = await self._create_main_task(email_data, enhanced_analysis)
            if main_task:
                tasks.append(main_task)
        
        # Extract sub-tasks for complex emails
        if complexity.get("overall") == "high" and action_types:
            sub_tasks = await self._extract_sub_tasks(email_data, enhanced_analysis)
            tasks.extend(sub_tasks)
        
        return tasks
    
    async def _create_main_task(self, email_data: Dict, enhanced_analysis: Dict) -> Dict:
        """Create main task from email"""
        
        subject = email_data.get("subject", "")
        from_info = email_data.get("from", {})
        from_name = from_info.get("name", "Unknown") if isinstance(from_info, dict) else "Unknown"
        
        classification = enhanced_analysis.get("classification", "action_item")
        complexity_info = enhanced_analysis.get("complexity", {})
        urgency = enhanced_analysis.get("urgency", "medium")
        
        # Determine task complexity
        if complexity_info.get("overall") == "high":
            task_complexity = "deep"
        elif complexity_info.get("overall") == "medium":
            task_complexity = "medium"
        else:
            task_complexity = "quick"
        
        # Determine energy level
        if urgency in ["high", "critical"]:
            energy_level = "high_impact"
        elif enhanced_analysis.get("blocking_others"):
            energy_level = "high_impact"
        else:
            energy_level = "medium"
        
        # Create task title
        if classification == "needs_response":
            title = f"📧 Respond: {subject}"
        elif classification == "meeting_request":
            title = f"📅 Meeting: {subject}"
        else:
            title = f"📋 Action: {subject}"
        
        # Create description
        description = f"From: {from_name}\n"
        if enhanced_analysis.get("summary"):
            description += f"Summary: {enhanced_analysis['summary']}\n"
        if enhanced_analysis.get("action_needed"):
            description += f"Action: {enhanced_analysis['action_needed']}\n"
        
        return {
            "title": title[:100],  # Limit title length
            "description": description,
            "complexity": task_complexity,
            "energy": energy_level
        }
    
    async def _extract_sub_tasks(self, email_data: Dict, enhanced_analysis: Dict) -> List[Dict]:
        """Extract sub-tasks from complex emails"""
        
        # For now, return empty list - this could be expanded with more sophisticated parsing
        # Could use LLM to break down complex emails into sub-tasks
        return []


if __name__ == "__main__":
    async def main():
        pipeline = EnhancedPipeline()
        result = await pipeline.process_emails_with_intelligence(max_emails=50)
        print(f"\n📊 Enhanced Pipeline Results:")
        print(json.dumps(result, indent=2))
    
    asyncio.run(main())