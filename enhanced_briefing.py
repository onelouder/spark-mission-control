#!/usr/bin/env python3
"""
Enhanced Briefing System with Improved Intelligence
Builds on briefing.py with smarter context aggregation and insights
"""

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
import httpx

# Import base briefing functionality
from briefing import (
    call_llm, load_json_file, save_json_file, days_since, 
    get_pt_time_str, get_contact_tier, calculate_tier_weight,
    is_item_snoozed, get_calendar_events, DATA_DIR, PT
)

class EnhancedBriefing:
    """Enhanced briefing with smarter insights and context awareness"""
    
    def __init__(self):
        self.insight_cache_file = os.path.join(DATA_DIR, "briefing_insights_cache.json")
        self.pattern_cache_file = os.path.join(DATA_DIR, "briefing_patterns_cache.json")
    
    async def generate_enhanced_briefing(self) -> Dict:
        """Generate enhanced briefing with improved intelligence"""
        
        # Load base data
        processed_emails = load_json_file(os.path.join(DATA_DIR, "processed_emails.json"), {})
        emails = processed_emails.get("emails", {})
        tasks = load_json_file(os.path.join(DATA_DIR, "tasks.json"), [])
        contacts = load_json_file(os.path.join(DATA_DIR, "contacts.json"), {})
        
        # Generate enhanced insights
        insights = await self._generate_contextual_insights(emails, tasks, contacts)
        patterns = await self._detect_workflow_patterns(emails, tasks)
        predictions = await self._generate_predictions(emails, tasks, patterns)
        
        # Build enhanced blocks
        enhanced_blocks = {
            "priority_matrix": await self._build_priority_matrix(emails, tasks, insights),
            "workflow_insights": await self._build_workflow_insights(patterns, predictions),
            "context_threads": await self._build_enhanced_threads(emails, tasks, insights),
            "energy_optimization": await self._build_energy_optimization(tasks, patterns),
            "bottleneck_analysis": await self._analyze_bottlenecks(emails, tasks, insights),
            "smart_recommendations": await self._generate_smart_recommendations(emails, tasks, insights, patterns)
        }
        
        return {
            "generated_at": get_pt_time_str(),
            "enhanced_blocks": enhanced_blocks,
            "insights": insights,
            "patterns": patterns,
            "predictions": predictions
        }
    
    async def _generate_contextual_insights(self, emails: Dict, tasks: List[Dict], contacts: Dict) -> Dict:
        """Generate contextual insights about current workload"""
        
        # Analyze email context patterns
        domain_activity = self._analyze_domain_activity(emails)
        urgency_trends = self._analyze_urgency_trends(emails, tasks)
        response_patterns = self._analyze_response_patterns(emails)
        workload_distribution = self._analyze_workload_distribution(tasks)
        
        # Generate AI insights about patterns
        insight_prompt = f"""Analyze these work patterns and provide strategic insights:

Domain Activity: {json.dumps(domain_activity, indent=2)}
Urgency Trends: {json.dumps(urgency_trends, indent=2)}
Response Patterns: {json.dumps(response_patterns, indent=2)}
Workload Distribution: {json.dumps(workload_distribution, indent=2)}

Provide insights in JSON format:
{{
  "key_insights": ["3-4 strategic observations about work patterns"],
  "attention_areas": ["areas that need immediate attention"],
  "opportunities": ["opportunities for optimization"],
  "risk_factors": ["potential bottlenecks or issues"]
}}

Focus on actionable insights that would help prioritize work effectively."""
        
        try:
            insights_result = await call_llm(insight_prompt, timeout=30)
            if insights_result:
                import re
                json_match = re.search(r'\{.*\}', insights_result, re.DOTALL)
                if json_match:
                    ai_insights = json.loads(json_match.group())
                else:
                    ai_insights = {"key_insights": [], "attention_areas": [], "opportunities": [], "risk_factors": []}
            else:
                ai_insights = {"key_insights": [], "attention_areas": [], "opportunities": [], "risk_factors": []}
        except:
            ai_insights = {"key_insights": [], "attention_areas": [], "opportunities": [], "risk_factors": []}
        
        return {
            "domain_activity": domain_activity,
            "urgency_trends": urgency_trends,
            "response_patterns": response_patterns,
            "workload_distribution": workload_distribution,
            "ai_insights": ai_insights,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
    
    def _analyze_domain_activity(self, emails: Dict) -> Dict:
        """Analyze activity patterns by domain/context"""
        domain_stats = {}
        
        for email_id, email_info in emails.items():
            email_data = email_info.get("email_data", {})
            from_info = email_data.get("from", {})
            from_address = from_info.get("address", "") if isinstance(from_info, dict) else ""
            
            if "@" in from_address:
                domain = from_address.split("@")[1]
                
                if domain not in domain_stats:
                    domain_stats[domain] = {
                        "email_count": 0,
                        "unread_count": 0,
                        "action_items": 0,
                        "avg_response_time": 0,
                        "last_activity": None
                    }
                
                domain_stats[domain]["email_count"] += 1
                
                if not email_data.get("isRead", True):
                    domain_stats[domain]["unread_count"] += 1
                
                analysis = email_info.get("analysis", {})
                if analysis.get("classification") in ["action_item", "needs_response"]:
                    domain_stats[domain]["action_items"] += 1
                
                received_date = email_data.get("received", "")
                if received_date:
                    if not domain_stats[domain]["last_activity"] or received_date > domain_stats[domain]["last_activity"]:
                        domain_stats[domain]["last_activity"] = received_date
        
        # Sort by activity level
        sorted_domains = sorted(
            domain_stats.items(),
            key=lambda x: x[1]["action_items"] + x[1]["unread_count"],
            reverse=True
        )
        
        return {
            "top_active_domains": sorted_domains[:10],
            "total_domains": len(domain_stats),
            "action_item_domains": len([d for d in domain_stats.values() if d["action_items"] > 0])
        }
    
    def _analyze_urgency_trends(self, emails: Dict, tasks: List[Dict]) -> Dict:
        """Analyze urgency trends over time"""
        urgency_by_day = {}
        overdue_items = []
        
        # Analyze email urgency trends
        for email_id, email_info in emails.items():
            email_data = email_info.get("email_data", {})
            analysis = email_info.get("analysis", {})
            
            received_date = email_data.get("received", "")
            if received_date:
                try:
                    date_obj = datetime.fromisoformat(received_date.replace("Z", "+00:00"))
                    day_key = date_obj.strftime("%Y-%m-%d")
                    
                    if day_key not in urgency_by_day:
                        urgency_by_day[day_key] = {"high": 0, "medium": 0, "low": 0}
                    
                    urgency = analysis.get("urgency", "low")
                    urgency_by_day[day_key][urgency] += 1
                except:
                    continue
        
        # Check for overdue items
        for task in tasks:
            if task.get("column") in ["todo", "inprogress"]:
                created_at = task.get("created_at", "")
                if created_at:
                    days_old = days_since(created_at)
                    if days_old > 3:  # Overdue after 3 days
                        overdue_items.append({
                            "id": task["id"],
                            "title": task["title"],
                            "days_overdue": days_old,
                            "complexity": task.get("complexity", "medium")
                        })
        
        return {
            "urgency_trends": urgency_by_day,
            "overdue_items": sorted(overdue_items, key=lambda x: x["days_overdue"], reverse=True),
            "high_urgency_today": sum(day.get("high", 0) for day in urgency_by_day.values() if days_since(day) == 0)
        }
    
    def _analyze_response_patterns(self, emails: Dict) -> Dict:
        """Analyze email response patterns"""
        response_times = []
        pending_responses = []
        
        for email_id, email_info in emails.items():
            email_data = email_info.get("email_data", {})
            analysis = email_info.get("analysis", {})
            
            if analysis.get("classification") == "needs_response":
                days_waiting = days_since(email_data.get("received", ""))
                pending_responses.append({
                    "email_id": email_id,
                    "subject": email_data.get("subject", ""),
                    "from": email_data.get("from", {}).get("name", "Unknown"),
                    "days_waiting": days_waiting,
                    "urgency": analysis.get("urgency", "low")
                })
        
        # Calculate average response time for handled emails
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        return {
            "pending_responses": sorted(pending_responses, key=lambda x: x["days_waiting"], reverse=True),
            "avg_response_time_days": avg_response_time,
            "overdue_responses": len([r for r in pending_responses if r["days_waiting"] > 2])
        }
    
    def _analyze_workload_distribution(self, tasks: List[Dict]) -> Dict:
        """Analyze task workload distribution"""
        by_complexity = {"quick": 0, "medium": 0, "deep": 0}
        by_column = {}
        by_energy = {}
        stuck_tasks = []
        
        for task in tasks:
            complexity = task.get("complexity", "medium")
            column = task.get("column", "unsorted")
            energy = task.get("energy", "medium")
            
            if complexity in by_complexity:
                by_complexity[complexity] += 1
            
            by_column[column] = by_column.get(column, 0) + 1
            by_energy[energy] = by_energy.get(energy, 0) + 1
            
            # Check if task is stuck
            stuck_since = task.get("stuck_since", task.get("updated_at", ""))
            if stuck_since and days_since(stuck_since) > 5:
                stuck_tasks.append({
                    "id": task["id"],
                    "title": task["title"],
                    "days_stuck": days_since(stuck_since),
                    "complexity": complexity
                })
        
        return {
            "by_complexity": by_complexity,
            "by_column": by_column,
            "by_energy": by_energy,
            "stuck_tasks": sorted(stuck_tasks, key=lambda x: x["days_stuck"], reverse=True),
            "total_active": sum(by_column.get(col, 0) for col in ["todo", "inprogress"])
        }
    
    async def _detect_workflow_patterns(self, emails: Dict, tasks: List[Dict]) -> Dict:
        """Detect patterns in workflow and communication"""
        
        # Time-based patterns
        activity_by_hour = {}
        activity_by_day = {}
        
        # Communication patterns
        communication_frequency = {}
        project_clusters = {}
        
        # Task completion patterns
        completion_times = {}
        
        for email_id, email_info in emails.items():
            email_data = email_info.get("email_data", {})
            received_date = email_data.get("received", "")
            
            if received_date:
                try:
                    date_obj = datetime.fromisoformat(received_date.replace("Z", "+00:00"))
                    hour = date_obj.hour
                    day = date_obj.strftime("%A")
                    
                    activity_by_hour[hour] = activity_by_hour.get(hour, 0) + 1
                    activity_by_day[day] = activity_by_day.get(day, 0) + 1
                except:
                    continue
        
        return {
            "activity_by_hour": activity_by_hour,
            "activity_by_day": activity_by_day,
            "peak_hours": sorted(activity_by_hour.items(), key=lambda x: x[1], reverse=True)[:3],
            "busiest_days": sorted(activity_by_day.items(), key=lambda x: x[1], reverse=True)[:3]
        }
    
    async def _generate_predictions(self, emails: Dict, tasks: List[Dict], patterns: Dict) -> Dict:
        """Generate predictions about workload and priorities"""
        
        predictions = {
            "workload_forecast": self._predict_workload(emails, tasks, patterns),
            "bottleneck_risks": self._predict_bottlenecks(tasks, patterns),
            "optimal_work_times": self._predict_optimal_times(patterns),
            "completion_estimates": self._predict_completion_times(tasks)
        }
        
        return predictions
    
    def _predict_workload(self, emails: Dict, tasks: List[Dict], patterns: Dict) -> Dict:
        """Predict upcoming workload based on patterns"""
        # Simple prediction based on current trends
        current_action_items = len([
            e for e in emails.values() 
            if e.get("analysis", {}).get("classification") in ["action_item", "needs_response"]
        ])
        
        current_tasks = len([t for t in tasks if t.get("column") in ["todo", "inprogress"]])
        
        # Predict based on weekly patterns
        avg_daily_emails = sum(patterns.get("activity_by_day", {}).values()) / 7
        
        return {
            "current_load": current_action_items + current_tasks,
            "predicted_daily_items": round(avg_daily_emails * 0.3),  # Assume 30% become action items
            "workload_trend": "increasing" if current_action_items > 10 else "stable"
        }
    
    def _predict_bottlenecks(self, tasks: List[Dict], patterns: Dict) -> List[Dict]:
        """Predict potential bottlenecks"""
        bottlenecks = []
        
        # Check for accumulating tasks in specific categories
        complexity_counts = {}
        for task in tasks:
            if task.get("column") in ["todo", "inprogress"]:
                complexity = task.get("complexity", "medium")
                complexity_counts[complexity] = complexity_counts.get(complexity, 0) + 1
        
        # If too many complex tasks accumulating
        if complexity_counts.get("deep", 0) > 3:
            bottlenecks.append({
                "type": "complexity_overload",
                "description": f"{complexity_counts['deep']} deep complexity tasks may create bottleneck",
                "risk_level": "medium"
            })
        
        return bottlenecks
    
    def _predict_optimal_times(self, patterns: Dict) -> Dict:
        """Predict optimal work times based on patterns"""
        peak_hours = patterns.get("peak_hours", [])
        
        if peak_hours:
            # Suggest work time opposite to peak communication
            busy_hours = [h[0] for h in peak_hours]
            quiet_hours = [h for h in range(24) if h not in busy_hours]
            
            return {
                "focus_time_hours": quiet_hours[:3],
                "communication_hours": busy_hours,
                "deep_work_windows": self._find_deep_work_windows(busy_hours)
            }
        
        return {"focus_time_hours": [9, 10, 11], "communication_hours": [13, 14, 15]}
    
    def _find_deep_work_windows(self, busy_hours: List[int]) -> List[Dict]:
        """Find 2+ hour windows without interruptions"""
        windows = []
        current_start = None
        current_length = 0
        
        for hour in range(24):
            if hour not in busy_hours:
                if current_start is None:
                    current_start = hour
                current_length += 1
            else:
                if current_start is not None and current_length >= 2:
                    windows.append({
                        "start_hour": current_start,
                        "duration_hours": current_length
                    })
                current_start = None
                current_length = 0
        
        return windows
    
    def _predict_completion_times(self, tasks: List[Dict]) -> Dict:
        """Predict task completion times based on complexity"""
        complexity_times = {
            "quick": 0.5,   # 30 minutes
            "medium": 2,    # 2 hours
            "deep": 8       # 8 hours
        }
        
        total_hours = 0
        task_estimates = []
        
        for task in tasks:
            if task.get("column") in ["todo", "inprogress"]:
                complexity = task.get("complexity", "medium")
                estimated_hours = complexity_times.get(complexity, 2)
                total_hours += estimated_hours
                
                task_estimates.append({
                    "id": task["id"],
                    "title": task["title"],
                    "estimated_hours": estimated_hours
                })
        
        return {
            "total_estimated_hours": total_hours,
            "estimated_days": round(total_hours / 8, 1),
            "task_estimates": task_estimates
        }
    
    async def _build_priority_matrix(self, emails: Dict, tasks: List[Dict], insights: Dict) -> Dict:
        """Build an enhanced priority matrix"""
        matrix = {
            "urgent_important": [],
            "urgent_not_important": [],
            "not_urgent_important": [],
            "not_urgent_not_important": []
        }
        
        # Classify emails and tasks into matrix
        for email_id, email_info in emails.items():
            if is_item_snoozed(email_id, "email"):
                continue
                
            analysis = email_info.get("analysis", {})
            urgency = analysis.get("urgency", "low")
            classification = analysis.get("classification", "fyi")
            
            # Determine importance based on classification and contact tier
            is_important = classification in ["needs_response", "action_item"]
            is_urgent = urgency in ["high", "critical"]
            
            item = {
                "id": email_id,
                "type": "email",
                "title": email_info.get("email_data", {}).get("subject", ""),
                "urgency": urgency,
                "importance": "high" if is_important else "low"
            }
            
            if is_urgent and is_important:
                matrix["urgent_important"].append(item)
            elif is_urgent and not is_important:
                matrix["urgent_not_important"].append(item)
            elif not is_urgent and is_important:
                matrix["not_urgent_important"].append(item)
            else:
                matrix["not_urgent_not_important"].append(item)
        
        # Add tasks to matrix
        for task in tasks:
            if task.get("column") not in ["todo", "inprogress"] or is_item_snoozed(task["id"], "task"):
                continue
            
            complexity = task.get("complexity", "medium")
            energy = task.get("energy", "medium")
            days_old = days_since(task.get("created_at", ""))
            
            is_urgent = days_old > 3 or complexity == "quick"
            is_important = complexity in ["deep", "medium"] or energy == "high_impact"
            
            item = {
                "id": task["id"],
                "type": "task",
                "title": task["title"],
                "complexity": complexity,
                "days_old": days_old
            }
            
            if is_urgent and is_important:
                matrix["urgent_important"].append(item)
            elif is_urgent and not is_important:
                matrix["urgent_not_important"].append(item)
            elif not is_urgent and is_important:
                matrix["not_urgent_important"].append(item)
            else:
                matrix["not_urgent_not_important"].append(item)
        
        return matrix
    
    async def _build_workflow_insights(self, patterns: Dict, predictions: Dict) -> Dict:
        """Build workflow insights section"""
        return {
            "patterns": patterns,
            "predictions": predictions,
            "optimization_suggestions": [
                f"Peak activity: {patterns.get('peak_hours', [[0, 0]])[0][0]}:00 - consider blocking for focus",
                f"Busiest day: {patterns.get('busiest_days', [['Unknown', 0]])[0][0]} - plan lighter meetings",
                f"Estimated workload: {predictions.get('workload_forecast', {}).get('estimated_days', 0)} days"
            ]
        }
    
    async def _build_enhanced_threads(self, emails: Dict, tasks: List[Dict], insights: Dict) -> List[Dict]:
        """Build enhanced active threads with better context"""
        # This would expand on the base active threads with more intelligence
        # For now, return a placeholder that integrates insights
        return [
            {
                "title": "Enhanced Thread Analysis",
                "status": "Active pattern analysis integrated",
                "insight": "Using domain activity patterns for better thread detection"
            }
        ]
    
    async def _build_energy_optimization(self, tasks: List[Dict], patterns: Dict) -> Dict:
        """Build energy optimization recommendations"""
        high_energy_tasks = [t for t in tasks if t.get("energy") == "high_impact" and t.get("column") in ["todo", "inprogress"]]
        low_energy_tasks = [t for t in tasks if t.get("energy") == "low_stakes" and t.get("column") in ["todo", "inprogress"]]
        
        optimal_times = patterns.get("peak_hours", [])
        
        return {
            "high_energy_tasks": len(high_energy_tasks),
            "low_energy_tasks": len(low_energy_tasks),
            "recommendations": [
                f"Schedule {len(high_energy_tasks)} high-impact tasks during peak focus hours",
                f"Use communication windows for {len(low_energy_tasks)} low-stakes tasks",
                "Consider batching similar complexity tasks together"
            ],
            "optimal_schedule": self._generate_optimal_schedule(high_energy_tasks, low_energy_tasks, optimal_times)
        }
    
    def _generate_optimal_schedule(self, high_energy: List, low_energy: List, optimal_times: List) -> List[Dict]:
        """Generate an optimal task schedule"""
        schedule = []
        
        # Schedule high-energy tasks during optimal focus times
        focus_hours = [9, 10, 11, 14, 15]  # Default focus hours
        
        for i, task in enumerate(high_energy[:len(focus_hours)]):
            schedule.append({
                "time_slot": f"{focus_hours[i]}:00",
                "task_id": task["id"],
                "task_title": task["title"],
                "type": "high_energy",
                "duration": "90 minutes"
            })
        
        return schedule
    
    async def _analyze_bottlenecks(self, emails: Dict, tasks: List[Dict], insights: Dict) -> Dict:
        """Analyze current bottlenecks"""
        bottlenecks = []
        
        # Email response bottlenecks
        pending_responses = insights.get("response_patterns", {}).get("pending_responses", [])
        if len(pending_responses) > 5:
            bottlenecks.append({
                "type": "email_response",
                "description": f"{len(pending_responses)} emails waiting for response",
                "impact": "high" if len(pending_responses) > 10 else "medium",
                "recommendation": "Schedule dedicated email response time"
            })
        
        # Task complexity bottlenecks
        stuck_tasks = insights.get("workload_distribution", {}).get("stuck_tasks", [])
        if stuck_tasks:
            bottlenecks.append({
                "type": "stuck_tasks",
                "description": f"{len(stuck_tasks)} tasks stuck for >5 days",
                "impact": "medium",
                "recommendation": "Review and break down complex tasks"
            })
        
        return {
            "current_bottlenecks": bottlenecks,
            "bottleneck_count": len(bottlenecks),
            "resolution_priority": sorted(bottlenecks, key=lambda x: x["impact"], reverse=True)
        }
    
    async def _generate_smart_recommendations(self, emails: Dict, tasks: List[Dict], insights: Dict, patterns: Dict) -> List[Dict]:
        """Generate smart recommendations based on analysis"""
        recommendations = []
        
        # Time management recommendations
        peak_hours = patterns.get("peak_hours", [])
        if peak_hours:
            recommendations.append({
                "category": "time_management",
                "priority": "high",
                "title": "Optimize Communication Windows",
                "description": f"Peak email activity at {peak_hours[0][0]}:00. Consider focus blocks before/after.",
                "action": f"Block {peak_hours[0][0]-2}:00-{peak_hours[0][0]}:00 for deep work"
            })
        
        # Workload recommendations
        workload = insights.get("workload_distribution", {})
        if workload.get("total_active", 0) > 20:
            recommendations.append({
                "category": "workload",
                "priority": "medium", 
                "title": "High Task Load Detected",
                "description": f"{workload['total_active']} active tasks may impact focus",
                "action": "Consider deferring or delegating lower-priority tasks"
            })
        
        # Response time recommendations
        response_patterns = insights.get("response_patterns", {})
        if response_patterns.get("overdue_responses", 0) > 3:
            recommendations.append({
                "category": "communication",
                "priority": "high",
                "title": "Response Time Alert",
                "description": f"{response_patterns['overdue_responses']} overdue email responses",
                "action": "Schedule 30-minute email response session today"
            })
        
        return recommendations