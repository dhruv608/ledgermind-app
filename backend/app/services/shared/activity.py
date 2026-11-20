"""When a client's data last changed, so the screens can say the review or the workbook is out of date."""
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement


def mark_changed(db: Session, engagement_id: str | None) -> None:
    """Record that something the review and the workbook read has changed (mappings, setup, journals, VAT, payroll),
    and check it again by itself: the checks start in the
    background, or a run already going runs once more when it ends, so several changes in a row are one more run."""
    if not engagement_id:
        return
    db.execute(update(ClientEngagement).where(ClientEngagement.id == engagement_id).values(data_changed_at=datetime.utcnow()))
    db.commit()
    recheck(db, engagement_id)


def recheck(db: Session, engagement_id: str) -> None:
    """Start the checks again after a change. Not for a change the checks make themselves (re-analysis inside a run:
    it would start itself for ever), and only for a job whose checks ran before (the upload starts the first run)."""
    import logging
    import threading
    if threading.current_thread().name.startswith("checks-"):
        return
    try:
        from backend.app.services.checks import runner
        if runner._latest(db, str(engagement_id)) is None:
            return
        eng = db.get(ClientEngagement, engagement_id)
        if eng is not None:
            runner.start_if_ready(db, eng, "change")
    except Exception:
        logging.getLogger(__name__).exception("Could not start the checks again for %s", engagement_id)


def iso(value: datetime | None) -> str | None:
    """Timestamps go to the browser as UTC ISO strings, so they can be compared and shown in local time."""
    return value.isoformat() + "Z" if value else None


def freshness(eng: ClientEngagement, has_tax_computation: bool, workpaper, mappings_to_review: int) -> dict:
    """Whether the review and the workbook still reflect the client's current data.

    The review is out of date when it never ran in full (no tax computation) or data changed after it ran. The workbook
    is out of date when data changed or the review ran after it was built, or it was built final while mappings still
    need review."""
    changed, reviewed = eng.data_changed_at, eng.review_run_at
    built = workpaper.generated_at if workpaper else None
    is_final = bool(workpaper) and not workpaper.filename.upper().endswith("_DRAFT.XLSX")
    review_stale = not reviewed or not has_tax_computation or bool(changed and changed > reviewed)
    workbook_stale = bool(workpaper) and (
        bool(built and changed and changed > built)
        or bool(built and reviewed and reviewed > built)
        or (is_final and mappings_to_review > 0)
    )
    moments = [m for m in (eng.created_at, changed, reviewed, built) if m]
    return {
        "data_changed_at": iso(changed),
        "review_run_at": iso(reviewed),
        "review_stale": review_stale,
        "workbook_stale": workbook_stale,
        "last_activity_at": iso(max(moments)) if moments else None,
    }
