"""An OpenDocument spreadsheet (.ods: LibreOffice, a Google Sheets download) read without extra packages: it is a zip
whose content.xml holds the tables. Each sheet comes back as rows of cell text; a cell's office:value (the number
behind a formatted figure) is preferred to its shown text. Repeated rows and columns (how ODS stores blank runs) are
expanded, but trailing blank runs are dropped so a sheet is never millions of empty cells."""

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, List

NS = {"table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
      "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
      "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0"}
T = "{%s}" % NS["table"]
O = "{%s}" % NS["office"]
MAX_ROWS, MAX_COLS = 5000, 200


def _cell_text(cell) -> str:
    value = cell.get(O + "value") or cell.get(O + "date-value") or cell.get(O + "boolean-value")
    if value is not None:
        return value
    return " ".join("".join(p.itertext()) for p in cell.findall("text:p", NS)).strip()


def read(data: bytes) -> Dict[str, List[List[str]]]:
    """{sheet name: rows of cell text}."""
    xml = zipfile.ZipFile(io.BytesIO(data)).read("content.xml")
    root = ET.fromstring(xml)
    out: Dict[str, List[List[str]]] = {}
    for table in root.iter(T + "table"):
        rows: List[List[str]] = []
        for row in table.iter(T + "table-row"):
            cells: List[str] = []
            for cell in row:
                if cell.tag not in (T + "table-cell", T + "covered-table-cell"):
                    continue
                n = min(int(cell.get(T + "number-columns-repeated", "1")), MAX_COLS)
                cells += [_cell_text(cell)] * n
            while cells and not cells[-1]:
                cells.pop()
            n = min(int(row.get(T + "number-rows-repeated", "1")), MAX_ROWS)
            rows += [cells[:MAX_COLS]] * (n if cells else min(n, 1))
            if len(rows) >= MAX_ROWS:
                break
        while rows and not rows[-1]:
            rows.pop()
        out[table.get(T + "name") or f"Sheet{len(out) + 1}"] = rows
    return out


def text(data: bytes, max_rows: int = 60) -> str:
    """The sheets as the intake gives spreadsheets: '[Sheet] cell cell ...' per sheet."""
    return "\n".join(f"[{name}] " + " ".join(c for r in rows[:max_rows] for c in r if c and not re.fullmatch(r"\s*", c))
                     for name, rows in read(data).items())
