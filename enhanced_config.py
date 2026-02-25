#!/usr/bin/env python3
"""
Enhanced Configuration Management
Manages settings for enhanced briefing and task extraction features
"""

import json
import os
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

class EnhancedConfig:
    """Configuration manager for enhanced features"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.config_file = os.path.join(data_dir, "enhanced_config.json")
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load enhanced configuration with defaults"""
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration"""
        return {
            "enhanced_features": {
                "enabled": True,
                "version": "2.0",
                "last_updated": datetime.now(timezone.utc).isoformat()
            },
            "enhanced_analyzer": {
                "enabled": True,
                "complexity_analysis": True,
                "stakeholder_extraction": True,
                "deadline_extraction": True,
                "time_estimation": True,
                "urgency_scoring": True,
                "pattern_matching": True,
                "fallback_to_basic": True
            },
            "enhanced_briefing": {
                "enabled": True,
                "priority_matrix": True,
                "workflow_insights": True,
                "energy_optimization": True,
                "bottleneck_analysis": True,
                "smart_recommendations": True,
                "pattern_detection": True,
                "prediction_engine": True,
                "cache_duration_minutes": 30
            },
            "enhanced_pipeline": {
                "enabled": True,
                "smart_filtering": True,
                "automatic_task_creation": True,
                "multi_source_integration": True,
                "enhanced_triage": True,
                "task_complexity_detection": True,
                "stakeholder_mapping": True
            },
            "task_extraction": {
                "auto_create_tasks": True,
                "complexity_threshold": "medium",  # quick, medium, deep
                "create_subtasks": False,
                "estimate_time": True,
                "extract_deadlines": True,
                "identify_blockers": True,
                "stakeholder_assignment": False
            },
            "contact_intelligence": {
                "dynamic_tier_learning": True,
                "response_time_tracking": True,
                "communication_pattern_analysis": True,
                "relationship_scoring": False,
                "auto_tier_adjustment": False
            },
            "performance": {
                "llm_timeout_seconds": 30,
                "max_concurrent_analysis": 5,
                "cache_analysis_results": True,
                "async_processing": True,
                "batch_processing": True,
                "background_enhancement": False
            },
            "integrations": {
                "office365_enhanced": True,
                "gmail_enhanced": True,
                "calendar_intelligence": True,
                "task_manager_sync": True,
                "crm_integration": False
            },
            "ui_preferences": {
                "show_complexity_badges": True,
                "show_time_estimates": True,
                "show_stakeholder_info": True,
                "enhanced_tooltips": True,
                "smart_sorting": True,
                "priority_highlighting": True
            },
            "privacy": {
                "store_enhanced_data": True,
                "anonymize_stakeholders": False,
                "limit_data_retention_days": 90,
                "export_enhanced_data": False
            },
            "experimental": {
                "ai_predictions": False,
                "auto_delegation": False,
                "smart_scheduling": False,
                "context_switching": False,
                "mood_detection": False
            }
        }
    
    def save_config(self) -> None:
        """Save configuration to file"""
        os.makedirs(self.data_dir, exist_ok=True)
        self.config["enhanced_features"]["last_updated"] = datetime.now(timezone.utc).isoformat()
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """Get configuration value using dot notation (e.g., 'enhanced_analyzer.enabled')"""
        keys = key_path.split('.')
        value = self.config
        
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key_path: str, value: Any) -> None:
        """Set configuration value using dot notation"""
        keys = key_path.split('.')
        config_section = self.config
        
        # Navigate to the parent section
        for key in keys[:-1]:
            if key not in config_section:
                config_section[key] = {}
            config_section = config_section[key]
        
        # Set the final value
        config_section[keys[-1]] = value
        self.save_config()
    
    def is_enabled(self, feature_path: str) -> bool:
        """Check if a feature is enabled"""
        return self.get(f"{feature_path}.enabled", False)
    
    def get_analyzer_config(self) -> Dict[str, Any]:
        """Get configuration for enhanced analyzer"""
        return self.config.get("enhanced_analyzer", {})
    
    def get_briefing_config(self) -> Dict[str, Any]:
        """Get configuration for enhanced briefing"""
        return self.config.get("enhanced_briefing", {})
    
    def get_pipeline_config(self) -> Dict[str, Any]:
        """Get configuration for enhanced pipeline"""
        return self.config.get("enhanced_pipeline", {})
    
    def get_task_extraction_config(self) -> Dict[str, Any]:
        """Get configuration for task extraction"""
        return self.config.get("task_extraction", {})
    
    def get_performance_config(self) -> Dict[str, Any]:
        """Get performance configuration"""
        return self.config.get("performance", {})
    
    def toggle_feature(self, feature_path: str) -> bool:
        """Toggle a feature on/off and return new state"""
        current = self.get(f"{feature_path}.enabled", False)
        new_state = not current
        self.set(f"{feature_path}.enabled", new_state)
        return new_state
    
    def reset_to_defaults(self) -> None:
        """Reset configuration to defaults"""
        self.config = self._get_default_config()
        self.save_config()
    
    def validate_config(self) -> Dict[str, Any]:
        """Validate configuration and return any issues"""
        issues = []
        warnings = []
        
        # Check required fields
        required_sections = [
            "enhanced_features", "enhanced_analyzer", "enhanced_briefing", 
            "enhanced_pipeline", "task_extraction", "performance"
        ]
        
        for section in required_sections:
            if section not in self.config:
                issues.append(f"Missing required section: {section}")
        
        # Check performance settings
        llm_timeout = self.get("performance.llm_timeout_seconds", 30)
        if llm_timeout < 10 or llm_timeout > 120:
            warnings.append(f"LLM timeout {llm_timeout}s may cause issues (recommended: 20-60s)")
        
        max_concurrent = self.get("performance.max_concurrent_analysis", 5)
        if max_concurrent > 10:
            warnings.append(f"Max concurrent analysis {max_concurrent} may overwhelm system")
        
        # Check cache duration
        cache_duration = self.get("enhanced_briefing.cache_duration_minutes", 30)
        if cache_duration < 5 or cache_duration > 120:
            warnings.append(f"Cache duration {cache_duration}m may impact performance")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings
        }
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get status summary of enhanced features"""
        return {
            "enhanced_features_enabled": self.is_enabled("enhanced_features"),
            "enhanced_analyzer_enabled": self.is_enabled("enhanced_analyzer"),
            "enhanced_briefing_enabled": self.is_enabled("enhanced_briefing"),
            "enhanced_pipeline_enabled": self.is_enabled("enhanced_pipeline"),
            "auto_task_creation": self.get("task_extraction.auto_create_tasks", False),
            "smart_filtering": self.get("enhanced_pipeline.smart_filtering", False),
            "priority_matrix": self.get("enhanced_briefing.priority_matrix", False),
            "workflow_insights": self.get("enhanced_briefing.workflow_insights", False),
            "last_updated": self.get("enhanced_features.last_updated", "Never"),
            "version": self.get("enhanced_features.version", "Unknown")
        }
    
    def export_config(self) -> str:
        """Export configuration as JSON string"""
        return json.dumps(self.config, indent=2)
    
    def import_config(self, config_json: str) -> bool:
        """Import configuration from JSON string"""
        try:
            imported_config = json.loads(config_json)
            
            # Validate imported config
            if "enhanced_features" not in imported_config:
                return False
            
            self.config = imported_config
            self.save_config()
            return True
            
        except json.JSONDecodeError:
            return False
    
    def get_feature_recommendations(self) -> List[Dict[str, str]]:
        """Get recommendations for feature configuration"""
        recommendations = []
        
        # Check if user might benefit from enhanced features
        if not self.is_enabled("enhanced_features"):
            recommendations.append({
                "type": "enable",
                "feature": "enhanced_features",
                "reason": "Enhanced features provide better email analysis and task extraction",
                "priority": "high"
            })
        
        if self.is_enabled("enhanced_analyzer") and not self.get("enhanced_analyzer.complexity_analysis"):
            recommendations.append({
                "type": "enable",
                "feature": "enhanced_analyzer.complexity_analysis",
                "reason": "Complexity analysis helps estimate task duration and priority",
                "priority": "medium"
            })
        
        if self.is_enabled("enhanced_briefing") and not self.get("enhanced_briefing.smart_recommendations"):
            recommendations.append({
                "type": "enable",
                "feature": "enhanced_briefing.smart_recommendations",
                "reason": "Smart recommendations provide actionable insights",
                "priority": "medium"
            })
        
        if self.get("task_extraction.auto_create_tasks") and self.get("task_extraction.complexity_threshold") == "quick":
            recommendations.append({
                "type": "adjust",
                "feature": "task_extraction.complexity_threshold",
                "reason": "Consider 'medium' threshold to avoid creating too many trivial tasks",
                "priority": "low"
            })
        
        return recommendations


class ConfigManager:
    """Global configuration manager"""
    
    _instance: Optional[EnhancedConfig] = None
    
    @classmethod
    def get_instance(cls, data_dir: str = "data") -> EnhancedConfig:
        """Get singleton config instance"""
        if cls._instance is None:
            cls._instance = EnhancedConfig(data_dir)
        return cls._instance
    
    @classmethod
    def reload(cls, data_dir: str = "data") -> EnhancedConfig:
        """Reload configuration"""
        cls._instance = EnhancedConfig(data_dir)
        return cls._instance


# Convenience functions
def get_config() -> EnhancedConfig:
    """Get global config instance"""
    return ConfigManager.get_instance()

def is_feature_enabled(feature_path: str) -> bool:
    """Check if feature is enabled"""
    return get_config().is_enabled(feature_path)

def get_setting(key_path: str, default: Any = None) -> Any:
    """Get configuration setting"""
    return get_config().get(key_path, default)

def set_setting(key_path: str, value: Any) -> None:
    """Set configuration setting"""
    get_config().set(key_path, value)


if __name__ == "__main__":
    # Test configuration system
    config = EnhancedConfig()
    
    print("Enhanced Configuration System Test")
    print("=" * 40)
    
    # Show status
    status = config.get_status_summary()
    print("Status:")
    for key, value in status.items():
        print(f"  {key}: {value}")
    
    # Show validation
    validation = config.validate_config()
    print(f"\nValidation: {'✅ Valid' if validation['valid'] else '❌ Invalid'}")
    if validation['issues']:
        print("Issues:")
        for issue in validation['issues']:
            print(f"  - {issue}")
    if validation['warnings']:
        print("Warnings:")
        for warning in validation['warnings']:
            print(f"  - {warning}")
    
    # Show recommendations
    recommendations = config.get_feature_recommendations()
    if recommendations:
        print("\nRecommendations:")
        for rec in recommendations:
            print(f"  {rec['priority'].upper()}: {rec['reason']}")
    
    print("\n✅ Configuration system working correctly")