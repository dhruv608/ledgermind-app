"""Intake: the files as the client sent them, made ready to read (R-IN-01 to R-IN-04).

  archives   zip unpacked, also inside another zip; __MACOSX, .DS_Store, Thumbs.db and Office lock files dropped
             (rar / 7z: unreadable, ask for a zip)
  protected  a PDF that opens without a password (owner lock only) is read; one that needs a password is never
             tried: unreadable, with the client query
  text       a PDF's text layer; none (a scan) or an image: read as a picture by the AI (extract/vision.py)
  duplicates the same file twice (by hash) is kept once"""

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from typing import List, Optional, Tuple

JUNK = (".ds_store", "thumbs.db", "desktop.ini")
IMAGES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
MAX_DEPTH = 3


@dataclass
class Item:
    name: str                       # 'archive.zip/folder/file.pdf' inside an archive
    data: bytes
    sha256: str
    text: str = ""                  # the text layer (PDF, spreadsheet, Word), '' for a scan or image
    pages: int = 0
    image: bool = False             # a picture (or a scanned PDF): read by the AI as an image
    unreadable: str = ""            # why it cannot be read (the client query)
    saved: Optional[str] = None     # when the file itself was last saved (an Office file's own date, else the zip's)


def _junk(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    leaf = parts[-1].lower()
    return ("__macosx" in (p.lower() for p in parts) or leaf in JUNK or leaf.startswith("~$") or leaf.startswith("._")
            or not leaf)


def _unpack(name: str, data: bytes, depth: int = 0, saved: Optional[str] = None) -> List[Tuple[str, bytes, str, Optional[str]]]:
    """(name, bytes, why unreadable, the date it was saved in the zip) for each file, archives opened."""
    low = name.lower()
    if low.endswith(".zip"):
        if depth >= MAX_DEPTH:
            return [(name, data, "Archive inside archives too deep: please send the files themselves.", saved)]
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            members = [i for i in z.infolist() if not i.is_dir() and not _junk(i.filename)]
            locked = [i for i in members if i.flag_bits & 0x1]
            # The locked files are one query for the zip, never a password tried (R-IN-03)
            out = ([(name, b"", f"{len(locked)} of the {len(members)} files in this zip need a password: please "
                                f"send them without one.", saved)] if locked else [])
            for info in members:
                if not info.flag_bits & 0x1:
                    when = "%04d-%02d-%02dT%02d:%02d" % info.date_time[:5]
                    out.extend(_unpack(f"{name}/{info.filename}", z.read(info), depth + 1, when))
            return out
        except zipfile.BadZipFile:
            return [(name, data, "The zip file is damaged: please send it again.", saved)]
    if low.endswith((".rar", ".7z")):
        return [(name, data, "This archive type is not read: please send the files, or one .zip.", saved)]
    return [(name, data, "", saved)]


OFFICE_SAVED = re.compile(r"<dcterms:modified[^>]*>([^<]+)<")
OLE = bytes.fromhex("d0cf11e0a1b11ae1")                 # an old Office file (.doc, .xls), or an encrypted new one
DOC_RUN = re.compile(r"[\x20-\x7e\xa3\r\n\t]{5,}")


def _doc_text(data: bytes) -> str:
    """An old Word (.doc) file's words: its text runs read as Windows text (a letter's figures and dates), without the
    binary around them."""
    if data[:8] != OLE:
        return data[:20000].decode("utf-8", "ignore")
    return " ".join(DOC_RUN.findall(data.decode("cp1252", "ignore")))[:20000]


def _office_saved(data: bytes) -> Optional[str]:
    """An .xlsx or .docx file's own last-saved date (docProps/core.xml), YYYY-MM-DDTHH:MM."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            m = OFFICE_SAVED.search(z.read("docProps/core.xml").decode("utf-8", "ignore"))
        return m.group(1)[:16] if m else None
    except Exception:
        return None


def _pdf(item: Item) -> None:
    import fitz
    try:
        doc = fitz.open(stream=item.data, filetype="pdf")
    except Exception:
        item.unreadable = "The PDF is damaged: please send it again."
        return
    # A lock that only stops editing opens with no password; one that needs a password is never tried (R-IN-03)
    if doc.needs_pass and not doc.authenticate(""):
        item.unreadable = f"Please send an unprotected copy of {item.name.split('/')[-1]}."
        return
    item.pages = doc.page_count
    item.text = "\n".join(doc[i].get_text() for i in range(min(doc.page_count, 20)))
    if len(item.text.strip()) < 40:
        item.image = True                       # a scan: no text layer


def _sheet_text(item: Item) -> None:
    """Enough of a spreadsheet or Word file's text to say what it is."""
    low = item.name.lower()
    try:
        if low.endswith(".docx"):
            import re
            xml = zipfile.ZipFile(io.BytesIO(item.data)).read("word/document.xml").decode("utf-8", "ignore")
            item.text = " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))
        elif low.endswith(".ods"):
            from backend.app.sa.extract import ods
            item.text = ods.text(item.data)
        elif low.endswith((".xlsx", ".xlsm", ".xls", ".csv")):
            import pandas as pd
            if low.endswith(".csv"):
                frames = {"csv": pd.read_csv(io.BytesIO(item.data), header=None, nrows=60)}
            else:
                frames = pd.read_excel(io.BytesIO(item.data), sheet_name=None, header=None, nrows=60)
            # Row by row, cells apart: a client's list of accounts read as one run of words loses which figure is
            # whose (the bank's name may sit on the row above its figure)
            item.text = "\n".join(f"[{s}]\n" + "\n".join(" | ".join(str(v) for v in row if str(v) != "nan")
                                                         for row in f.values if any(str(v) != "nan" for v in row))
                                  for s, f in frames.items())
    except Exception:
        item.text = ""


def intake(files: List[Tuple[str, bytes]]) -> List[Item]:
    """Every file ready to classify, in the order sent; archives unpacked and junk dropped."""
    items: List[Item] = []
    for name, data in files:
        if _junk(name):
            continue
        for inner, blob, why, saved in _unpack(name, data):
            item = Item(inner, blob, hashlib.sha256(blob).hexdigest(), unreadable=why)
            low = inner.lower()
            item.saved = (_office_saved(blob) if low.endswith((".xlsx", ".xlsm", ".docx")) else None) or saved
            if not why:
                if low.endswith(".pdf"):
                    _pdf(item)
                elif low.endswith(IMAGES):
                    item.image = True
                elif low.endswith((".heic", ".heif")):
                    item.unreadable = "iPhone photo format (HEIC) is not read yet: please send it as a JPG or PDF."
                elif low.endswith((".docx", ".xlsx", ".xlsm")) and blob[:8] == OLE:
                    # An Office file that is really an encrypted container: protected by a password (R-IN-03)
                    item.unreadable = f"Please send an unprotected copy of {inner.split('/')[-1]}."
                elif low.endswith((".docx", ".xlsx", ".xlsm", ".xls", ".csv", ".ods")):
                    _sheet_text(item)
                elif low.endswith(".doc"):
                    item.text = _doc_text(blob)
                elif low.endswith((".txt", ".msg", ".eml")):
                    item.text = blob[:20000].decode("utf-8", "ignore")
            items.append(item)
    return items


def page_texts(item: Item) -> List[str]:
    """Each PDF page's own text (empty for a scanned page)."""
    import fitz
    try:
        doc = fitz.open(stream=item.data, filetype="pdf")
        doc.authenticate("")
        return [doc[i].get_text() for i in range(doc.page_count)]
    except Exception:
        return []


def page_png(item: Item, page: int = 0, dpi: int = 200) -> Optional[bytes]:
    """A PDF page as a picture for the AI (an image file is sent as it is)."""
    if not item.name.lower().endswith(".pdf"):
        return item.data
    import fitz
    doc = fitz.open(stream=item.data, filetype="pdf")
    doc.authenticate("")
    if page >= doc.page_count:
        return None
    return doc[page].get_pixmap(dpi=dpi).tobytes("png")
