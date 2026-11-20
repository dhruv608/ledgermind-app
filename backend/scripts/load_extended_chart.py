"""
Add the rest of the full TaxCalc chart ("Chart of Accounts - Limited company", 881 codes, the COA tab of the
master workpaper template) to master_coa as extended codes. The firm standard list (COA_Standard, 543 codes)
is left untouched; only codes that are missing are inserted, so this is safe to re-run.

- section (category): the heading the code sits under in the chart
- class: firm convention, codes below 4000 are Profit and Loss, 4000 and above Balance Sheet
- normal balance: the usual side for that section (depreciation / amortisation / impairment are credits)

Run from the project root:  python backend/scripts/load_extended_chart.py
"""

import collections
import re
import sys
from pathlib import Path

import openpyxl
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.core.database import SessionLocal
from backend.app.models.database import MasterCOA

TEMPLATE = Path(__file__).resolve().parent.parent / "app" / "templates" / "master_workpapers_template.xlsx"
CONTRA_NAMES = re.compile(r"depreciation|amortisation|impairment", re.IGNORECASE)


def full_chart() -> dict:
    ws = openpyxl.load_workbook(TEMPLATE, read_only=True, data_only=True)["COA"]
    chart, heading = {}, None
    for row in ws.iter_rows(values_only=True):
        code, name = row[0], row[1]
        if isinstance(code, (int, float)) and name:
            chart[int(code)] = (str(name).strip(), heading)
        elif isinstance(code, str) and code.strip() and not name:
            heading = code.strip()
    return chart


def main() -> None:
    db = SessionLocal()
    existing = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars().all()}

    side_by_section = collections.defaultdict(collections.Counter)
    lead_by_section = collections.defaultdict(collections.Counter)
    for c in existing.values():
        if not CONTRA_NAMES.search(c.std_name):
            side_by_section[c.category][c.normal_balance] += 1
        lead_by_section[c.category][c.lead_schedule_ref] += 1

    added = collections.Counter()
    for code, (name, section) in sorted(full_chart().items()):
        if code in existing:
            continue
        is_pl = code < 4000
        if CONTRA_NAMES.search(name):
            side = "Credit" if not is_pl else "Debit"
        elif side_by_section[section]:
            side = side_by_section[section].most_common(1)[0][0]
        else:
            side = "Credit" if (code < 1000 or code >= 5000) else "Debit"
        lead = lead_by_section[section].most_common(1)[0][0] if lead_by_section[section] else None
        db.add(MasterCOA(
            std_code=code,
            std_name=name,
            category=section,
            financial_class="Profit and Loss" if is_pl else "Balance Sheet",
            normal_balance=side,
            lead_schedule_ref=lead,
            is_extended=True,
        ))
        added[section] += 1

    db.commit()
    standard = sum(1 for c in existing.values() if not c.is_extended)
    print(f"Added {sum(added.values())} extended codes ({standard} standard and {len(existing) - standard} extended codes already present, unchanged)")
    for section, n in added.most_common():
        print(f"  {section:45} {n}")


if __name__ == "__main__":
    sys.exit(main())
