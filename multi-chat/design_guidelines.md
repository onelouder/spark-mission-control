# Whitepaper Research Library - Design Guidelines

## Design Approach
**Reference-Based:** Technical productivity application inspired by Linear's precision, Notion's organization, and modern code editors (VS Code, Sublime). Dark-first interface optimized for extended research sessions.

## Core Design Elements

### Typography
- **System Font Stack:** system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif
- **Monospace:** ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace (for code, data, version IDs)
- **Base Size:** 11px (compact, information-dense)
- **Line Height:** 1.4 (tight, efficient)
- **Sizes:** Headers 18px→15px→13px→12px, Body 12px, UI elements 11px, Labels 10px, Metadata 9px

### Color System (Dark Theme)
```
Backgrounds:
--bg0: #0b0f14 (deepest, main canvas)
--bg1: #0f1620 (panels, containers)
--bg2: #131c28 (elevated elements)
--bg3: #1a2433 (hover states)

Borders:
--border0: rgba(255,255,255,0.06) (subtle dividers)
--border1: rgba(255,255,255,0.10) (panel borders)
--border2: rgba(255,255,255,0.15) (emphasized borders)

Text:
--text0: rgba(255,255,255,0.90) (primary)
--text1: rgba(255,255,255,0.65) (secondary)
--text2: rgba(255,255,255,0.45) (tertiary)
--text3: rgba(255,255,255,0.30) (disabled)

Semantic:
--accent: #4ea1ff (primary actions, selections)
--success: #35d07f (complete, active)
--warning: #f0b429 (processing, alerts)
--danger: #ff5c5c (errors, deletions)
--info: #6ea8ff (informational)
--purple: #a78bfa (planning stage)
--google-blue: #4285f4 (Gemini branding)
```

### Layout System
**Spacing:** Consistent 2px/4px/6px/8px/10px/12px/14px/16px/20px/24px units
- Micro gaps: 2px-6px
- Component padding: 8px-12px
- Section spacing: 16px-24px

**Structure:**
- Fixed header: 32px height
- Left sidebar: 240px fixed width
- Right panel: 340px fixed width
- Center: Flexible content area
- All panels use flexbox column layout

### Component Library

**Navigation & Panels:**
- Tree items: 24px height, hover background transition 75ms
- Panel headers: 28px with 10px uppercase labels (letter-spacing: 2px)
- Folder icons with chevrons for expand/collapse
- Selected state: accent-dim background + text0 color

**Buttons & Controls:**
- Icon buttons: 24px×24px, 14px icons, subtle hover states
- Primary actions: 26px height, accent-dim background, uppercase labels
- Dropdowns: 24px height, bg2 background, border1 borders
- All transitions: 75ms ease

**Editor Components:**
- Line numbers: 44px fixed width, right-aligned
- Tabs: 30px height with active state styling
- View toggle: Segmented control with 2px border-radius
- Footer status bar: 24px with monospace metrics

**Status Indicators:**
- Status dots: 6px circles with pulse animation for active states
- Color-coded by stage (research: info, errata: warning, drafting: accent)
- Badges: 9px text, 2px border-radius, semantic color backgrounds

**Forms & Inputs:**
- Consistent 1px borders with border1 color
- 2px border-radius (subtle rounding)
- Focus states increase border opacity
- Monospace for technical inputs

### Markdown Rendering
- H1: 18px with bottom border
- H2: 15px with generous top margin
- H3: 13px 
- Body: 12px, line-height 1.7
- Code inline: bg2 background, accent text, 10px monospace
- Code blocks: bg0 background, border0 border, 14px padding
- Tables: Full width, alternating row backgrounds

### Animations
**Minimal and Purposeful:**
- Pulse: 1.5s for active pipeline stages
- Spin: 1s linear for loading states
- Hover transitions: 75ms
- No scroll-triggered or decorative animations

### Component States
- Default: Standard styling
- Hover: bg3 background or increased border opacity
- Active/Selected: accent-dim background + accent color
- Disabled: 60% opacity + no pointer events
- Running: warning color scheme

### Scrollbars
- Width: 6px
- Track: bg1
- Thumb: #1e293b with 3px border-radius
- Minimal, matches VS Code aesthetic

## Key UX Patterns
- Single-click selection in tree
- Real-time WebSocket updates for pipeline progress
- Toggle between rendered/source views in editor
- Persistent header with global status
- Collapsible panels (future enhancement)
- No color references for now - focus on structure and hierarchy