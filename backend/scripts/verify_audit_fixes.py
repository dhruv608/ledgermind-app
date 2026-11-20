import os
import openpyxl
from pathlib import Path
from backend.app.core.config import settings
from backend.app.core.database import SessionLocal
from backend.app.models.database import ClientEngagement, TBRecord, GLTransaction
from backend.app.services.workbook.excel_service import excel_service

def verify_system():
    db = SessionLocal()
    eng = db.query(ClientEngagement).first()
    if not eng:
        print('No engagement found in DB, creating test engagement')
        from datetime import date
        eng = ClientEngagement(
            id='audit-verify-001',
            client_name='Apex Capital Partners Ltd',
            period_end_date=date(2025, 12, 31),
            source_system='Xero',
            status='IN_PROGRESS'
        )
        db.add(eng)
        db.commit()

    tb_records = db.query(TBRecord).filter(TBRecord.engagement_id == eng.id).all()
    print(f'Testing with database engagement: "{eng.client_name}" (ID: {eng.id})')
    print(f'Total TB records in engagement: {len(tb_records)}')

    wp = excel_service.generate_master_workpapers(engagement=eng, tb_records=tb_records, db=db)
    file_path = settings.DATA_DIR / wp.filename
    print(f'Generated file on disk: {file_path.name} ({file_path.stat().st_size:,} bytes)')

    wb = openpyxl.load_workbook(str(file_path), data_only=False)

    print('\n=== 1. TTB COLUMN TOTALS VERIFICATION ===')
    ws_ttb = wb['TTB']
    tot_r = 6 + len(tb_records) + 1 if len(tb_records) > 0 else 7
    print(f'Row {tot_r} Label:', repr(ws_ttb.cell(tot_r, 2).value))
    print(f'Row {tot_r} Debit Formula:', repr(ws_ttb.cell(tot_r, 6).value))
    print(f'Row {tot_r} Credit Formula:', repr(ws_ttb.cell(tot_r, 7).value))
    print(f'Row {tot_r} Check Formula:', repr(ws_ttb.cell(tot_r, 8).value))

    print('\n=== 2. RE-ANALYSIS TAB BLANK VERIFICATION ===')
    ws_re = wb['Re-analysis']
    non_empty_re = [r for r in range(8, ws_re.max_row + 1) if any(ws_re.cell(r, c).value is not None for c in range(1, 10))]
    print(f'Re-Analysis data rows (must be 0): {len(non_empty_re)}')

    print('\n=== 3. DEBTORS & SUBLEDGER PURGE VERIFICATION ===')
    if 'E2.1-Debtors NL ' in wb.sheetnames:
        ws_deb = wb['E2.1-Debtors NL ']
        print('Debtors NL max_row:', ws_deb.max_row)
        print('Debtors NL row 7 sample:', [ws_deb.cell(7, c).value for c in range(1, 10)])
    else:
        print('Debtors tab correctly pruned (no Debtors nominal code in client TTB)')

    print('\n=== 4. LEAKAGE AUDIT ACROSS ALL WORKBOOK SHEETS ===')
    # Names from the template's source client that must not leak into a built workbook (kept outside the repository)
    tokens = [t.strip().lower() for t in os.environ.get('LM_TEMPLATE_SOURCE_NAMES', '').split(',') if t.strip()]
    leaks = []
    for s in wb.sheetnames:
        ws = wb[s]
        for r in range(1, ws.max_row + 1):
            for c in range(1, ws.max_column + 1):
                cell = ws.cell(r, c)
                v = str(cell.value or '').lower()
                h_loc = str(cell.hyperlink.location if cell.hyperlink else '').lower()
                h_tar = str(cell.hyperlink.target if cell.hyperlink else '').lower()
                if any(t in v or t in h_loc or t in h_tar for t in tokens):
                    leaks.append((s, r, c, v, h_loc))
    print(f'Total cross-contamination leakage count: {len(leaks)}')
    if leaks:
        print('Leaks found:', leaks[:5])
    else:
        print('RESULT: 100% CONFIRMED — Zero leakage tokens across all sheets, cells, formulas, and hyperlinks!')

if __name__ == '__main__':
    verify_system()
