"""Stateless triage decisioning ported from v1 ``briefing.py``.

Given an :class:`EmailTriage` row and a resolved contact tier, decide:

- ``decision``: should this surface in today's briefing?
- ``filter_reason``: short human label for *why* (used by the UI to
  group items, e.g. ``"partner contact"``, ``"newsletter"``).

The service is pure-function — it never touches the database. Callers
load the rows and pass them in. This keeps the briefing assembly easy to
unit-test without spinning up Redis or Postgres.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Decision sentinel values stored in ``EmailTriage.final_decision``.
DECISION_BRIEF = "decision"          # surface in decisions block
DECISION_DROP = "drop"               # filtered out (blocked sender, newsletter)
DECISION_REVIEW = "review"           # human review (not auto-decided)
DECISION_TASK = "task"               # already converted to kanban task


@dataclass(frozen=True)
class TriageVerdict:
    """Result of running the triage logic over an email row."""

    decision: str
    reason: str


def classify(
    *,
    contact_tier: str,
    from_address: Optional[str],
    subject: Optional[str] = None,
    filter_reason_hint: Optional[str] = None,
    converted_to_task: bool = False,
) -> TriageVerdict:
    """Produce a :class:`TriageVerdict` from already-loaded triage inputs.

    Args:
        contact_tier: Output of :func:`repositories.contact_repo.resolve_tier`
            (``"partner"`` / ``"blocked"`` / ``"unknown"``).
        from_address: Lowercased sender address.
        subject: Message subject (used for newsletter heuristics).
        filter_reason_hint: Pre-computed filter reason (Decapoda /
            v1 pipeline). When set and decisive (e.g. ``"newsletter"``,
            ``"blocked_domain"``), it short-circuits classification.
        converted_to_task: ``True`` if the email already has a task.
    """
    if converted_to_task:
        return TriageVerdict(DECISION_TASK, "converted to task")

    if contact_tier == "blocked":
        return TriageVerdict(DECISION_DROP, "blocked contact")

    if filter_reason_hint:
        if filter_reason_hint in {"blocked_domain", "blocked_pattern"}:
            return TriageVerdict(DECISION_DROP, "blocked sender")
        if filter_reason_hint in {"newsletter", "no_reply", "automated"}:
            return TriageVerdict(DECISION_DROP, filter_reason_hint)

    if subject and _looks_like_newsletter(subject, from_address):
        return TriageVerdict(DECISION_DROP, "newsletter heuristic")

    if contact_tier == "partner":
        return TriageVerdict(DECISION_BRIEF, "partner contact")

    return TriageVerdict(DECISION_REVIEW, "unknown sender — needs review")


def _looks_like_newsletter(subject: str, from_address: Optional[str]) -> bool:
    """Heuristic match for common newsletter / no-reply patterns."""
    subject_lc = subject.lower()
    if any(token in subject_lc for token in ("unsubscribe", "newsletter", "digest")):
        return True
    if from_address and any(
        token in from_address for token in ("no-reply", "noreply", "bounce", "mailer-daemon")
    ):
        return True
    return False
