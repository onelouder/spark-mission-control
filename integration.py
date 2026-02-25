#!/usr/bin/env python3
"""
Enhanced System Integration
Hooks enhanced briefing and email processing into existing Mission Control
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

# Import existing components
from briefing import generate_full_briefing
from pipeline import sync_and_process_emails

# Import enhanced components
from enhanced_briefing import EnhancedBriefing
from enhanced_pipeline import EnhancedPipeline
from enhanced_config import get_config, is_feature_enabled

class IntegrationManager:
    """Manages integration between enhanced and legacy systems"""
    
    def __init__(self):
        self.config = get_config()
        self.enhanced_briefing = EnhancedBriefing() if is_feature_enabled("enhanced_briefing") else None
        self.enhanced_pipeline = EnhancedPipeline() if is_feature_enabled("enhanced_pipeline") else None
        
    async def generate_briefing(self, force_refresh: bool = False) -> Dict:
        """Generate briefing using appropriate system"""
        
        if is_feature_enabled("enhanced_briefing") and self.enhanced_briefing:
            return await self._generate_enhanced_briefing(force_refresh)
        else:
            return await self._generate_legacy_briefing(force_refresh)
    
    async def _generate_enhanced_briefing(self, force_refresh: bool = False) -> Dict:
        """Generate enhanced briefing with legacy compatibility"""
        
        # Check cache first unless force refresh
        cache_file = "data/integrated_briefing_cache.json"
        cache_duration_minutes = self.config.get("enhanced_briefing.cache_duration_minutes", 30)
        
        if not force_refresh and os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    cached = json.load(f)
                    cached_time = datetime.fromisoformat(cached["cached_at"])
                    if (datetime.now(timezone.utc) - cached_time).seconds < cache_duration_minutes * 60:
                        return cached["briefing"]
            except:
                pass
        
        print("🚀 Generating enhanced briefing...")
        
        # Generate both enhanced and legacy briefings
        enhanced_briefing_data = await self.enhanced_briefing.generate_enhanced_briefing()
        legacy_briefing_data = await generate_full_briefing()
        
        # Merge the briefings
        integrated_briefing = await self._merge_briefings(legacy_briefing_data, enhanced_briefing_data)
        
        # Cache the result
        cache_data = {
            "briefing": integrated_briefing,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "enhanced_features_used": True
        }
        
        try:
            os.makedirs("data", exist_ok=True)
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
        except:
            pass  # Cache failure shouldn't break briefing
        
        return integrated_briefing
    
    async def _generate_legacy_briefing(self, force_refresh: bool = False) -> Dict:
        """Generate legacy briefing"""
        print("📊 Generating legacy briefing...")
        return await generate_full_briefing()
    
    async def _merge_briefings(self, legacy: Dict, enhanced: Dict) -> Dict:
        """Merge legacy and enhanced briefing data"""
        
        # Start with legacy structure
        merged = dict(legacy)
        
        # Add enhanced blocks as additional sections
        if "enhanced_blocks" in enhanced:
            merged["enhanced_blocks"] = enhanced["enhanced_blocks"]
        
        # Enhance existing blocks with additional data
        if "blocks" in merged:
            # Enhance decisions block with priority matrix data
            if "priority_matrix" in enhanced.get("enhanced_blocks", {}):
                priority_matrix = enhanced["enhanced_blocks"]["priority_matrix"]
                merged["blocks"]["priority_matrix"] = {
                    "title": "PRIORITY MATRIX",
                    "data": priority_matrix,
                    "enhanced": True
                }
            
            # Add workflow insights
            if "workflow_insights" in enhanced.get("enhanced_blocks", {}):
                merged["blocks"]["workflow_insights"] = {
                    "title": "WORKFLOW INSIGHTS",
                    "data": enhanced["enhanced_blocks"]["workflow_insights"],
                    "enhanced": True
                }
            
            # Add smart recommendations
            if "smart_recommendations" in enhanced.get("enhanced_blocks", {}):
                merged["blocks"]["smart_recommendations"] = {
                    "title": "SMART RECOMMENDATIONS",
                    "data": enhanced["enhanced_blocks"]["smart_recommendations"],
                    "enhanced": True,
                    "always_expanded": True
                }
        
        # Add metadata
        merged["enhanced_features"] = {
            "enabled": True,
            "generated_at": enhanced.get("generated_at"),
            "insights_available": "insights" in enhanced,
            "patterns_detected": "patterns" in enhanced
        }
        
        return merged
    
    async def process_emails(self, max_emails: int = 100) -> Dict:
        """Process emails using appropriate pipeline"""
        
        if is_feature_enabled("enhanced_pipeline") and self.enhanced_pipeline:
            return await self._process_enhanced_emails(max_emails)
        else:
            return await self._process_legacy_emails(max_emails)
    
    async def _process_enhanced_emails(self, max_emails: int = 100) -> Dict:
        """Process emails with enhanced pipeline"""
        print("🚀 Processing emails with enhanced pipeline...")
        
        result = await self.enhanced_pipeline.process_emails_with_intelligence(max_emails)
        
        # Add legacy compatibility
        result["legacy_compatible"] = True
        result["enhanced_features_used"] = True
        
        return result
    
    async def _process_legacy_emails(self, max_emails: int = 100) -> Dict:
        """Process emails with legacy pipeline"""
        print("📊 Processing emails with legacy pipeline...")
        return await sync_and_process_emails(max_emails)
    
    async def get_system_status(self) -> Dict:
        """Get status of integrated system"""
        
        config_status = self.config.get_status_summary()
        validation = self.config.validate_config()
        
        # Test component availability
        component_status = {
            "enhanced_briefing_available": self.enhanced_briefing is not None,
            "enhanced_pipeline_available": self.enhanced_pipeline is not None,
            "enhanced_analyzer_available": is_feature_enabled("enhanced_analyzer"),
            "config_valid": validation["valid"]
        }
        
        # Check data files
        data_files = {
            "processed_emails": os.path.exists("data/processed_emails.json"),
            "tasks": os.path.exists("data/tasks.json"),
            "contacts": os.path.exists("data/contacts.json"),
            "enhanced_config": os.path.exists("data/enhanced_config.json")
        }
        
        return {
            "integration_status": "active" if any(component_status.values()) else "disabled",
            "config_status": config_status,
            "component_status": component_status,
            "data_files": data_files,
            "validation": validation,
            "last_check": datetime.now(timezone.utc).isoformat()
        }
    
    async def migrate_data(self) -> Dict:
        """Migrate existing data to support enhanced features"""
        print("🔄 Migrating data for enhanced features...")
        
        migration_results = {
            "emails_migrated": 0,
            "tasks_migrated": 0,
            "contacts_migrated": 0,
            "errors": []
        }
        
        try:
            # Migrate processed emails to include enhanced analysis placeholders
            await self._migrate_processed_emails(migration_results)
            
            # Migrate tasks to include enhanced fields
            await self._migrate_tasks(migration_results)
            
            # Migrate contacts for intelligence features
            await self._migrate_contacts(migration_results)
            
        except Exception as e:
            migration_results["errors"].append(f"Migration failed: {e}")
        
        return migration_results
    
    async def _migrate_processed_emails(self, results: Dict) -> None:
        """Migrate processed emails"""
        emails_file = "data/processed_emails.json"
        
        if not os.path.exists(emails_file):
            return
        
        try:
            with open(emails_file, 'r') as f:
                data = json.load(f)
            
            emails = data.get("emails", {})
            migrated_count = 0
            
            for email_id, email_data in emails.items():
                # Add enhanced analysis placeholder if not exists
                if "enhanced_analysis" not in email_data:
                    email_data["enhanced_analysis"] = {
                        "migrated": True,
                        "requires_reanalysis": True,
                        "migration_date": datetime.now(timezone.utc).isoformat()
                    }
                    migrated_count += 1
            
            # Save migrated data
            with open(emails_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            results["emails_migrated"] = migrated_count
            
        except Exception as e:
            results["errors"].append(f"Email migration failed: {e}")
    
    async def _migrate_tasks(self, results: Dict) -> None:
        """Migrate tasks"""
        tasks_file = "data/tasks.json"
        
        if not os.path.exists(tasks_file):
            return
        
        try:
            with open(tasks_file, 'r') as f:
                tasks = json.load(f)
            
            migrated_count = 0
            
            for task in tasks:
                # Add enhanced fields if not exists
                enhanced_fields = {
                    "estimated_time": None,
                    "stakeholders": [],
                    "blocking_others": False,
                    "enhanced_extraction": False,
                    "migration_date": datetime.now(timezone.utc).isoformat()
                }
                
                for field, default_value in enhanced_fields.items():
                    if field not in task:
                        task[field] = default_value
                        migrated_count += 1
            
            # Save migrated data
            with open(tasks_file, 'w') as f:
                json.dump(tasks, f, indent=2)
            
            results["tasks_migrated"] = migrated_count
            
        except Exception as e:
            results["errors"].append(f"Task migration failed: {e}")
    
    async def _migrate_contacts(self, results: Dict) -> None:
        """Migrate contacts"""
        contacts_file = "data/contacts.json"
        
        if not os.path.exists(contacts_file):
            return
        
        try:
            with open(contacts_file, 'r') as f:
                contacts = json.load(f)
            
            # Add enhanced contact intelligence fields
            if "intelligence" not in contacts:
                contacts["intelligence"] = {
                    "response_patterns": {},
                    "communication_frequency": {},
                    "relationship_scores": {},
                    "last_analysis": datetime.now(timezone.utc).isoformat()
                }
                results["contacts_migrated"] = 1
            
            # Save migrated data
            with open(contacts_file, 'w') as f:
                json.dump(contacts, f, indent=2)
                
        except Exception as e:
            results["errors"].append(f"Contact migration failed: {e}")
    
    async def run_system_check(self) -> Dict:
        """Run comprehensive system check"""
        print("🔧 Running enhanced system check...")
        
        checks = {
            "config_validation": self.config.validate_config(),
            "system_status": await self.get_system_status(),
            "feature_recommendations": self.config.get_feature_recommendations(),
            "data_integrity": await self._check_data_integrity(),
            "performance_metrics": await self._check_performance()
        }
        
        # Overall health score
        health_score = self._calculate_health_score(checks)
        checks["overall_health"] = {
            "score": health_score,
            "status": "excellent" if health_score > 0.9 else "good" if health_score > 0.7 else "needs_attention"
        }
        
        return checks
    
    async def _check_data_integrity(self) -> Dict:
        """Check data file integrity"""
        integrity = {
            "files_checked": 0,
            "files_valid": 0,
            "files_corrupted": [],
            "missing_files": []
        }
        
        required_files = [
            "data/processed_emails.json",
            "data/tasks.json", 
            "data/contacts.json"
        ]
        
        for file_path in required_files:
            integrity["files_checked"] += 1
            
            if not os.path.exists(file_path):
                integrity["missing_files"].append(file_path)
                continue
            
            try:
                with open(file_path, 'r') as f:
                    json.load(f)
                integrity["files_valid"] += 1
            except json.JSONDecodeError:
                integrity["files_corrupted"].append(file_path)
        
        return integrity
    
    async def _check_performance(self) -> Dict:
        """Check system performance metrics"""
        
        # This would normally check actual performance metrics
        # For now, return basic estimates
        return {
            "briefing_generation_time_estimate": "5-15 seconds",
            "email_processing_time_estimate": "10-30 seconds", 
            "analysis_accuracy_estimate": "85-95%",
            "cache_hit_rate_estimate": "70-80%",
            "memory_usage_status": "normal"
        }
    
    def _calculate_health_score(self, checks: Dict) -> float:
        """Calculate overall system health score"""
        
        config_score = 1.0 if checks["config_validation"]["valid"] else 0.5
        
        status = checks["system_status"]
        status_score = sum(status["component_status"].values()) / len(status["component_status"])
        
        data_integrity = checks["data_integrity"]
        data_score = data_integrity["files_valid"] / max(data_integrity["files_checked"], 1)
        
        # Weight the scores
        overall_score = (config_score * 0.3 + status_score * 0.5 + data_score * 0.2)
        
        return round(overall_score, 2)


# Global integration manager instance
_integration_manager = None

def get_integration_manager() -> IntegrationManager:
    """Get global integration manager"""
    global _integration_manager
    if _integration_manager is None:
        _integration_manager = IntegrationManager()
    return _integration_manager

# Convenience functions for Flask app integration
async def integrated_briefing(force_refresh: bool = False) -> Dict:
    """Generate integrated briefing"""
    return await get_integration_manager().generate_briefing(force_refresh)

async def integrated_email_processing(max_emails: int = 100) -> Dict:
    """Process emails with integrated pipeline"""
    return await get_integration_manager().process_emails(max_emails)

async def system_health_check() -> Dict:
    """Get system health check"""
    return await get_integration_manager().run_system_check()


if __name__ == "__main__":
    async def test_integration():
        """Test integration system"""
        print("🧪 Testing Enhanced System Integration")
        print("=" * 50)
        
        manager = IntegrationManager()
        
        # Test system status
        print("📊 Checking system status...")
        status = await manager.get_system_status()
        print(f"Integration status: {status['integration_status']}")
        print(f"Enhanced features: {sum(status['component_status'].values())}/4 enabled")
        
        # Test migration
        print("\n🔄 Testing data migration...")
        migration = await manager.migrate_data()
        print(f"Migrated: {migration['emails_migrated']} emails, {migration['tasks_migrated']} tasks")
        
        # Test system check
        print("\n🔧 Running system check...")
        check_results = await manager.run_system_check()
        health = check_results["overall_health"]
        print(f"System health: {health['score']:.1%} ({health['status']})")
        
        # Show recommendations
        recommendations = check_results.get("feature_recommendations", [])
        if recommendations:
            print(f"\n💡 {len(recommendations)} recommendations available")
        
        print("\n✅ Integration testing complete")
    
    asyncio.run(test_integration())