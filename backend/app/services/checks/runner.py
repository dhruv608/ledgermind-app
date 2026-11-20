"""The client's checks run by themselves in the background: once the setup is
complete, after a save of the setup or a new upload, or when the accountant asks. Each run is a row in check_runs
with the step it is on, so the screen can show the progress from any server worker. The checks are the review's own
(services/review/review_engine); nothing is posted: journals stay proposals for the accountant."""

import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.core.database import SessionLocal
from backend.app.models.check_runs import CheckRun
from backend.app.services.checks import progress

log = logging.getLogger(__name__)

# The areas in the order the review works through them (the review calls progress.step with each key)
STEPS: List[Tuple[str, str]] = [
    ("books", "Trial balance and ledger"),
    ("opening", "Opening balances"),
    ("general", "General and FRS 102 checks"),
    ("cis", "CIS and subcontractors"),
    ("dla", "Director's loan"),
    ("industry", "Industry questions"),
    ("fixed_assets", "Fixed assets and depreciation"),
    ("stock", "Stock"),
    ("accruals", "Accruals and prepayments"),
    ("payroll", "Payroll and net wages"),
    ("loans", "Loans"),
    ("vat", "VAT"),
    ("ct", "Corporation tax"),
    ("save", "Saving the results"),
]
_INDEX = {key: i for i, (key, _) in enumerate(STEPS)}

# The step a point belongs to, by its reference (the families the screen's areas use); the rest are general checks
STEP_REFS: List[Tuple[str, "re.Pattern"]] = [
    ("opening", re.compile(r"^(U-OB|E-004)")),
    ("books", re.compile(r"^(U-TB|TB-)")),
    ("cis", re.compile(r"^(CIS|U-SUB)")),
    ("dla", re.compile(r"^(U-DLA|DL-|U-DIV|U-EQ|RP-)")),
    ("fixed_assets", re.compile(r"^(U-FA|C1|FRS-FA|FRS-IN|G1$)")),
    ("stock", re.compile(r"^(U-STK|YE-03)")),
    ("accruals", re.compile(r"^(U-ACC|U-PRE|U-ADJ|G2$|G3$|YE-0[12])")),
    ("payroll", re.compile(r"^(U-PAY|PY-|U-EA)")),
    ("loans", re.compile(r"^(U-LOAN|U-LSE)")),
    ("vat", re.compile(r"^(V-|VT-)")),
    ("ct", re.compile(r"^(CT-|U-CT)")),
]


def step_of(ref: str) -> str:
    return next((key for key, pattern in STEP_REFS if pattern.search(ref or "")), "general")


def step_results(db: Session, engagement_id: str) -> Dict[str, Dict[str, Any]]:
    """What each step left for the accountant: open points, and journals proposed (their total), by step."""
    from backend.app.models.database import AuditFinding, ProposedJournal
    out: Dict[str, Dict[str, Any]] = {}
    refs = {}
    for f in db.query(AuditFinding).filter(AuditFinding.engagement_id == engagement_id).all():
        refs[f.id] = f.procedure_ref
        if f.status == "OPEN" and f.procedure_ref != "CT-01":
            r = out.setdefault(step_of(f.procedure_ref), {"points": 0, "journals": 0, "amount": 0.0})
            r["points"] += 1
    for j in db.query(ProposedJournal).filter(ProposedJournal.engagement_id == engagement_id,
                                              ProposedJournal.status == "PROPOSED").all():
        key = step_of(refs.get(j.finding_id, "")) if j.finding_id else ("ct" if j.stage == "STAGE_3_CT600" else
                                                                        "vat" if j.stage == "STAGE_2_VAT" else "general")
        r = out.setdefault(key, {"points": 0, "journals": 0, "amount": 0.0})
        r["journals"] += 1
        r["amount"] = round(r["amount"] + float(j.amount or 0), 2)
    return out

# A run still marked running after this long stopped with its server (a restart or a deploy)
STALE_AFTER = timedelta(minutes=20)


def _view(run: Optional[CheckRun]) -> Dict[str, Any]:
    if run is None:
        return {"status": "NONE", "steps": [label for _, label in STEPS]}
    status = run.status
    if status == "RUNNING" and run.started_at and datetime.utcnow() - run.started_at > STALE_AFTER:
        status = "FAILED"
    return {
        "id": run.id,
        "status": status,
        "trigger": run.trigger,
        "step": run.step,
        "step_label": dict(STEPS).get(run.step or "", ""),
        "steps_done": run.steps_done or 0,
        "steps_total": len(STEPS),
        "steps": [label for _, label in STEPS],
        "summary": json.loads(run.summary) if run.summary else None,
        "error": run.error if status == "FAILED" else None,
        "started_at": run.started_at.isoformat() + "Z" if run.started_at else None,
        "finished_at": run.finished_at.isoformat() + "Z" if run.finished_at else None,
    }


def _latest(db: Session, engagement_id: str) -> Optional[CheckRun]:
    return (db.query(CheckRun).filter(CheckRun.engagement_id == engagement_id)
            .order_by(CheckRun.id.desc()).first())


def latest(db: Session, engagement_id: str) -> Dict[str, Any]:
    out = _view(_latest(db, engagement_id))
    out["history"] = [{"id": r.id, "status": _view(r)["status"], "trigger": r.trigger,
                       "started_at": r.started_at.isoformat() + "Z" if r.started_at else None,
                       "seconds": (json.loads(r.summary).get("seconds") if r.summary else None)}
                      for r in db.query(CheckRun).filter(CheckRun.engagement_id == engagement_id)
                      .order_by(CheckRun.id.desc()).limit(6)]
    out["step_keys"] = [key for key, _ in STEPS]
    return out


def setup_gaps(db: Session, engagement) -> List[str]:
    from backend.app.services.setup.engagement_setup import setup_status
    from backend.app.services.setup.profile_service import ProfileService
    return setup_status(engagement, ProfileService.get_or_create_profile(db, str(engagement.id)), db)["gaps"]


def start(db: Session, engagement, trigger: str, user_id: Optional[int] = None) -> Dict[str, Any]:
    """Start the checks unless the setup still has gaps (they wait for it). While a run is going, it is marked to run
    again when it finishes, so the change just made is checked too."""
    gaps = setup_gaps(db, engagement)
    if gaps:
        return {**latest(db, str(engagement.id)), "waiting_for_setup": gaps}
    run = _latest(db, str(engagement.id))
    if run is not None and _view(run)["status"] == "RUNNING":
        run.rerun = True
        db.commit()
        return _view(run)
    if run is not None and run.status == "RUNNING":       # stale: it stopped with its server
        run.status, run.error, run.finished_at = "FAILED", "Stopped with the server", datetime.utcnow()
    run = CheckRun(engagement_id=str(engagement.id), status="RUNNING", trigger=trigger, step=STEPS[0][0],
                   steps_done=0, started_by=user_id)
    db.add(run)
    db.commit()
    threading.Thread(target=_run, args=(run.id, str(engagement.id)), daemon=True,
                     name=f"checks-{engagement.id}").start()
    return _view(run)


def start_if_ready(db: Session, engagement, trigger: str, user_id: Optional[int] = None) -> None:
    """After a setup save or an upload: start the checks when the setup is complete; never fails the caller."""
    try:
        start(db, engagement, trigger, user_id)
    except Exception:
        log.exception("Could not start the checks for %s", engagement.id)


def _save_step(run_id: int, key: str, began: float) -> None:
    # Its own session: the review's session is not committed half way. The time each step started is kept in the
    # summary, so the screen can show how long each took
    db = SessionLocal()
    try:
        run = db.get(CheckRun, run_id)
        if run is not None:
            run.step = key
            run.steps_done = _INDEX.get(key, run.steps_done or 0)
            summary = json.loads(run.summary) if run.summary else {}
            summary.setdefault("started", {})[key] = round(time.monotonic() - began, 1)
            run.summary = json.dumps(summary)
            db.commit()
    except Exception:
        log.warning("Could not save the checks' step %s", key, exc_info=True)
    finally:
        db.close()


def _run(run_id: int, engagement_id: str) -> None:
    from backend.app.services.review.review_engine import SequentialReviewEngine
    while True:
        began = time.monotonic()
        token = progress.watching(lambda key: _save_step(run_id, key, began))
        db = SessionLocal()
        try:
            result = SequentialReviewEngine.run_full_sequential_review(engagement_id, db)
            run = db.get(CheckRun, run_id)
            again = bool(run.rerun)
            run.status, run.step, run.steps_done = "DONE", None, len(STEPS)
            run.finished_at = datetime.utcnow()
            summary = json.loads(run.summary) if run.summary else {}
            summary.update({"points": result["total_findings"], "journals": result["total_journals"],
                            "seconds": round(time.monotonic() - began), "results": step_results(db, engagement_id)})
            run.summary = json.dumps(summary)
            db.commit()
        except Exception as e:
            log.exception("The checks failed for %s", engagement_id)
            db.rollback()
            run = db.get(CheckRun, run_id)
            again = False
            if run is not None:
                run.status, run.error, run.finished_at = "FAILED", str(e)[:1000], datetime.utcnow()
                db.commit()
        finally:
            progress.done_watching(token)
            db.close()
        if not again:
            return
        # The books or setup changed while it ran: a new run checks them
        db = SessionLocal()
        try:
            new = CheckRun(engagement_id=engagement_id, status="RUNNING", trigger="change", step=STEPS[0][0],
                           steps_done=0)
            db.add(new)
            db.commit()
            run_id = new.id
        finally:
            db.close()
