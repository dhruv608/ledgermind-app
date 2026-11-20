"""Working out every formula so the saved file shows figures: Excel (on a Windows computer) or LibreOffice (on the
server)."""

import logging
from datetime import date, datetime
from pathlib import Path

import openpyxl

logger = logging.getLogger(__name__)


def recalculate_with_excel_com(file_path: Path) -> bool:
    """Invokes Microsoft Excel COM to calculate all formulas and persist cached values."""
    try:
        import subprocess
        script_path = Path(__file__).resolve().parents[2] / "scripts" / "recalc.ps1"
        if script_path.exists():
            res = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script_path), "-FilePath", str(file_path)],
                timeout=180,
                capture_output=True,
                text=True
            )
            return res.returncode == 0
        else:
            clean_path = str(file_path).replace("'", "''")
            ps_script = f"""
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
$excel.AskToUpdateLinks = $false
try {{
    $wb = $excel.Workbooks.Open('{clean_path}', 0, $false)
    $excel.CalculateFull()
    $wb.Save()
    $wb.Close($false)
}} finally {{
    $excel.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($excel) | Out-Null
    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
}}
"""
            subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_script], timeout=180, capture_output=True)
            return True
    except Exception as e:
        logger.info("Excel COM recalculation skipped or failed: %s", e)
        return False


# The values Excel accepts in an error cell (t="e")
EXCEL_ERRORS = {"#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A", "#GETTING_DATA", "#SPILL!",
                "#CALC!", "#FIELD!", "#BLOCKED!", "#CONNECT!", "#BUSY!", "#UNKNOWN!"}


def recalculate_with_libreoffice(file_path: Path) -> bool:
    """Works out every formula with LibreOffice (on the server, where there is no Excel) and writes the results
    into the workbook as each formula's saved value. Only the values are taken from LibreOffice: the file itself
    (formatting, widths, number formats) stays exactly as built, since a LibreOffice re-save changes them."""
    import re
    import shutil
    import subprocess
    import tempfile
    import zipfile
    from datetime import time
    from xml.sax.saxutils import escape
    from openpyxl.utils.datetime import to_excel

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return False
    try:
        with tempfile.TemporaryDirectory() as tmp:
            # Its own profile folder, so two builds at once do not block each other
            subprocess.run([soffice, "--headless", f"-env:UserInstallation=file://{Path(tmp).as_posix()}/profile",
                            "--calc", "--convert-to", "xlsx", "--outdir", tmp, str(file_path)],
                           timeout=240, capture_output=True, check=True)
            calculated = Path(tmp) / file_path.name
            values = openpyxl.load_workbook(calculated, data_only=True, read_only=True)
            results = {ws.title: {c.coordinate: c.value for row in ws.iter_rows() for c in row
                                  if getattr(c, "coordinate", None) and c.value is not None}
                       for ws in values.worksheets}
            values.close()

        with zipfile.ZipFile(file_path) as z:
            parts = {n: z.read(n) for n in z.namelist()}
        # Sheet name -> its XML part
        rels = {}
        for tag in re.findall(r"<Relationship\b[^>]*>", parts["xl/_rels/workbook.xml.rels"].decode()):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', tag))
            rels[attrs.get("Id")] = attrs.get("Target", "")
        sheets = {}
        for tag in re.findall(r"<sheet\b[^>]*>", parts["xl/workbook.xml"].decode()):
            attrs = dict(re.findall(r'([\w:]+)="([^"]*)"', tag))
            name, target = attrs.get("name", ""), rels.get(attrs.get("r:id"), "").lstrip("/")
            sheets[name.replace("&amp;", "&").replace("&apos;", "'").replace("&quot;", '"')] = (
                target if target.startswith("xl/") else f"xl/{target}")

        cell = re.compile(r'<c r="([A-Z]+[0-9]+)"([^>]*?)(?<!/)>(<f[^>]*?(?:/>|>[^<]*</f>))(?:<v\s*/>|<v>[^<]*</v>)?</c>')

        def with_value(m, found):
            ref, attrs, formula = m.group(1), re.sub(r'\s+t="[^"]*"', "", m.group(2)), m.group(3)
            v = found.get(ref)
            if v is None:
                return m.group(0)
            if isinstance(v, bool):
                t, text = "b", "1" if v else "0"
            elif isinstance(v, (datetime, date, time)):
                t, text = None, repr(float(to_excel(v)))      # a date is a number in Excel, shown by its format
            elif isinstance(v, (int, float)):
                t, text = None, repr(float(v)) if isinstance(v, float) else str(v)
            elif isinstance(v, str) and v in EXCEL_ERRORS:
                # Only Excel's own error codes: a text that starts with '#' (a QuickBooks reference '#4825', linked
                # from the GL by formula) written as an error makes Excel repair the file
                t, text = "e", escape(v)
            else:
                t, text = "str", escape(str(v))
            kind = f' t="{t}"' if t else ""
            return f'<c r="{ref}"{attrs}{kind}>{formula}<v>{text}</v></c>'

        for name, part in sheets.items():
            if part in parts and name in results:
                xml = parts[part].decode("utf-8")
                parts[part] = cell.sub(lambda m: with_value(m, results[name]), xml).encode("utf-8")
        out = file_path.with_suffix(".calc.xlsx")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for n, data in parts.items():
                z.writestr(n, data)
        out.replace(file_path)
        return True
    except Exception as e:
        logger.info("LibreOffice recalculation skipped or failed: %s", e)
        return False
