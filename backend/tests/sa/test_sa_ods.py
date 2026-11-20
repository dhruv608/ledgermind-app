"""OpenDocument spreadsheets (.ods) read without extra packages (a made-up sheet)."""

import io
import zipfile

from backend.app.sa.extract import ods

CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
<office:body><office:spreadsheet><table:table table:name="Sales">
<table:table-row><table:table-cell><text:p>Month</text:p></table:table-cell><table:table-cell><text:p>Total</text:p></table:table-cell></table:table-row>
<table:table-row><table:table-cell><text:p>April</text:p></table:table-cell><table:table-cell office:value-type="float" office:value="1234.5"><text:p>1,234.50</text:p></table:table-cell></table:table-row>
<table:table-row table:number-rows-repeated="1048570"><table:table-cell table:number-columns-repeated="1024"/></table:table-row>
</table:table></office:spreadsheet></office:body></office:document-content>"""


def _ods() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", CONTENT)
    return buf.getvalue()


def test_rows_with_numbers_and_no_blank_run():
    sheets = ods.read(_ods())
    assert sheets == {"Sales": [["Month", "Total"], ["April", "1234.5"]]}     # the blank million rows are dropped
    assert ods.text(_ods()) == "[Sales] Month Total April 1234.5"
