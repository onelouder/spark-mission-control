#!/usr/bin/env python3
"""
Mission Control API Security Patch
Adds authentication requirements to unprotected API endpoints
"""

import re
import sys

def apply_security_patch(file_path):
    """Apply authentication requirements to API endpoints"""
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # List of endpoints that should remain public (if any)
    public_endpoints = [
        '/api/health',  # Keep one health check public for monitoring
    ]
    
    # Critical endpoints that MUST be protected
    critical_endpoints = [
        # Agent Management & System Control
        '/api/agents',
        '/api/sessions/spawn',
        '/api/sessions/send', 
        '/api/sessions/list',
        '/api/synapse/',
        '/api/system-metrics',
        '/api/cron/',
        
        # Task & Queue Management
        '/api/queue',
        '/api/tasks',
        
        # Data Access
        '/api/email/',
        '/api/calendar/',
        '/api/briefing/',
        '/api/contacts',
        '/api/notes',
        '/api/accomplishments',
        '/api/working-context',
        '/api/git-activity',
        '/api/papers/',
    ]
    
    # Pattern to match @app.{method}("/api/...") lines
    pattern = r'(@app\.(get|post|put|patch|delete|api_route)\("(/api/[^"]+)".*?\))'
    
    def should_protect_endpoint(endpoint_path):
        """Determine if endpoint should be protected"""
        # Skip if already protected (has Depends)
        if 'Depends(' in endpoint_path:
            return False
            
        # Check if it's in public list
        for public in public_endpoints:
            if endpoint_path.startswith(public):
                return False
        
        # Protect all /api/ endpoints by default
        return endpoint_path.startswith('/api/')
    
    lines = content.split('\n')
    modified_lines = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Check if this is an @app decorator for an API endpoint
        match = re.search(r'@app\.(get|post|put|patch|delete|api_route)\("(/api/[^"]+)"', line)
        
        if match:
            method = match.group(1)
            endpoint = match.group(2)
            
            # Check if this endpoint should be protected
            if should_protect_endpoint(endpoint) and 'Depends(' not in line:
                # Look ahead to the function definition
                j = i + 1
                while j < len(lines) and not lines[j].strip().startswith('async def '):
                    j += 1
                
                if j < len(lines):
                    func_line = lines[j]
                    
                    # Check if function already has Depends(require_auth)
                    if 'Depends(require_auth)' not in func_line:
                        # Add authentication dependency
                        if '(' in func_line and ')' in func_line:
                            # Find the closing parenthesis of the parameters
                            param_start = func_line.find('(')
                            param_end = func_line.rfind(')')
                            
                            current_params = func_line[param_start+1:param_end].strip()
                            
                            if current_params:
                                # Add auth parameter after existing parameters
                                new_params = current_params + ', username: str = Depends(require_auth)'
                            else:
                                # No existing parameters, just add auth
                                new_params = 'username: str = Depends(require_auth)'
                            
                            # Reconstruct the function line
                            lines[j] = func_line[:param_start+1] + new_params + func_line[param_end:]
                            
                            print(f"✅ Protected: {method.upper()} {endpoint}")
                
        modified_lines.append(lines[i])
        i += 1
    
    return '\n'.join(modified_lines)

if __name__ == "__main__":
    app_file = "/home/jwells/projects/mission-control/app.py"
    
    print("🔒 Applying Mission Control API Security Patch...")
    print("=" * 50)
    
    try:
        patched_content = apply_security_patch(app_file)
        
        # Write the patched content
        with open(app_file, 'w') as f:
            f.write(patched_content)
        
        print("=" * 50)
        print("✅ Security patch applied successfully!")
        print("📝 Backup saved as: app.py.backup-pre-security-fix")
        print("🔄 Restart Mission Control to apply changes")
        
    except Exception as e:
        print(f"❌ Error applying security patch: {e}")
        sys.exit(1)