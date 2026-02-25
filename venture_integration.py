"""
X-Cognis Venture Engine Integration for Mission Control
Add venture routes and templates to the existing Mission Control app.
"""

import sys
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# Add venture engine src to path
VENTURE_ENGINE_PATH = Path("/home/jwells/projects/_xcognis_venture_engine")
sys.path.insert(0, str(VENTURE_ENGINE_PATH / "src"))

# Import venture API functions
import venture_api as api

# Templates for venture pages
venture_templates = Jinja2Templates(directory=str(VENTURE_ENGINE_PATH / "templates"))

# Create router for venture endpoints
router = APIRouter(tags=["venture"])


# ============================================
# HTML Pages
# ============================================

@router.get("/venture", response_class=HTMLResponse)
async def venture_dashboard(request: Request):
    """X-Cognis Venture Engine dashboard."""
    return venture_templates.TemplateResponse("venture.html", {"request": request})


# ============================================
# API Endpoints
# ============================================

@router.get("/api/venture/state")
async def get_state():
    """Get current venture state."""
    return api.get_venture_state()


@router.post("/api/venture/ventures")
async def create_venture(
    name: str,
    slug: str,
    thesis: str,
    stage: str = "THESIS",
    max_days: int = 14,
    contacts_required: int = 3,
    capital_budget: int = 15000,
    status: str = "active"
):
    """Create a new venture."""
    venture_id = api.create_venture(
        name=name,
        slug=slug,
        thesis=thesis,
        stage=stage,
        max_days=max_days,
        contacts_required=contacts_required,
        capital_budget=capital_budget,
        status=status
    )
    return {"id": venture_id, "status": "created"}


@router.post("/api/venture/ventures/{venture_id}/advance")
async def advance_venture(
    venture_id: str,
    to_stage: str,
    evidence: str,  # JSON string
    approved_by: str,
    new_max_days: int = None,
    new_capital_budget: int = None
):
    """Advance venture to next stage."""
    import json
    evidence_list = json.loads(evidence) if evidence else []
    decision_id = api.advance_venture(
        venture_id=venture_id,
        to_stage=to_stage,
        evidence=evidence_list,
        approved_by=approved_by,
        new_max_days=new_max_days,
        new_capital_budget=new_capital_budget
    )
    return {"decision_id": decision_id, "status": "advanced"}


@router.post("/api/venture/ventures/{venture_id}/kill")
async def kill_venture(venture_id: str, reason: str, approved_by: str):
    """Kill a venture."""
    decision_id = api.kill_venture(venture_id, reason, approved_by)
    return {"decision_id": decision_id, "status": "killed"}


@router.get("/api/venture/health")
async def get_health(venture_id: str = None):
    """Get venture health status."""
    return api.get_venture_health(venture_id)


@router.get("/api/venture/forcing")
async def check_forcing():
    """Check forcing functions."""
    return api.check_forcing_functions()


# Pipeline
@router.get("/api/venture/pipeline")
async def get_pipeline(venture_id: str = None):
    """Get pipeline by stage."""
    return api.get_pipeline(venture_id)


@router.post("/api/venture/pipeline")
async def add_to_pipeline(venture_id: str, contact_id: str, stage: str = "target"):
    """Add contact to pipeline."""
    pipeline_id = api.add_to_pipeline(venture_id, contact_id, stage)
    return {"id": pipeline_id}


@router.patch("/api/venture/pipeline/{pipeline_id}")
async def update_pipeline(
    pipeline_id: str,
    stage: str,
    notes: str = None,
    next_action: str = None,
    next_action_date: str = None
):
    """Update pipeline stage."""
    api.update_pipeline_stage(pipeline_id, stage, notes, next_action, next_action_date)
    return {"status": "updated"}


@router.get("/api/venture/pipeline/stale")
async def get_stale_leads(days: int = 7):
    """Get stale leads."""
    return api.get_stale_leads(days)


# Contacts
@router.get("/api/venture/contacts")
async def get_contacts(venture_id: str = None):
    """Get contacts."""
    return api.get_contacts(venture_id)


@router.post("/api/venture/contacts")
async def create_contact(
    name: str,
    company: str = None,
    role: str = None,
    email: str = None,
    linkedin: str = None,
    contact_type: str = "other",
    notes: str = None
):
    """Create contact."""
    contact_id = api.create_contact(name, company, role, email, linkedin, contact_type, notes)
    return {"id": contact_id}


# Outreach
@router.get("/api/venture/outreach")
async def get_outreach(status: str = None):
    """Get outreach queue."""
    return api.get_outreach_queue(status)


@router.post("/api/venture/outreach")
async def create_outreach(
    venture_id: str,
    contact_id: str,
    channel: str,
    body: str,
    subject: str = None,
    generated_by: str = "ximena"
):
    """Create outreach draft."""
    outreach_id = api.create_outreach(venture_id, contact_id, channel, subject, body, generated_by)
    return {"id": outreach_id, "status": "draft"}


@router.post("/api/venture/outreach/{outreach_id}/approve")
async def approve_outreach(outreach_id: str, approved_by: str):
    """Approve outreach."""
    api.approve_outreach(outreach_id, approved_by)
    return {"status": "approved"}


@router.post("/api/venture/outreach/{outreach_id}/send")
async def send_outreach(outreach_id: str):
    """Mark outreach as sent."""
    api.mark_outreach_sent(outreach_id)
    return {"status": "sent"}


# Signals
@router.get("/api/venture/signals")
async def get_signals(status: str = None):
    """Get signals."""
    return api.get_signals(status)


@router.post("/api/venture/signals")
async def create_signal(
    title: str,
    source: str,
    summary: str,
    domain: str,
    displacement_test: str,
    rps_score: int,
    source_url: str = None
):
    """Create signal."""
    signal_id = api.create_signal(title, source, summary, domain, displacement_test, rps_score, source_url)
    return {"id": signal_id}


@router.post("/api/venture/signals/{signal_id}/review")
async def review_signal(signal_id: str, action: str):
    """Review signal."""
    api.review_signal(signal_id, action)
    return {"status": action}


# Metrics
@router.get("/api/venture/metrics")
async def get_metrics(venture_id: str = None, days: int = 30):
    """Get metrics."""
    return api.get_metrics(venture_id, days)


def register_venture_routes(app):
    """Register venture routes with the main FastAPI app."""
    app.include_router(router)
    print("[STARTUP] X-Cognis Venture Engine routes registered at /venture and /api/venture/*")
