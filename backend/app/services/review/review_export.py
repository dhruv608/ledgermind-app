"""The Review tab's download: the review points of a job as a PDF report (to send or keep on file) or an Excel list,
all of them, the open ones only, or what the tab shows (one stage, one severity). The tax computation (CT-01) is not
a point and is left out."""

from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement
from backend.app.services.assistant.outputs import build_excel, build_pdf, safe_name

STAGES = {"STAGE_1_ACCOUNTING": "Accounts checks", "STAGE_2_VAT": "VAT", "STAGE_3_CT600": "Corporation tax"}
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
STATUS = {"OPEN": "Open", "CLEARED": "Cleared"}
SHOWING = {"all": "all points, open and cleared", "open": "open points only", "screen": "the points shown on screen"}


def _points(db: Session, eng: ClientEngagement, include: str, stage: str, severity: str) -> List[AuditFinding]:
    points = (db.query(AuditFinding).filter(AuditFinding.engagement_id == eng.id, AuditFinding.procedure_ref != "CT-01")
              .order_by(AuditFinding.id).all())
    sev = lambda f: (f.severity or "LOW").upper()
    if include == "open":
        points = [f for f in points if f.status == "OPEN"]
    elif include == "screen_open":   # the tab with Show cleared off: adjusted points still show
        points = [f for f in points if f.status != "CLEARED"]
    if include.startswith("screen"):
        if stage in STAGES:
            points = [f for f in points if (f.stage or "STAGE_1_ACCOUNTING") == stage]
        if severity == "HIGH":
            points = [f for f in points if sev(f) in ("HIGH", "CRITICAL")]
        elif severity in SEVERITIES:
            points = [f for f in points if sev(f) == severity]
    order = lambda f: (list(STAGES).index(f.stage) if f.stage in STAGES else 0, f.status != "OPEN",
                       SEVERITIES.index(sev(f)) if sev(f) in SEVERITIES else 3, f.id)
    return sorted(points, key=order)


def _status(f: AuditFinding) -> str:
    return STATUS.get(f.status or "OPEN", (f.status or "").title())


def review_export(db: Session, eng: ClientEngagement, fmt: str, include: str = "all", stage: str = "",
                  severity: str = "", made_by: str = "") -> Tuple[bytes, str, str]:
    """The file, its name and media type. include: all, open, screen (all shown) or screen_open."""
    points = _points(db, eng, include, stage, severity)
    made_by = made_by or "LedgerMind"
    showing = SHOWING["screen" if include.startswith("screen") else include if include in SHOWING else "all"]
    if include.startswith("screen") and (stage in STAGES or severity in SEVERITIES):
        showing += " (" + ", ".join(x for x in (STAGES.get(stage, ""), f"{severity.title()} severity" if severity in SEVERITIES else "") if x) + ")"
    year_end = eng.period_end_date
    name = safe_name(f"{eng.client_name} review points {year_end:%Y-%m-%d}" if year_end else f"{eng.client_name} review points", "Review points")

    if fmt == "xlsx":
        rows = [[STAGES.get(f.stage, "Accounts checks"), f.procedure_ref, f.procedure_name, (f.severity or "").title(),
                 f.source_row_ref or "", f.finding_title, f.finding_details, float(f.quantified_amount or 0), _status(f),
                 f"{f.cleared_at:%d/%m/%Y}" if f.cleared_at else "", f.cleared_note or ""] for f in points]
        sheet = {"name": "Review points", "rows": rows,
                 "columns": ["Stage", "Ref", "Check", "Severity", "Account or line", "Point", "Detail", "Amount",
                             "Status", "Cleared on", "Cleared note"]}
        data = build_excel(f"Review points: {showing}", [sheet], eng.client_name, year_end, made_by=made_by)
        return data, f"{name}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    # PDF: who and when, the counts by stage, then each stage's points (open first, the worst first)
    counts: Dict[str, Dict[str, int]] = {s: {"open": 0, "done": 0} for s in STAGES}
    for f in points:
        counts[f.stage if f.stage in STAGES else "STAGE_1_ACCOUNTING"]["open" if f.status == "OPEN" else "done"] += 1
    run = f"Review last run {eng.review_run_at:%d/%m/%Y %H:%M}." if eng.review_run_at else "The full review has not run yet."
    open_sev = {s: sum(1 for f in points if f.status == "OPEN" and (f.severity or "LOW").upper() == s) for s in SEVERITIES}
    sev_line = ", ".join(f"{n} {s.lower()}" for s, n in open_sev.items() if n) or "none"
    summary = {"heading": "Summary",
               "text": f"Prepared by {made_by}. {run}\nThis report shows {showing}: {len(points)} point(s). "
                       f"Open points by severity: {sev_line}.",
               "table": {"columns": ["Stage", "Open", "Cleared or adjusted", "Total"], "widths": [3, 1, 1.4, 1], "count_cols": [1, 2, 3],
                         "rows": [[label, str(c["open"]), str(c["done"]), str(c["open"] + c["done"])]
                                  for s, label in STAGES.items() for c in [counts[s]]]
                         + [["Total", str(sum(c["open"] for c in counts.values())),
                             str(sum(c["done"] for c in counts.values())), str(len(points))]]}}
    sections = [summary]
    for s, label in STAGES.items():
        mine = [f for f in points if (f.stage if f.stage in STAGES else "STAGE_1_ACCOUNTING") == s]
        if not mine:
            continue
        rows = []
        for f in mine:
            text = f"**{f.finding_title}**\n{f.finding_details}"
            if f.source_row_ref:
                text += f"\nAccount or line: {f.source_row_ref}"
            if f.status != "OPEN" and (f.cleared_note or f.cleared_at):
                when = f" {f.cleared_at:%d/%m/%Y}" if f.cleared_at else ""
                text += f"\n**{_status(f)}{when}:** {f.cleared_note or ''}"
            amount = float(f.quantified_amount or 0)
            rows.append([f"{f.procedure_ref}\n{f.procedure_name}", text, (f.severity or "").title(),
                         f"{amount:,.2f}" if amount else "-", _status(f)])
        sections.append({"heading": f"{label} ({len(mine)})",
                         "table": {"columns": ["Check", "Point", "Severity", "Amount", "Status"],
                                   "widths": [1.5, 5, 1, 1.1, 1.1], "rows": rows}})
    if not points:
        sections.append({"heading": "Points", "text": "No review points to show."})
    data = build_pdf("Review points", sections, eng.client_name, year_end, made_by=made_by)
    return data, f"{name}.pdf", "application/pdf"
