#!/usr/bin/env python3
"""
Mission Control Upgrade Script
Integrates enhanced briefing and email processing into existing app.py
"""

import os
import shutil
import re
from datetime import datetime
from typing import List, Tuple

class MissionControlUpgrader:
    """Handles upgrading Mission Control to use enhanced features"""
    
    def __init__(self, app_file: str = "app.py"):
        self.app_file = app_file
        self.backup_file = f"app.py.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.upgrade_log = []
    
    def upgrade(self) -> bool:
        """Run the full upgrade process"""
        try:
            print("🚀 Starting Mission Control upgrade...")
            
            # Step 1: Create backup
            self._create_backup()
            
            # Step 2: Read current app.py
            content = self._read_app_file()
            
            # Step 3: Add enhanced imports
            content = self._add_enhanced_imports(content)
            
            # Step 4: Modify briefing endpoints
            content = self._upgrade_briefing_endpoints(content)
            
            # Step 5: Modify email processing endpoints
            content = self._upgrade_email_endpoints(content)
            
            # Step 6: Add new enhanced endpoints
            content = self._add_enhanced_endpoints(content)
            
            # Step 7: Update background tasks
            content = self._update_background_tasks(content)
            
            # Step 8: Write upgraded file
            self._write_app_file(content)
            
            # Step 9: Create configuration files
            self._create_config_files()
            
            print("✅ Mission Control upgrade completed successfully!")
            print(f"📄 Backup created: {self.backup_file}")
            self._print_upgrade_summary()
            
            return True
            
        except Exception as e:
            print(f"❌ Upgrade failed: {e}")
            self._restore_backup()
            return False
    
    def _create_backup(self) -> None:
        """Create backup of original app.py"""
        if os.path.exists(self.app_file):
            shutil.copy2(self.app_file, self.backup_file)
            self.upgrade_log.append(f"✅ Created backup: {self.backup_file}")
        else:
            raise FileNotFoundError(f"app.py not found at {self.app_file}")
    
    def _read_app_file(self) -> str:
        """Read current app.py content"""
        with open(self.app_file, 'r') as f:
            return f.read()
    
    def _write_app_file(self, content: str) -> None:
        """Write upgraded app.py content"""
        with open(self.app_file, 'w') as f:
            f.write(content)
    
    def _add_enhanced_imports(self, content: str) -> str:
        """Add enhanced system imports"""
        
        # Find the import section
        import_section = "# Import enhanced systems (added by upgrade script)\\n"
        import_section += "try:\\n"
        import_section += "    from integration import integrated_briefing, integrated_email_processing, system_health_check\\n"
        import_section += "    from enhanced_config import get_config, is_feature_enabled\\n"
        import_section += "    ENHANCED_FEATURES_AVAILABLE = True\\n"
        import_section += "    print(\\"[STARTUP] Enhanced features loaded successfully\\")\\n"
        import_section += "except ImportError as e:\\n"
        import_section += "    print(f\\"[STARTUP] Enhanced features not available: {e}\\")\\n"
        import_section += "    ENHANCED_FEATURES_AVAILABLE = False\\n"
        import_section += "\\n"
        
        # Insert after existing imports
        import_pattern = r"(from briefing import.*?\\n)"
        replacement = r"\\1\\n" + import_section
        
        content = re.sub(import_pattern, replacement, content, flags=re.DOTALL)
        self.upgrade_log.append("✅ Added enhanced system imports")
        
        return content
    
    def _upgrade_briefing_endpoints(self, content: str) -> str:
        """Upgrade briefing endpoints to use enhanced system"""
        
        # Find and replace the briefing endpoint
        old_briefing_pattern = r"@app\\.get\\(\\"/api/briefing\\"\\)\\s*async def get_briefing\\(\\):(.*?)return briefing_data"
        
        new_briefing_function = '''@app.get("/api/briefing")
async def get_briefing():
    """Get briefing using enhanced or legacy system"""
    try:
        if ENHANCED_FEATURES_AVAILABLE and is_feature_enabled("enhanced_briefing"):
            briefing_data = await integrated_briefing(force_refresh=False)
        else:
            briefing_data = await generate_full_briefing()
        
        return briefing_data
    except Exception as e:
        print(f"[ERROR] Briefing generation failed: {e}")
        return {"error": "Failed to generate briefing", "details": str(e)}'''
        
        if re.search(old_briefing_pattern, content, re.DOTALL):
            content = re.sub(old_briefing_pattern, new_briefing_function, content, flags=re.DOTALL)
            self.upgrade_log.append("✅ Upgraded briefing endpoint")
        else:
            # Add new endpoint if not found
            content = self._insert_before_main(content, new_briefing_function + "\\n\\n")
            self.upgrade_log.append("✅ Added enhanced briefing endpoint")
        
        return content
    
    def _upgrade_email_endpoints(self, content: str) -> str:
        """Upgrade email processing endpoints"""
        
        # Find and replace email sync endpoint
        old_email_pattern = r"@app\\.get\\(\\"/api/sync/email\\"\\)\\s*async def sync_email\\(\\):(.*?)return \\{.*?\\}"
        
        new_email_function = '''@app.get("/api/sync/email")
async def sync_email():
    """Sync emails using enhanced or legacy pipeline"""
    try:
        if ENHANCED_FEATURES_AVAILABLE and is_feature_enabled("enhanced_pipeline"):
            result = await integrated_email_processing(max_emails=100)
        else:
            result = await sync_and_process_emails(max_emails=100)
        
        return result
    except Exception as e:
        print(f"[ERROR] Email sync failed: {e}")
        return {"error": "Failed to sync emails", "details": str(e)}'''
        
        if re.search(old_email_pattern, content, re.DOTALL):
            content = re.sub(old_email_pattern, new_email_function, content, flags=re.DOTALL)
            self.upgrade_log.append("✅ Upgraded email sync endpoint")
        else:
            content = self._insert_before_main(content, new_email_function + "\\n\\n")
            self.upgrade_log.append("✅ Added enhanced email sync endpoint")
        
        return content
    
    def _add_enhanced_endpoints(self, content: str) -> str:
        """Add new enhanced feature endpoints"""
        
        enhanced_endpoints = '''
# Enhanced feature endpoints (added by upgrade script)

@app.get("/api/enhanced/status")
async def get_enhanced_status():
    """Get enhanced features status"""
    if not ENHANCED_FEATURES_AVAILABLE:
        return {"available": False, "reason": "Enhanced features not loaded"}
    
    try:
        status = await system_health_check()
        return {"available": True, "status": status}
    except Exception as e:
        return {"available": False, "error": str(e)}

@app.get("/api/enhanced/config")
async def get_enhanced_config():
    """Get enhanced configuration"""
    if not ENHANCED_FEATURES_AVAILABLE:
        return {"error": "Enhanced features not available"}
    
    try:
        config = get_config()
        return {
            "status": config.get_status_summary(),
            "validation": config.validate_config(),
            "recommendations": config.get_feature_recommendations()
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/enhanced/config")
async def update_enhanced_config(request: Request):
    """Update enhanced configuration"""
    if not ENHANCED_FEATURES_AVAILABLE:
        return {"error": "Enhanced features not available"}
    
    try:
        data = await request.json()
        config = get_config()
        
        # Update configuration
        for key, value in data.items():
            config.set(key, value)
        
        return {"success": True, "message": "Configuration updated"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/briefing/refresh")
async def refresh_briefing():
    """Force refresh briefing cache"""
    try:
        if ENHANCED_FEATURES_AVAILABLE and is_feature_enabled("enhanced_briefing"):
            briefing_data = await integrated_briefing(force_refresh=True)
        else:
            briefing_data = await generate_full_briefing()
        
        return {"success": True, "briefing": briefing_data}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/analytics/insights")
async def get_analytics_insights():
    """Get enhanced analytics insights"""
    if not ENHANCED_FEATURES_AVAILABLE:
        return {"error": "Enhanced features not available"}
    
    try:
        # This would return insights from enhanced briefing
        return {"insights": "Enhanced analytics not yet implemented"}
    except Exception as e:
        return {"error": str(e)}
'''
        
        # Insert before the main block
        content = self._insert_before_main(content, enhanced_endpoints)
        self.upgrade_log.append("✅ Added enhanced feature endpoints")
        
        return content
    
    def _update_background_tasks(self, content: str) -> str:
        """Update background tasks to use enhanced features when available"""
        
        # Find the background task functions
        task_pattern = r"async def periodic_briefing_refresh\\(\\):(.*?)await asyncio\\.sleep\\(900\\)"
        
        enhanced_task = '''async def periodic_briefing_refresh():
    """Enhanced background briefing refresh"""
    while True:
        try:
            print(f"[PERIODIC] Refreshing briefing cache at {datetime.now()}")
            
            if ENHANCED_FEATURES_AVAILABLE and is_feature_enabled("enhanced_briefing"):
                await integrated_briefing(force_refresh=True)
                print("[PERIODIC] Enhanced briefing cache refreshed")
            else:
                await generate_full_briefing()
                print("[PERIODIC] Legacy briefing cache refreshed")
                
        except Exception as e:
            print(f"[PERIODIC] Briefing refresh failed: {e}")
        
        await asyncio.sleep(900)  # 15 minutes'''
        
        if re.search(task_pattern, content, re.DOTALL):
            content = re.sub(task_pattern, enhanced_task, content, flags=re.DOTALL)
            self.upgrade_log.append("✅ Updated periodic briefing refresh task")
        
        # Update email sync task
        email_task_pattern = r"async def periodic_email_sync\\(\\):(.*?)await asyncio\\.sleep\\(1800\\)"
        
        enhanced_email_task = '''async def periodic_email_sync():
    """Enhanced background email sync"""
    while True:
        try:
            print(f"[PERIODIC] Syncing emails at {datetime.now()}")
            
            if ENHANCED_FEATURES_AVAILABLE and is_feature_enabled("enhanced_pipeline"):
                result = await integrated_email_processing(max_emails=50)
                print(f"[PERIODIC] Enhanced email sync: {result.get('new_processed', 0)} new emails")
            else:
                result = await sync_and_process_emails(max_emails=50)
                print(f"[PERIODIC] Legacy email sync: {result.get('new_processed', 0)} new emails")
                
        except Exception as e:
            print(f"[PERIODIC] Email sync failed: {e}")
        
        await asyncio.sleep(1800)  # 30 minutes'''
        
        if re.search(email_task_pattern, content, re.DOTALL):
            content = re.sub(email_task_pattern, enhanced_email_task, content, flags=re.DOTALL)
            self.upgrade_log.append("✅ Updated periodic email sync task")
        
        return content
    
    def _insert_before_main(self, content: str, new_content: str) -> str:
        """Insert content before the if __name__ == '__main__' block"""
        
        main_pattern = r"(if __name__ == ['\\\"]__main__['\\\"].*)"
        replacement = new_content + r"\\n\\1"
        
        if re.search(main_pattern, content):
            content = re.sub(main_pattern, replacement, content, flags=re.DOTALL)
        else:
            # If no main block, just append
            content += "\\n" + new_content
        
        return content
    
    def _create_config_files(self) -> None:
        """Create initial configuration files"""
        
        try:
            # Initialize enhanced configuration
            from enhanced_config import EnhancedConfig
            config = EnhancedConfig()
            config.save_config()
            self.upgrade_log.append("✅ Created enhanced configuration file")
            
        except ImportError:
            self.upgrade_log.append("⚠️ Could not create enhanced config (module not available)")
    
    def _restore_backup(self) -> None:
        """Restore from backup if upgrade fails"""
        if os.path.exists(self.backup_file):
            shutil.copy2(self.backup_file, self.app_file)
            print(f"🔄 Restored from backup: {self.backup_file}")
    
    def _print_upgrade_summary(self) -> None:
        """Print upgrade summary"""
        print("\\n📋 Upgrade Summary:")
        print("=" * 40)
        for log_entry in self.upgrade_log:
            print(f"  {log_entry}")
        
        print("\\n🎯 Next Steps:")
        print("  1. Restart Mission Control: python app.py")
        print("  2. Check enhanced status: GET /api/enhanced/status")
        print("  3. Configure features: GET /api/enhanced/config")
        print("  4. Test briefing: GET /api/briefing")
        
        print("\\n💡 New Features Available:")
        print("  - Enhanced email analysis with complexity scoring")
        print("  - Intelligent task extraction and priority matrix")  
        print("  - Smart workflow insights and recommendations")
        print("  - Improved contact intelligence and patterns")
        print("  - Configurable enhancement levels")

def main():
    """Run the upgrade"""
    upgrader = MissionControlUpgrader()
    
    print("Mission Control Enhancement Upgrade")
    print("=" * 40)
    print("This will upgrade your Mission Control to use enhanced features.")
    print("A backup will be created automatically.")
    print()
    
    confirmation = input("Proceed with upgrade? (y/N): ").strip().lower()
    if confirmation != 'y':
        print("Upgrade cancelled.")
        return
    
    success = upgrader.upgrade()
    
    if success:
        print("\\n🎉 Upgrade completed successfully!")
        print("\\nYou can now:")
        print("- Restart Mission Control to use enhanced features")
        print("- Check the status at /api/enhanced/status")
        print("- Configure features at /api/enhanced/config")
        
        if os.path.exists(upgrader.backup_file):
            keep_backup = input(f"\\nKeep backup file {upgrader.backup_file}? (Y/n): ").strip().lower()
            if keep_backup == 'n':
                os.remove(upgrader.backup_file)
                print("Backup file removed.")
    else:
        print("\\n❌ Upgrade failed. Original app.py has been restored.")

if __name__ == "__main__":
    main()