"""Files attached to a chat question: read when added (no AI for a PDF with text), a preview made, kinds checked."""

from types import SimpleNamespace as N

import fitz

from backend.app.services.assistant import uploads


def _pdf(text: str, password: str = "") -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    opts = {"encryption": fitz.PDF_ENCRYPT_AES_256, "user_pw": password, "owner_pw": password + "x"} if password else {}
    return doc.tobytes(**opts)


def test_text_pdf_read_without_ai_and_preview():
    data = _pdf("Bank statement 1 April to 30 April 2026. Closing balance 1,234.56 and more words to read here.")
    text, pages, status, note, by = uploads.read("statement.pdf", data)
    assert (status, pages, by, note) == ("READ", 1, "text", None) and "1,234.56" in text
    png = uploads.thumbnail("statement.pdf", data)
    assert png and png[:8] == b"\x89PNG\r\n\x1a\n"


def test_locked_pdf_not_read_and_kinds():
    text, pages, status, note, by = uploads.read("locked.pdf", _pdf("secret", password="pw"))
    assert status == "UNREADABLE" and "unprotected copy" in note and text == ""
    assert uploads.kind_of("Receipt.JPG") == "image/jpeg" and uploads.kind_of("book.xlsx") is None


def test_files_as_the_model_reads_them():
    a = N(filename="P60.pdf", pages=1, status="READ", text="Pay 30,000 Tax 3,486", note=None)
    b = N(filename="scan.pdf", pages=3, status="UNREADABLE", text="", note="The PDF is damaged: please send it again.")
    out = uploads.for_model([a, b])
    assert out.startswith("[Attached file 1: P60.pdf]\nPay 30,000")
    assert "[Attached file 2: scan.pdf, 3 pages]\n(Could not be read: The PDF is damaged" in out
