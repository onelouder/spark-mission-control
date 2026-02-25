// Minimal briefing debug script
console.log('DEBUG: Script loaded');

document.addEventListener('DOMContentLoaded', async function() {
    console.log('DEBUG: DOM loaded');
    
    try {
        // Hide loading, show error initially
        const loadingEl = document.getElementById('loading-state');
        const errorEl = document.getElementById('error-state');
        const containerEl = document.getElementById('briefing-container');
        
        console.log('DEBUG: Elements found:', {
            loading: !!loadingEl,
            error: !!errorEl, 
            container: !!containerEl
        });
        
        if (loadingEl) loadingEl.classList.add('hidden');
        if (errorEl) {
            errorEl.classList.remove('hidden');
            errorEl.innerHTML = '<p>Loading briefing data...</p>';
        }
        
        // Try API call
        console.log('DEBUG: Making API call');
        const response = await fetch('/api/briefing');
        console.log('DEBUG: API response status:', response.status);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        console.log('DEBUG: Data received:', !!data);
        
        // Show success
        if (errorEl) errorEl.classList.add('hidden');
        if (containerEl) {
            containerEl.classList.remove('hidden');
            containerEl.innerHTML = '<div style="padding: 20px;">Briefing data loaded successfully! Found ' + (data.blocks ? Object.keys(data.blocks).length : 0) + ' blocks.</div>';
        }
        
        console.log('DEBUG: Success!');
        
    } catch (err) {
        console.error('DEBUG: Error:', err);
        const errorEl = document.getElementById('error-state');
        if (errorEl) {
            errorEl.classList.remove('hidden');
            errorEl.innerHTML = '<p>Error: ' + err.message + '</p>';
        }
    }
});