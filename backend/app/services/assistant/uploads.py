"""Files attached to a question: read as soon as they are added, so the tile can say what was read before sending.

  PDF with text   its text layer, as it is (fast, exact)
  scan or photo   each page (up to MAX_PAGES) transcribed by the model that sees pictures (sa/extract/vision.py)
  locked/damaged  not read: the tile says why (a PDF that needs a password is never tried)
  preview         the first page or the picture, small, for the tile

The text goes to the chat model with the question (MAX_CHARS a file): the main model reads text only."""

from typing import Dict, Optional, Tuple

MAX_FILES = 5
MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 10
MAX_CHARS = 30000
KINDS = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".gif": "image/gif"}
PROMPT = ("Transcribe all the text in this document image exactly as written: every number, date, name and table row "
          "(a table as lines with | between columns). Do not summarise or explain. If there is no text, describe the "
          "image in one sentence.")


def kind_of(name: str) -> Optional[str]:
    low = name.lower()
    return next((m for ext, m in KINDS.items() if low.endswith(ext)), None)


def _transcribe(image: bytes) -> str:
    from backend.app.sa.extract.vision import READER, _client, _format
    r = _client().converse(
        modelId=READER,
        messages=[{"role": "user", "content": [{"image": {"format": _format(image), "source": {"bytes": image}}},
                                               {"text": PROMPT}]}],
        inferenceConfig={"maxTokens": 4000, "temperature": 0})
    from backend.app.core import ai_usage
    ai_usage.record(READER, "image", PROMPT, r)
    return next((b["text"] for b in r["output"]["message"]["content"] if "text" in b), "").strip()


def thumbnail(name: str, data: bytes, width: int = 320) -> Optional[bytes]:
    """The first page (a PDF) or the picture, about 320 pixels wide, as a PNG."""
    import fitz
    try:
        doc = fitz.open(stream=data, filetype="pdf" if name.lower().endswith(".pdf") else name.rsplit(".", 1)[-1].lower())
        if doc.needs_pass and not doc.authenticate(""):
            return None
        page = doc[0]
        zoom = width / max(page.rect.width, 1)
        return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")
    except Exception:
        return None


def read(name: str, data: bytes) -> Tuple[str, int, str, Optional[str], str]:
    """(text, pages, status, note, read_by)."""
    from backend.app.sa.intake import intake, page_png
    items = intake([(name, data)])
    if not items:
        return "", 0, "UNREADABLE", "The file is empty.", ""
    item = items[0]
    if item.unreadable:
        return "", item.pages, "UNREADABLE", item.unreadable, ""
    if not item.image:
        text = item.text.strip()
        return text[:MAX_CHARS], item.pages, ("READ" if text else "UNREADABLE"), (None if text else "No text found in it."), "text"
    from backend.app.sa.extract.vision import READER
    pages = max(item.pages, 1)
    parts = []
    for p in range(min(pages, MAX_PAGES)):
        try:
            png = page_png(item, p, dpi=150)
            if png:
                got = _transcribe(png)
                parts.append(f"[Page {p + 1}]\n{got}" if pages > 1 else got)
        except Exception:
            parts.append(f"[Page {p + 1}: could not be read]")
    text = "\n\n".join(parts).strip()
    note = f"Only the first {MAX_PAGES} of {pages} pages were read." if pages > MAX_PAGES else None
    return text[:MAX_CHARS], pages, ("READ" if text else "UNREADABLE"), note or (None if text else "Nothing could be read."), READER


def upload_json(u) -> Dict:
    return {"id": u.id, "name": u.filename, "mime": u.mime, "size": u.size_bytes, "pages": u.pages or 0,
            "status": u.status, "note": u.note, "chars": len(u.text or ""), "has_thumb": bool(u.thumb_path),
            "image": u.mime.startswith("image/")}


def for_model(uploads) -> str:
    """The files as the model reads them, before the question."""
    out = []
    for n, u in enumerate(uploads, start=1):
        head = f"[Attached file {n}: {u.filename}" + (f", {u.pages} pages" if (u.pages or 0) > 1 else "") + "]"
        out.append(f"{head}\n{u.text}" if u.status == "READ" and u.text else f"{head}\n(Could not be read: {u.note or 'no text'})")
    return "\n\n".join(out)
