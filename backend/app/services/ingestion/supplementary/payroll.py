"""Payroll: the BrightPay report, a payroll summary, P32 sheets, head count, employment allowance and director pay."""

import re
from datetime import date
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from backend.app.models.database import PayrollP32Record
from backend.app.services.ingestion import payroll_directors
from backend.app.services.ingestion.supplementary.common import (
    BRIGHTPAY_COLUMNS, BRIGHTPAY_NET, BRIGHTPAY_PERIOD, BRIGHTPAY_REQUIRED, SUMMARY_TITLE,
)


class PayrollParsing:
    """Payroll: the BrightPay report, a payroll summary, P32 sheets, head count, employment allowance and director pay.
    Mixed into SupplementaryParserService."""

    @staticmethod
    def _average_employees(rows: List[List[str]]) -> Optional[float]:
        """The year's average from a line such as 'Average employee : | | 3' or 'AVG NO EMPLOYEES | | 14.27'."""
        for row in rows:
            for i, cell in enumerate(row):
                if re.match(r"^\s*(?:average|avg\.?)\s+(?:no\.?\s+(?:of\s+)?)?(?:employees?|ee'?s?)\b", cell or "", re.I):
                    for later in row[i + 1:]:
                        try:
                            n = float(str(later).replace(",", "").strip())
                        except ValueError:
                            continue
                        if 0 < n < 10000:
                            return round(n, 2)
        return None

    @classmethod
    def _store_headcount(cls, engagement_id: str, by_month: Dict[date, float], year_average: Optional[float],
                         db: Session) -> None:
        """The number of employees the payroll file gives (replacing an earlier payroll file's)."""
        from backend.app.models.payroll_headcount import PayrollHeadcount
        db.query(PayrollHeadcount).filter(PayrollHeadcount.engagement_id == engagement_id).delete(synchronize_session=False)
        for when, n in sorted(by_month.items()):
            if n and n > 0:
                db.add(PayrollHeadcount(engagement_id=engagement_id, period_end=when, count=round(n, 2)))
        if year_average:
            db.add(PayrollHeadcount(engagement_id=engagement_id, period_end=None, count=year_average))
        db.commit()

    @classmethod
    def _store_allowance(cls, engagement_id: str, by_month: Dict[Optional[date], float], db: Session) -> None:
        """The employment allowance the payroll file shows (replacing an earlier payroll file's)."""
        from backend.app.models.payroll_allowance import PayrollAllowance
        db.query(PayrollAllowance).filter(PayrollAllowance.engagement_id == engagement_id).delete(synchronize_session=False)
        for when, amount in sorted(by_month.items(), key=lambda kv: kv[0] or date.min):
            if abs(amount) >= 0.005:
                db.add(PayrollAllowance(engagement_id=engagement_id, period_end=when, amount=round(amount, 2)))
        db.commit()

    @classmethod
    def _store_director_pay(cls, engagement_id: str, filename: str, rows: List[List[str]], db: Session) -> None:
        """Directors' pay as the payroll file gives it (replacing an earlier payroll file's)."""
        import json
        from backend.app.models.director_pay import PayrollDirectorMonth, PayrollDirectorPay
        db.query(PayrollDirectorPay).filter(PayrollDirectorPay.engagement_id == engagement_id).delete(synchronize_session=False)
        db.query(PayrollDirectorMonth).filter(PayrollDirectorMonth.engagement_id == engagement_id).delete(synchronize_session=False)
        found = payroll_directors.read(rows)
        if found is not None:
            db.add(PayrollDirectorPay(engagement_id=engagement_id, gross_pay=found.gross, employer_nic=found.employer_nic,
                                      pension_employer=found.pension_employer, people=json.dumps(found.people) or None,
                                      how=found.how, filename=filename[:255]))
            for when, gross in sorted(found.months.items()):
                db.add(PayrollDirectorMonth(engagement_id=engagement_id, period_end=when, gross_pay=round(gross, 2)))
        db.commit()

    @classmethod
    def _brightpay_header(cls, rows: List[List[str]]) -> Optional[int]:
        """Row index of a BrightPay payroll report's column headings, or None if this is not one."""
        for i, row in enumerate(rows[:20]):
            cells = {c.strip().lower() for c in row}
            if BRIGHTPAY_REQUIRED <= cells and any(n in cells for n in BRIGHTPAY_NET):
                return i
        return None

    @staticmethod
    def _summary_field(heading: str) -> Optional[str]:
        """The payroll field a 'Payroll Summary' column holds ('ER NI', 'Employer NI', 'Employee Pension'...)."""
        h = re.sub(r"[^a-z ]", " ", heading.lower()).split()
        text = " ".join(h)
        # 'Er's NI' / 'Ers NI' / 'Employer NI'; 'Ee's Nest' / 'EE/NI'; NEST is the workplace pension
        employer = bool({"er", "ers", "employer", "employers"} & set(h))
        employee = bool({"ee", "ees", "employee", "employees"} & set(h))
        ni = bool({"ni", "nic", "nics"} & set(h))
        pension = bool({"pension", "pensions", "nest"} & set(h))
        # 'Employment Allowance', 'E Allowance', "Er' allow", 'PAYE and NI Allowance'
        if {"allowance", "allow"} & set(h):
            return "allowance"
        # 'No of Employees', 'No. of EE', "No of EE's", 'Avg. no of Employee': the headcount
        if re.search(r"\bno\b.*\b(?:ees?|employees?)\b|\bavg\b.*\bemployees?\b|headcount", text):
            return "headcount"
        if "gross" in h:
            return "gross_pay"
        # Statutory maternity, paternity, adoption and shared parental pay: paid through the payroll and claimed back
        # from HMRC (92%, 103% for small employers). Not sick pay: SSP is not recoverable since April 2014
        if re.fullmatch(r"(?:smp|spp|sap|shpp|spbp)(?: (?:paid|recovered|reclaimed))?", text) or re.search(
                r"\bstatutory (?:maternity|paternity|adoption|shared parental|parental bereavement)\b", text):
            return "statutory_pay_recovered"
        if h[:1] == ["tax"] or text in ("income tax", "paye tax") or (
                "tax" in h and employee and not ({"code", "payable", "paid", "due"} & set(h))):   # "Ee's Tax"
            return "tax_deducted"
        if ni and employer:
            return "employer_nic"
        if ni and employee:
            return "employee_nic"
        if "student" in h:
            return "student_loan"
        if pension and employer:
            return "pension_employer"
        if pension and employee:
            return "pension_employee"
        if text in ("take home pay", "take home"):
            return "take_home"
        # 'Net pay', 'Net wages'; not 'Net PAYE to pay' nor 'Net Wages Payment' (what was paid)
        if text.startswith("net") and not ({"paye", "tax", "payment", "payments", "paid", "payable", "due", "o", "s"}
                                           & set(h)):
            return "net_pay"
        if text == "paye":
            return "total_hmrc_due"
        if re.search(r"\b(wages?|salar(y|ies))\b", text) and not re.search(r"\b(paid|payable|due|o s|payments?|net)\b", text):
            return "wages"           # 'Director wages', 'Employee wages', 'Direct Wages': gross when no Gross column
        return None

    @classmethod
    def _summary_columns(cls, row: List[str]) -> Dict[int, str]:
        """{column: payroll field} of a 'Payroll Summary' heading row. 'PAYE' alone is the tax when there is no Tax
        column (else the total due to HMRC); wages / salary columns add up to the gross when there is no Gross
        column (a director's and the employees' wages side by side). 'Take-home pay' is the net pay when given (a
        'Net pay' beside it is before the pension)."""
        cols = {i: cls._summary_field(c) for i, c in enumerate(row) if c.strip() and cls._summary_field(c)}
        # The firm's own summary ('Directors | Employees | Tax | EE's NIC ...'): the directors' and the
        # employees' pay side by side, adding up to the gross
        if any(c.strip() and i not in cols and payroll_directors.DIRECTOR_COLUMN.match(c.strip()) for i, c in enumerate(row)):
            for i, c in enumerate(row):
                if i not in cols and (payroll_directors.DIRECTOR_COLUMN.match(c.strip())
                                      or re.fullmatch(r"(?i)employees?|staff|admin staff", c.strip())):
                    cols[i] = "wages"
        fields = set(cols.values())
        for i, f in list(cols.items()):
            if f == "net_pay" and "take_home" in fields:
                del cols[i]
            elif f == "take_home":
                cols[i] = "net_pay"
            elif f == "total_hmrc_due" and "tax_deducted" not in fields:
                cols[i] = "tax_deducted"
            elif f == "wages":
                if "gross_pay" in fields:
                    del cols[i]
                else:
                    cols[i] = "gross_pay"
        return cols

    @classmethod
    def _summary_headers(cls, rows: List[List[str]]) -> List[int]:
        """Rows holding the column headings of the firm's 'Payroll Summary' blocks (Gross, Tax, ... Net Wages)."""
        out = []
        for i, row in enumerate(rows):
            fields = set(cls._summary_columns(row).values())
            if {"gross_pay", "tax_deducted", "net_pay"} <= fields and ({"employer_nic", "employee_nic"} & fields):
                out.append(i)
        return out

    @classmethod
    def _parse_payroll_summary(cls, engagement_id: str, rows: List[List[str]], db: Session) -> int:
        """The firm's 'Payroll Summary': first the company's months with a Total line, then one block per director or
        employee (their name above the headings). The people are kept month by month, like a BrightPay report, and
        must add up to the company's months; without person blocks (or when they do not agree) the company's months
        are kept instead. Totals, opening lines and the notes below are not pay."""
        def amount(text: str) -> float:
            text = (text or "").replace("£", "").replace(",", "").strip()
            neg = text.startswith("(") and text.endswith(")")
            try:
                n = float(text.strip("()")) if text else 0.0
            except ValueError:
                return 0.0
            return -n if neg else n

        def month(text: str) -> Optional[date]:
            text = text.strip()
            # A weekly line ('Week 9 - Ending 1 June, 2024'): the month the week ends in
            ending = re.search(r"\bending\s+(\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4})\s*$", text, re.I)
            if ending:
                try:
                    d = pd.to_datetime(ending.group(1).replace(",", ""), dayfirst=True)
                except (ValueError, TypeError):
                    return None
                return None if pd.isna(d) else (d + pd.offsets.MonthEnd(0)).date()
            # A whole year on one line ('Apr25-Mar26'): dated at its last month
            text = re.sub(r"^[A-Za-z]{3,9}\s*'?\d{2,4}\s*[-–]\s*(?=[A-Za-z]{3,9}\s*'?\d{2,4}$)", "", text)
            short = re.fullmatch(r"([A-Za-z]{3,9})[\s'-]*(\d{2}|\d{4})", text)    # 'Apr-25', 'April 2025'
            try:
                # A date typed as text is UK day-first ('01/02/2024' is February); a real date cell comes as ISO
                # ('2024-02-01 00:00:00'), which day-first would swap
                d = (pd.to_datetime(f"1 {short.group(1)} {short.group(2)}", dayfirst=True) if short
                     else pd.to_datetime(text, dayfirst=bool(re.match(r"^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", text))))
            except (ValueError, TypeError):
                return None
            if pd.isna(d) or not (short or re.match(r"^\d{4}-\d{2}-\d{2}|^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", text)):
                return None
            return (d + pd.offsets.MonthEnd(0)).date()

        blocks = []                                  # (person or None, {month: {field: amount}})
        heads = cls._summary_headers(rows)
        for n, h in enumerate(heads):
            cols = cls._summary_columns(rows[h])
            # The month is in the first column, or in the column headed Month / Period / Date
            heading = [c.strip().lower() for c in rows[h]]
            at = next((i for i, c in enumerate(heading) if re.fullmatch(r"months?|period|pay period|date|tax month", c)), 0)
            # A name has words: column markers ('a', 'b') and cell links ('ETB!A1') above the headings are not people
            # nor is how often they are paid ('Employer | John Doe | Weekly')
            above = [c.strip() for c in rows[h - 1] if len(re.findall(r"[A-Za-z]", c)) >= 3 and "!" not in c
                     and not re.match(r"\s*(?:grand\s+)?totals?\b", c, re.I)
                     and not re.fullmatch(r"(?:\d+|four|two)?[\s-]*(?:weekly|monthly|fortnightly|annual(?:ly)?)",
                                          c.strip(), re.I)] if h > 0 else []
            person = None
            # The first block is the company's months, unless a person's name heads it (a report of one block per
            # person: a name above the headings, not 'Payroll Summary', 'Employees' or the client's name)
            if n == 0 and above and not SUMMARY_TITLE.search(" ".join(above)) and len(heads) > 1:
                person = above[-1]
            if n > 0 and above:
                # 'Director Payroll | Jane Doe', 'Employee | John Doe' or just 'J Smith'
                person = above[-1] if len(above) > 1 else above[0]
            months: Dict[date, Dict[str, float]] = {}
            end = heads[n + 1] if n + 1 < len(heads) else len(rows)
            for row in rows[h + 1:end]:
                first = row[at].strip() if at < len(row) else ""
                when = month(first)
                if when is None:
                    if months and (not first or first.lower().startswith("total")):
                        break                        # the block's total line ends it
                    continue                         # 'opening' and other lines before the months
                values: Dict[str, float] = {}
                for i, f in cols.items():
                    if i < len(row):
                        values[f] = values.get(f, 0.0) + amount(row[i])
                if any(abs(v) >= 0.005 for v in values.values()):
                    m = months.setdefault(when, {})
                    for f, v in values.items():
                        m[f] = m.get(f, 0.0) + v
            if months:
                blocks.append((person, months))
        if not blocks:
            return 0

        gross = lambda b: sum(m.get("gross_pay", 0.0) for m in b[1].values())
        if blocks[0][0] is not None and len(blocks) >= 3:
            # A block whose pay is the sum of all the others is the company's total, whatever is written above it
            # (else the year's pay is counted twice)
            for i, b in enumerate(blocks):
                rest = sum(gross(o) for j, o in enumerate(blocks) if j != i)
                if rest >= 1 and abs(gross(b) - rest) < 1:
                    blocks = [(None, b[1])] + [o for j, o in enumerate(blocks) if j != i]
                    break
        company = blocks[0] if blocks[0][0] is None else None
        people = [b for b in blocks if b[0] is not None]
        if company and people:
            if abs(gross(company) - sum(gross(p) for p in people)) >= 1:
                people = []                          # the people do not add up: keep the company's months
        kept = people or ([(None, company[1])] if company else blocks)
        # The employment allowance: from the people kept, else the company's months
        allowance: Dict[date, float] = {}
        for source in (kept, [company] if company else []):
            for _, months in source:
                for when, v in months.items():
                    if abs(v.get("allowance", 0.0)) >= 0.005:
                        allowance[when] = allowance.get(when, 0.0) + v["allowance"]
            if allowance:
                break
        cls._store_allowance(engagement_id, allowance, db)
        # The headcount: the company's months (a person's block has none to add up)
        source = company[1] if company else (blocks[0][1] if len(blocks) == 1 else {})
        heads_by_month = {when: v["headcount"] for when, v in source.items() if v.get("headcount")}
        year_average = cls._average_employees(rows)
        cls._store_headcount(engagement_id, heads_by_month, year_average, db)

        fields = ("gross_pay", "tax_deducted", "employee_nic", "employer_nic", "student_loan",
                  "pension_employee", "pension_employer", "net_pay", "statutory_pay_recovered")
        db.query(PayrollP32Record).filter(PayrollP32Record.engagement_id == engagement_id).delete(synchronize_session=False)
        count = 0
        for person, months in kept:
            for when, v in sorted(months.items()):
                values = {f: round(v.get(f, 0.0), 2) for f in fields}
                due = v.get("total_hmrc_due")
                db.add(PayrollP32Record(
                    engagement_id=engagement_id,
                    tax_month_label=when.strftime("%b %Y"),
                    period_end=when,
                    employee_name=person or "All employees",
                    total_hmrc_due=round(due if due is not None else
                                         values["tax_deducted"] + values["employee_nic"] + values["employer_nic"]
                                         + values["student_loan"], 2),
                    **values,
                ))
                count += 1
        db.commit()
        return count

    @classmethod
    def _parse_brightpay(cls, engagement_id: str, rows: List[List[str]], header_idx: int, db: Session) -> int:
        """One record per employee per pay period. The report's TOTAL lines and year summary are skipped,
        and uploading a report again replaces the pay periods it covers."""
        cols = {c.strip().lower(): i for i, c in enumerate(rows[header_idx])}

        def cell(row: List[str], name: str) -> str:
            i = cols.get(name)
            return row[i].strip() if i is not None and i < len(row) else ""

        def amount(text: str) -> float:
            try:
                return float(text.replace("£", "").replace(",", "")) if text else 0.0
            except ValueError:
                return 0.0

        def ending(first: str) -> Optional[date]:
            period = BRIGHTPAY_PERIOD.match(first)
            return pd.to_datetime(period.group(1) or period.group(2), dayfirst=True).date() if period else None

        # The first period's line can sit above the headings
        period_end = next((ending(r[0].strip()) for r in reversed(rows[:header_idx]) if r and ending(r[0].strip())), None)
        net_column = next(n for n in BRIGHTPAY_NET if n in cols)
        lines = []
        for row in rows[header_idx + 1:]:
            first = row[0].strip() if row else ""
            if ending(first):
                period_end = ending(first)
                continue
            if first.lower().startswith(("months ", "weeks ")) or "summary" in first.lower():
                period_end = None  # the year summary repeats the months above
                continue
            # The name is the 'Name' column (a works number can come first); a line with no name is a total
            name = " ".join(p for p in (cell(row, "name"), cell(row, "surname")) if p)
            if period_end is None or not first or not name or first.lower().startswith("total") or name.lower().startswith("total"):
                continue
            values = {field: amount(cell(row, col)) for col, field in BRIGHTPAY_COLUMNS.items() if col != "net pay"}
            values["net_pay"] = amount(cell(row, net_column))
            lines.append((period_end, name, values))

        if not lines:
            return 0
        periods = {p for p, _, _ in lines}
        db.query(PayrollP32Record).filter(
            PayrollP32Record.engagement_id == engagement_id,
            PayrollP32Record.period_end.in_(periods),
        ).delete(synchronize_session=False)
        for period_end, name, v in lines:
            db.add(PayrollP32Record(
                engagement_id=engagement_id,
                tax_month_label=period_end.strftime("%b %Y"),
                period_end=period_end,
                employee_name=name,
                total_hmrc_due=round(v["tax_deducted"] + v["employee_nic"] + v["employer_nic"] + v["student_loan"], 2),
                **v,
            ))
        db.commit()
        return len(lines)

    @classmethod
    def _parse_payroll(cls, engagement_id: str, df: pd.DataFrame, db: Session) -> int:
        """Reads plain payroll P32 rows. A payroll summary covers the year: a new upload replaces the earlier summary
        (the BrightPay monthly lines, which carry their month, are replaced month by month instead)."""
        records_added = 0
        year_allowance = 0.0
        year_heads: List[float] = []
        db.query(PayrollP32Record).filter(PayrollP32Record.engagement_id == engagement_id,
                                          PayrollP32Record.period_end.is_(None)).delete(synchronize_session=False)
        
        # Search for monthly or summary rows
        header_idx = -1
        for idx, row in df.iterrows():
            row_str = " ".join([str(v).lower() for v in row.values if pd.notna(v)])
            if any(k in row_str for k in ["gross", "paye", "pension"]) or re.search(r"\bnics?\b", row_str):
                header_idx = idx
                break
        
        if header_idx != -1:
            df.columns = [str(c).strip().lower() for c in df.iloc[header_idx]]
            data_df = df.iloc[header_idx + 1:].copy()
        else:
            data_df = df.copy()

        # A line with nothing in its label column (the Month / Period / Name column, else the first), below lines that
        # have a month or a name there, is a total
        first_col = next((c for c in data_df.columns if re.fullmatch(r"months?|period|pay period|name|employee", str(c).strip())),
                         data_df.columns[0] if len(data_df.columns) else None)
        labelled = first_col is not None and data_df[first_col].notna().any()
        for _, row in data_df.iterrows():
            if labelled and pd.isna(row[first_col]):
                continue
            label = ""
            for col in data_df.columns:
                col_name = str(col).lower()
                if any(k in col_name for k in ["month", "period", "tax period", "quarter"]):
                    if pd.notna(row[col]):
                        label = str(row[col]).strip()
                        break

            if not label:
                label = "Annual Payroll Summary"
            # The year's total line repeats the months above it
            if any(str(v).strip().lower().startswith(("total", "grand total", "year to date", "ytd"))
                   for v in row.values if pd.notna(v)):
                continue

            def get_num(patterns: List[str]) -> float:
                for col in data_df.columns:
                    col_name = str(col).lower()
                    if any(p in col_name for p in patterns):
                        val = row[col]
                        if pd.notna(val):
                            try:
                                return float(str(val).replace("£", "").replace(",", "").strip())
                            except ValueError:
                                pass
                return 0.0

            gross = get_num(["gross", "taxable pay"])
            paye = get_num(["paye", "tax deducted", "income tax"])
            emp_nic = get_num(["employee nic", "ee nic", "primary nic", "employee ni", "ee ni"])
            er_nic = get_num(["employer nic", "er nic", "secondary nic", "employer ni", "er ni"])
            pension_er = get_num(["employer pension", "er pension"])
            pension_ee = get_num(["employee pension", "ee pension"])
            total_hmrc = get_num(["hmrc", "total due", "net payment"]) or (paye + emp_nic + er_nic)
            # Net pay as a 'Payroll Summary' heading names it ('Net wages', 'Take-home pay'; not 'Net wages payment')
            heads = {str(c): cls._summary_field(str(c)) for c in data_df.columns}
            net_col = (next((c for c in data_df.columns if heads[str(c)] == "take_home"), None)
                       or next((c for c in data_df.columns if heads[str(c)] == "net_pay"), None))
            net = get_num([str(net_col).lower()]) if net_col is not None else 0.0
            head_col = next((c for c in data_df.columns if heads[str(c)] == "headcount"), None)
            if head_col is not None and gross > 0:
                year_heads.append(get_num([str(head_col).lower()]))
            allow_col = next((c for c in data_df.columns if heads[str(c)] == "allowance"), None)
            if allow_col is not None and gross > 0:
                year_allowance += get_num([str(allow_col).lower()])

            if gross > 0 or total_hmrc > 0:
                payroll_rec = PayrollP32Record(
                    engagement_id=engagement_id,
                    tax_month_label=label,
                    gross_pay=gross,
                    tax_deducted=paye,
                    employee_nic=emp_nic,
                    employer_nic=er_nic,
                    pension_employee=pension_ee,
                    pension_employer=pension_er,
                    net_pay=net,
                    total_hmrc_due=total_hmrc,
                )
                db.add(payroll_rec)
                records_added += 1

        db.commit()
        cls._store_allowance(engagement_id, {None: year_allowance}, db)
        heads = [h for h in year_heads if h > 0]
        cls._store_headcount(engagement_id, {}, round(sum(heads) / len(heads), 2) if heads else None, db)
        return records_added
