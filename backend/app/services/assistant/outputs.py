"""What the assistant can make when asked: an Excel file (openpyxl, as the workbook), a PDF note (reportlab) or a
chart drawn in the panel. The model passes the rows it got from the read tools; the file is built here, saved with
the chat and offered as a download card. A chart is only checked and handed to the panel, which draws it."""

import io
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.chat import ChatFile, ChatSession

MAX_ROWS = 2000
TEAL = "0F766E"
MONEY = '#,##0.00;(#,##0.00);"-"'


def _number(v: Any) -> Any:
    """'12,400.00', '£1,234' or '(500.00)' as a number; other text as it is."""
    if isinstance(v, (int, float)) or v is None:
        return v
    text = str(v).strip()
    m = re.fullmatch(r"(-)?\(?£?\s*(-)?([\d,]+(?:\.\d+)?)\)?", text)
    if not m or not re.search(r"\d", text):
        return text
    n = float(m.group(3).replace(",", ""))
    return -n if (m.group(1) or m.group(2) or (text.startswith("(") and text.endswith(")"))) else n


def safe_name(text: str, default: str) -> str:
    name = re.sub(r"[^A-Za-z0-9 &()\-_.,]+", "", text or "").strip()[:80]
    return name or default


def _table(t: Any) -> Tuple[List[str], List[List[Any]]]:
    if not isinstance(t, dict):
        return [], []
    cols = [str(c) for c in (t.get("columns") or [])][:30]
    rows = [r if isinstance(r, list) else [r] for r in (t.get("rows") or [])][:MAX_ROWS]
    return cols, rows


# ----------------------------------------------------------------------------------------------------- Excel

def build_excel(title: str, sheets: List[Dict[str, Any]], client: str, year_end: Optional[date],
                made_by: str = "LedgerMind Assistant") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    used = set()
    for n, sheet in enumerate(sheets[:10] or [{}]):
        name = re.sub(r"[\[\]:*?/\\]", "", str(sheet.get("name") or f"Sheet{n + 1}"))[:31] or f"Sheet{n + 1}"
        while name in used:
            name = f"{name[:28]}_{n}"
        used.add(name)
        ws = wb.create_sheet(name)
        cols, rows = _table(sheet)
        ws["A1"] = title
        ws["A1"].font = Font(bold=True, size=13, color=TEAL)
        ws["A2"] = " · ".join(x for x in (client, f"Year end {year_end:%d/%m/%Y}" if year_end else "",
                                          f"Made {date.today():%d/%m/%Y} by {made_by}") if x)
        ws["A2"].font = Font(size=9, color="64748B")
        head = 4
        thin = Side(style="thin", color="CBD5E1")
        for j, c in enumerate(cols, start=1):
            cell = ws.cell(row=head, column=j, value=c)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor=TEAL)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        widths = [len(str(c)) for c in cols]
        for i, r in enumerate(rows, start=head + 1):
            total = bool(r) and str(r[0]).strip().lower() in ("total", "totals", "grand total")
            for j, v in enumerate(r[:max(len(cols), 1)], start=1):
                value = _number(v)
                cell = ws.cell(row=i, column=j, value=value)
                if isinstance(value, (int, float)):
                    cell.number_format = MONEY
                if total:
                    cell.font = Font(bold=True)
                    cell.border = Border(top=thin, bottom=Side(style="double", color="0F172A"))
                if j - 1 < len(widths):
                    widths[j - 1] = max(widths[j - 1], len(f"{value:,.2f}" if isinstance(value, (int, float)) else str(value)))
                else:
                    widths.append(len(str(value)))
        for j, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(j)].width = min(max(w + 2, 10), 60)
        ws.freeze_panes = ws.cell(row=head + 1, column=1)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ------------------------------------------------------------------------------------------------------- PDF

def build_pdf(title: str, sections: List[Dict[str, Any]], client: str, year_end: Optional[date],
              made_by: str = "LedgerMind Assistant", subtitle: str = "") -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    teal, grey, line = colors.HexColor("#0F766E"), colors.HexColor("#475569"), colors.HexColor("#CBD5E1")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=17, textColor=teal, alignment=0, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], fontSize=9, textColor=grey, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12, textColor=teal, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=10, leading=14, spaceAfter=4)
    cell = ParagraphStyle("cell", parent=body, fontSize=8.5, leading=11, spaceAfter=0)
    cell_r = ParagraphStyle("cellr", parent=cell, alignment=2)
    cell_h = ParagraphStyle("cellh", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)

    def para(text: str, style) -> Paragraph:
        t = escape(str(text))
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        return Paragraph(t.replace("\n", "<br/>"), style)

    story = [para(title, h1),
             para(" · ".join(x for x in (client, f"Year end {year_end:%d/%m/%Y}" if year_end else "",
                                         f"Prepared {date.today():%d/%m/%Y}", subtitle) if x), sub)]
    width = A4[0] - 36 * mm
    for s in sections[:30]:
        if s.get("heading"):
            story.append(para(s["heading"], h2))
        for chunk in re.split(r"\n\s*\n", str(s.get("text") or "")):
            if chunk.strip():
                story.append(para(chunk.strip(), body))
        cols, rows = _table(s.get("table"))
        if cols:
            data = [[para(c, cell_h) for c in cols]]
            # Figures right-aligned, '3,263.21 Dr' and '£500.00 Cr' too
            amount = lambda v: isinstance(_number(v), (int, float)) or bool(re.fullmatch(r"£?[\d,]+(\.\d+)?\s*(Dr|Cr)", str(v).strip()))
            # Columns the table names as counts are shown as they are, right-aligned (3, not 3.00)
            counts = set(s["table"].get("count_cols") or [])
            for r in rows[:500]:
                data.append([para(v, cell_r) if j in counts else
                             para(f"{_number(v):,.2f}" if isinstance(_number(v), (int, float)) else v,
                                  cell_r if amount(v) else cell) for j, v in enumerate(r[:len(cols)])])
            # A table may give its columns' shares of the page width; else all equal
            shares = s["table"].get("widths") if len(s["table"].get("widths") or []) == len(cols) else [1] * len(cols)
            t = Table(data, colWidths=[width * w / sum(shares) for w in shares], repeatRows=1)
            style = [("BACKGROUND", (0, 0), (-1, 0), teal), ("GRID", (0, 0), (-1, -1), 0.4, line),
                     ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3),
                     ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
            style += [("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F8FAFC")) for i in range(2, len(data), 2)]
            t.setStyle(TableStyle(style))
            story += [Spacer(1, 3), t, Spacer(1, 6)]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(grey)
        canvas.drawString(18 * mm, 10 * mm, f"{client or 'LedgerMind'} · {title}"[:110])
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    out = io.BytesIO()
    SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                      bottomMargin=16 * mm, title=title, author=made_by).build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()


def save_file(db: Session, chat: ChatSession, data: bytes, filename: str, kind: str) -> ChatFile:
    from backend.app.core.s3 import S3Service
    f = ChatFile(session_id=chat.id, filename=filename, kind=kind, storage_path="", size_bytes=len(data))
    db.add(f)
    db.flush()
    content = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if kind == "xlsx" else "application/pdf")
    f.storage_path = S3Service().upload_file_bytes(data, f"assistant/{chat.id}/{f.id}.{kind}", content)
    db.commit()
    return f


def file_json(f: ChatFile) -> Dict[str, Any]:
    return {"id": f.id, "name": f.filename, "kind": f.kind, "size": f.size_bytes}


# ----------------------------------------------------------------------------------------------------- chart

def check_chart(args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The chart for the panel, or None when it is not drawable (labels and each series of numbers, same length)."""
    labels = [str(x)[:40] for x in (args.get("labels") or [])][:60]
    series = []
    for s in (args.get("series") or [])[:4]:
        if not isinstance(s, dict):
            continue
        values = [_number(v) for v in (s.get("values") or [])][:len(labels)]
        values = [v if isinstance(v, (int, float)) else None for v in values]
        if labels and len(values) == len(labels) and any(v is not None for v in values):
            series.append({"name": str(s.get("name") or "")[:40], "values": values})
    if not series:
        return None
    kind = str(args.get("type") or "bar").lower()
    return {"type": kind if kind in ("bar", "line") else "bar", "title": str(args.get("title") or "")[:120],
            "labels": labels, "series": series, "unit": "£" if str(args.get("unit") or "£") == "£" else ""}


# ------------------------------------------------------------------------------------------ tool definitions

def _spec(name: str, description: str, props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"toolSpec": {"name": name, "description": description,
                         "inputSchema": {"json": {"type": "object", "properties": props, "required": required}}}}


_TABLE = {"type": "object", "properties": {
    "columns": {"type": "array", "items": {"type": "string"}},
    "rows": {"type": "array", "items": {"type": "array", "items": {}}, "description": "Each row's cells, figures as numbers"}}}

SPECS = [
    _spec("make_excel", "Make an Excel file the user can download. Use ONLY when the user asks for Excel / a "
                        "spreadsheet / a download. Fill it with figures from the other tools, never invented ones.",
          {"title": {"type": "string", "description": "Short title, e.g. 'Payroll by month'"},
           "sheets": {"type": "array", "items": {"type": "object", "properties": {
               "name": {"type": "string"}, **_TABLE["properties"]}},
               "description": "One or more sheets; put a 'Total' row last where it helps"}},
          ["title", "sheets"]),
    _spec("make_pdf", "Make a PDF note the user can download (e.g. for the working-paper file). Use ONLY when the "
                      "user asks for a PDF / a note / a document. Figures only from the other tools.",
          {"title": {"type": "string"},
           "sections": {"type": "array", "items": {"type": "object", "properties": {
               "heading": {"type": "string"}, "text": {"type": "string", "description": "Plain text; **bold** allowed"},
               "table": _TABLE}}}},
          ["title", "sections"]),
    _spec("make_chart", "Draw a chart in the chat. Use it yourself when figures over time or a comparison read better "
                        "as a picture (a trend by month, this year against last year, the biggest items), and always "
                        "when the user asks for a chart or graph. Values are plain numbers in £.",
          {"type": {"type": "string", "description": "'bar' or 'line' (line for trends over months)"},
           "title": {"type": "string"},
           "labels": {"type": "array", "items": {"type": "string"}, "description": "x axis, e.g. months"},
           "series": {"type": "array", "items": {"type": "object", "properties": {
               "name": {"type": "string"}, "values": {"type": "array", "items": {"type": "number"}}}},
               "description": "One to four series, each with one value per label"}},
          ["labels", "series"]),
]

NAMES = {s["toolSpec"]["name"] for s in SPECS}
LABELS = {"make_excel": "Making the Excel file", "make_pdf": "Making the PDF", "make_chart": "Drawing the chart"}
