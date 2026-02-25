# Ideas: White Paper & Research Assistant

**Date:** 2026-01-29  
**Status:** Concept for Jason's review

---

## The Challenge

Jason maintains a substantial collection of white papers and technical documents across multiple domains:

**Work (Novvi):**
- Single-phase immersion cooling (60+ documents)
- EV Drive Fluids (6+ documents)
- Phase Change Materials (25+ documents)
- mPAO products, biobased chemicals, hydraulic fluids

**Research Interests:**
- Physics (toroidal EM waves, fusion, quantum spacetime)
- Financial/Economic analysis
- History and Philosophy
- Robotics and AI
- Quantum computing

**Pain Points:**
1. Keeping papers current with latest research and industry developments
2. Tracking which papers need revision and why
3. Maintaining consistency across related documents
4. Finding time for literature reviews
5. Remembering where specific information lives across 100+ documents

---

## Concept: Research Radar

A background system that monitors your key domains and surfaces relevant updates.

### How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  🔬 RESEARCH RADAR                                     Weekly   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  IMMERSION COOLING                                              │
│  ├─ 🆕 NVIDIA announces Blackwell Ultra cooling specs (Jan 27) │
│  │     → May affect: GPU TDP analysis, Thermal Resistance doc  │
│  ├─ 📄 New OCP paper on single-phase standards (Jan 24)        │
│  │     → May affect: Technical Landscape v12                    │
│  └─ 📊 GigaOm analyst report on DC cooling trends              │
│                                                                 │
│  EV DRIVE FLUIDS                                                │
│  ├─ 🚗 BYD announces new thermal management system             │
│  └─ 📈 Q4 EV sales data released (update market trends?)       │
│                                                                 │
│  PHASE CHANGE MATERIALS                                         │
│  └─ 🏢 ASHRAE publishes building envelope PCM guidelines       │
│                                                                 │
│  [Dismiss] [Save for later] [Update paper] [Add to reading]    │
└─────────────────────────────────────────────────────────────────┘
```

### Features

1. **Domain Watch Lists**
   - Configure keywords, companies, journals to monitor
   - Arxiv, Google Scholar, industry news, patent filings
   - Runs weekly/daily via cron job

2. **Paper Health Dashboard**
   - Last updated date for each paper
   - "Staleness" score based on how much the field has changed
   - Suggested revisions based on new developments

3. **Cross-Reference Map**
   - Which papers cite the same sources?
   - If you update one, which others might need updates?
   - Visualize document relationships

4. **Quick Revision Mode**
   - "Here's what changed since your last draft"
   - Suggested text updates with citations
   - Side-by-side diff view

---

## Concept: Paper Index & Search

A local search engine for your white papers.

### Implementation

```python
# Index all documents
papers/
  index.json          # Metadata: title, date, topics, status
  embeddings.npy      # Vector embeddings for semantic search
  full_text/          # Extracted text from PDFs/DOCX

# Search API
GET /api/papers/search?q=thermal+resistance+immersion
→ Returns ranked results across all your papers

# "Where did I write about X?"
GET /api/papers/search?q=NVIDIA+Blackwell+TDP
→ "Found in: GPU TDP and Immersion Cooling.docx (page 4)"
```

### Features

1. **Natural Language Search**
   - "Find everything I've written about water usage in data centers"
   - Returns snippets with page numbers

2. **Similar Content Detection**
   - "This paragraph appears in 3 other documents"
   - Helps maintain consistency

3. **Citation Tracker**
   - Which external sources do you cite most?
   - Are any citations outdated?

---

## Concept: Revision Assistant

AI-powered help for keeping papers current.

### Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│  📝 REVISION ASSISTANT                                          │
│  Paper: Data Center Immersion Cooling - Tech Landscape v12      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Last updated: 2025-10-22 (98 days ago)                        │
│                                                                 │
│  SUGGESTED UPDATES:                                             │
│                                                                 │
│  1. Section 3.2: GPU Power Roadmap                              │
│     Current: "Blackwell expected at 1000W TDP"                  │
│     Update: NVIDIA confirmed 1200W for Blackwell Ultra          │
│     Source: NVIDIA GTC 2026 keynote (Jan 15)                    │
│     [Apply] [Modify] [Skip]                                     │
│                                                                 │
│  2. Section 5.1: Market Size                                    │
│     Current: "$2.3B by 2028"                                    │
│     Update: New Gartner report estimates $3.1B                  │
│     Source: Gartner DC Infrastructure Report Q1 2026            │
│     [Apply] [Modify] [Skip]                                     │
│                                                                 │
│  3. Section 7: Competitive Landscape                            │
│     Note: 3M announced exit from fluorinated fluids             │
│     Suggest: Add paragraph on market implications               │
│     [Draft paragraph] [Skip]                                    │
│                                                                 │
│  [Generate full revision] [Export change log] [Schedule review] │
└─────────────────────────────────────────────────────────────────┘
```

---

## Concept: Reading Queue & Digest

Manage papers you want to read and get summaries.

### Features

1. **Reading Queue**
   - Save papers/articles to read later
   - Prioritize by relevance to active projects
   - "You have 3 papers in queue related to immersion cooling"

2. **Weekly Digest**
   - AI-summarized highlights from your queue
   - "Here's what matters from the 12 papers you saved this week"
   - Key takeaways, not full papers

3. **Citation Generator**
   - "Add this to my PCM paper"
   - Auto-generates citation in your preferred format
   - Extracts relevant quotes

---

## Integration with Mission Control

### Briefing Block: Research Updates

```
┌─────────────────────────────────────────────────────────────────┐
│  📚 RESEARCH RADAR                                   [expand]   │
├─────────────────────────────────────────────────────────────────┤
│  3 papers may need updates based on recent developments         │
│  5 new items in your reading queue                              │
│  Next scheduled review: Immersion Cooling v12 (Feb 5)           │
└─────────────────────────────────────────────────────────────────┘
```

### Context Integration

- Research Radar respects context filters
- "Novvi mode" shows only work-related paper updates
- Personal mode shows physics, philosophy, etc.

---

## Technical Implementation

### Phase 1: Paper Index
1. Extract text from all PDFs/DOCX in white_papers/
2. Build searchable index with metadata
3. Add search endpoint to Mission Control

### Phase 2: Research Radar
1. Configure watch lists per domain
2. Cron job for periodic news/paper scanning
3. Match new content to your existing papers

### Phase 3: Revision Assistant
1. Track last-modified dates
2. Diff engine for suggesting updates
3. AI drafting for new paragraphs

---

## Domain-Specific Watch Lists

### Immersion Cooling
**Keywords:** single-phase immersion, dielectric coolant, data center cooling, liquid cooling, PUE, thermal management
**Companies:** NVIDIA, Intel, AMD, Microsoft Azure, Google, Iceotope, GRC, LiquidCool, Asetek
**Journals:** IEEE Transactions on Components, ASHRAE Journal, Data Center Dynamics
**Events:** OCP Summit, NVIDIA GTC, Supercomputing Conference

### EV Drive Fluids
**Keywords:** EV thermal management, e-axle fluid, transmission fluid, electric vehicle lubricant
**Companies:** Tesla, BYD, Rivian, Lucid, Afton Chemical, Lubrizol
**Journals:** SAE International, Tribology Transactions

### Phase Change Materials
**Keywords:** PCM, thermal energy storage, building envelope, latent heat
**Companies:** Phase Change Energy Solutions, Microtek, Entropy Solutions
**Journals:** Applied Energy, Energy and Buildings, Solar Energy Materials

---

## Questions for Jason

1. Which papers are highest priority for staying current?
2. How often do you typically revise papers? (monthly? quarterly?)
3. What sources do you trust most for industry updates?
4. Would you want email/Telegram alerts for major developments?
5. Should this integrate with your Obsidian vault or stay separate?

---

*The goal: Never be surprised by "I wish I'd known about X before that meeting."*
