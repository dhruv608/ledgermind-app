"""Cleaning a raw trial balance or general ledger (Xero, QuickBooks, Sage, QuickBooks classic layout) into the app's
columns."""

import re
from datetime import date, datetime
from typing import Any, Dict, List

import pandas as pd

from backend.app.services.ingestion.ledger_files.common import (
    CREDIT_SIDE_NAME, DEBIT_SIDE_NAME, FIRM_CODE_HEADING, VAT_CODE_HEAD, _qb_vat_amount, _unique_headers, firm_code_of,
)


class LedgerCleaning:
    """Cleaning a raw trial balance or general ledger (Xero, QuickBooks, Sage, QuickBooks classic layout) into the
    app's columns. Mixed into IngestionService."""

    @staticmethod
    def _clean_xero_tb(raw_df: pd.DataFrame) -> pd.DataFrame:
        header_idx = None
        for i in range(min(15, len(raw_df))):
            row_vals = [str(v).lower() for v in raw_df.iloc[i].values if pd.notna(v)]
            # The account column is headed Account / Name, or just 'Description' ('Description | Debit | Credit')
            if (any("account" in v or "name" in v or v.strip() == "description" for v in row_vals)) and (any("debit" in v or "credit" in v or "balance" in v or "check" in v or "ytd" in v for v in row_vals)):
                header_idx = i
                break

        if header_idx is None:
            header_idx = 4 if len(raw_df) > 4 else 0

        headers, repeated = _unique_headers([str(c).strip() for c in raw_df.iloc[header_idx].values])
        df = raw_df.iloc[header_idx + 1:].copy()
        df.columns = headers
        df = df.dropna(how="all")

        code_col = next((c for c in df.columns if "code" in str(c).lower()), None)
        name_col = next((c for c in df.columns if ("account" in str(c).lower() and "code" not in str(c).lower() and "type" not in str(c).lower()) or "name" in str(c).lower() or "description" in str(c).lower()), None)
        debit_col = next((c for c in df.columns if "debit" in str(c).lower() or "dr" == str(c).lower()), None)
        credit_col = next((c for c in df.columns if "credit" in str(c).lower() or "cr" == str(c).lower()), None)
        balance_col = next((c for c in df.columns if "balance" in str(c).lower() or "net" in str(c).lower() or "ytd" in str(c).lower()), None)
        type_col = next((c for c in df.columns if "type" in str(c).lower()), None)
        # The firm's code beside the client's own ('Taxcalc Code', 'Final code'): the firm's coding of each account
        firm_col = next((c for c in df.columns if c != code_col and FIRM_CODE_HEADING.search(str(c))), None)

        # A file that writes credits with a minus sign in the Credit column (Sales: Debit 0, Credit -49,501.79): every
        # amount in that column is negative. Read as debit - credit they would turn credits into debits; their size is
        # the credit. One odd negative in a usual file is kept
        def _num(v):
            try:
                return float(str(v).replace(",", "").replace("£", "").strip())
            except (ValueError, TypeError):
                return None
        credits_signed = False
        if credit_col:
            seen = [x for x in (_num(v) for v in df[credit_col] if pd.notna(v)) if x is not None and abs(x) >= 0.005]
            credits_signed = len(seen) >= 2 and all(x < 0 for x in seen)

        # An extended TB under a two-line heading: column groups on the first line ('Opening balances | Journals |
        # Final Trial Balance'), 'Debit | Credit | Balance' on the second. The year-end figure is the last group: its
        # Balance column, else its Debit and Credit (not the first two figures on each line, which are the opening and
        # the journals)
        final_cols = None
        if header_idx + 1 < len(raw_df):
            sub = [str(v).strip().lower() if pd.notna(v) else "" for v in raw_df.iloc[header_idx + 1].values]
            top = " ".join(str(v).lower() for v in raw_df.iloc[header_idx].values if pd.notna(v))
            dr_pos = [i for i, v in enumerate(sub) if v.startswith(("debit", "dr"))]
            cr_pos = [i for i, v in enumerate(sub) if v.startswith(("credit", "cr"))]
            bal_pos = [i for i, v in enumerate(sub) if v.startswith("balance")]
            if dr_pos and cr_pos and "debit" not in top and "credit" not in top:
                if bal_pos and max(bal_pos) > max(cr_pos):
                    final_cols = ("balance", max(bal_pos), None)
                else:
                    final_cols = ("pair", max(dr_pos), max(cr_pos))

        res_rows = []
        for _, r in df.iterrows():
            c_val = str(r[code_col]).strip() if code_col and pd.notna(r[code_col]) else ""
            n_val = str(r[name_col]).strip() if name_col and pd.notna(r[name_col]) else ""
            
            # If no name_col, fallback to column 0
            if not n_val and not c_val:
                n_val = str(r.iloc[0]).strip() if pd.notna(r.iloc[0]) else ""

            if c_val and n_val and c_val != "nan" and n_val != "nan":
                full_name = f"{c_val} - {n_val}"
            elif n_val and n_val != "nan":
                full_name = n_val
            elif c_val and c_val != "nan":
                full_name = c_val
            else:
                continue

            fn_lower = full_name.lower()
            # The TB's final "Total" line ends the accounts; anything below it is a footer, such as Xero's
            # exchange-rate note ("1.14568 EUR (Euro)"). Section subtotals ("Total Revenue") are only skipped.
            if re.fullmatch(r"(grand\s+)?total", fn_lower.strip(" :")):
                break
            if (
                not full_name
                or fn_lower.startswith("total")
                or "grand total" in fn_lower
                or fn_lower == "nan"
                or fn_lower.startswith("accrual basis")
                or fn_lower.startswith("cash basis")
                or "gmt+" in fn_lower
                or "gmt-" in fn_lower
                or fn_lower.startswith("page ")
                or fn_lower.startswith("printed ")
                or (re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", fn_lower) and ("am" in fn_lower or "pm" in fn_lower))
            ):
                continue

            debit = 0.0
            credit = 0.0
            net = 0.0

            if debit_col and pd.notna(r.get(debit_col)):
                try:
                    debit = float(str(r[debit_col]).replace(",", "").replace("£", "").strip())
                except (ValueError, TypeError):
                    debit = 0.0

            if credit_col and pd.notna(r.get(credit_col)):
                try:
                    credit = float(str(r[credit_col]).replace(",", "").replace("£", "").strip())
                except (ValueError, TypeError):
                    credit = 0.0
                if credits_signed:
                    credit = abs(credit)

            if balance_col and pd.notna(r.get(balance_col)):
                try:
                    net = float(str(r[balance_col]).replace(",", "").replace("£", "").strip())
                except (ValueError, TypeError):
                    net = round(debit - credit, 2)
            else:
                net = round(debit - credit, 2)
            # Extended TB: the first Debit / Credit pair is the opening balance; the first Balance column is the
            # final one (opening plus the year's movements), so debit and credit follow it
            if repeated and balance_col:
                debit, credit = (net, 0.0) if net >= 0 else (0.0, -net)
            # ...or, under a two-line heading, the last group's figures (above)
            if final_cols is not None:
                at = lambda i: (_num(r.iloc[i]) if i < len(r) and pd.notna(r.iloc[i]) else None) or 0.0
                if final_cols[0] == "balance":
                    net = round(at(final_cols[1]), 2)
                else:
                    net = round(at(final_cols[1]) - abs(at(final_cols[2])), 2)
                debit, credit = (net, 0.0) if net >= 0 else (0.0, -net)

            # Fallback if no explicit debit/credit column found
            if final_cols is None and not debit_col and not credit_col and (debit == 0.0 and credit == 0.0 and net == 0.0):
                nums = []
                for v in r.values[1:]:
                    if pd.isna(v):
                        continue
                    try:
                        val = float(str(v).replace(",", "").replace("£", "").strip())
                        nums.append(val)
                    except (ValueError, TypeError):
                        continue
                if len(nums) >= 2:
                    debit = nums[0]
                    # A negative second figure is a credit written with its minus sign (a two-line heading the
                    # columns were not found under: Sales 0 | -49,501.79), not a debit
                    credit = abs(nums[1]) if nums[1] < 0 else nums[1]
                    net = round(debit - credit, 2)
                elif len(nums) == 1:
                    net = nums[0]
                    if net >= 0:
                        debit = net
                    else:
                        credit = abs(net)

            debit = 0.0 if pd.isna(debit) else float(debit)
            credit = 0.0 if pd.isna(credit) else float(credit)
            net = 0.0 if pd.isna(net) else float(net)

            acc_type = str(r[type_col]).strip() if type_col and pd.notna(r[type_col]) else None

            res_rows.append({
                "raw_account_name": full_name,
                "account_type": acc_type,
                "debit": debit,
                "credit": credit,
                "net": net,
                "firm_code": firm_code_of(r[firm_col]) if firm_col else None,
            })

        return pd.DataFrame(res_rows)

    @staticmethod
    def _clean_universal_gl(raw_df: pd.DataFrame, source_system: str) -> pd.DataFrame:
        """Universal parser for both Xero and QuickBooks General Ledger files."""
        header_idx = None
        for i in range(min(15, len(raw_df))):
            row_vals = [str(v).lower() for v in raw_df.iloc[i].values if pd.notna(v)]
            if ("date" in row_vals or "transaction date" in row_vals) and ("debit" in row_vals or "credit" in row_vals or "amount" in row_vals or "description" in row_vals):
                header_idx = i
                break

        if header_idx is None:
            return raw_df.dropna(how="all")

        headers = [str(c).strip() for c in raw_df.iloc[header_idx].values]
        lower_headers = {h.lower() for h in headers}
        if "transaction type" in lower_headers and "distribution account" not in lower_headers:
            return LedgerCleaning._clean_quickbooks_classic_gl(raw_df, header_idx, headers)
        df = raw_df.iloc[header_idx + 1:].copy()
        df.columns = _unique_headers(headers)[0]

        current_account = ""
        clean_rows = []
        opening_balances: Dict[str, float] = {}
        # QuickBooks: account headings still open, parent first. A sub-account sits under its parent's heading
        # until 'Total for <parent> with sub-accounts', and is named 'Parent:Child' as in the trial balance
        # ('Residential Property:Rent receivables'), so two sub-accounts with the same name stay apart.
        open_headings: List[str] = []

        is_qb = any("distribution account" in h.lower() for h in headers) or source_system == "QUICKBOOKS"

        for _, r in df.iterrows():
            if is_qb:
                # QuickBooks structure
                dist_acc = str(r.get("Distribution account", "")).strip() if pd.notna(r.get("Distribution account")) else ""
                col0 = str(r.iloc[0]).strip() if pd.notna(r.iloc[0]) and str(r.iloc[0]) != "nan" else ""
                if col0 and not dist_acc:
                    closing = re.match(r"total for (.+?)(?: with sub-accounts)?$", col0, re.IGNORECASE)
                    if closing:
                        name = closing.group(1).strip()
                        if name in open_headings:
                            del open_headings[open_headings.index(name):]
                    else:
                        open_headings.append(col0)
                    current_account = ":".join(open_headings)
                    continue

                if dist_acc.lower() == "beginning balance":
                    try:
                        opening_balances[current_account] = float(str(r.get("Balance")).replace(",", "").replace("£", "").strip())
                    except (TypeError, ValueError):
                        pass
                    continue
                
                amt = r.get("Amount")
                if pd.isna(amt) or str(amt).lower() in ["nan", ""]:
                    continue

                try:
                    amount_val = float(str(amt).replace(",", "").replace("£", "").strip())
                except:
                    continue

                dr = amount_val if amount_val > 0 else 0.0
                cr = abs(amount_val) if amount_val < 0 else 0.0

                # Empty cells come through as NaN, which counts as filled in an 'or': read them as blank
                text = lambda v: str(v).strip() if pd.notna(v) else ""
                clean_rows.append({
                    "Date": r.get("Transaction date"),
                    "Source": text(r.get("Transaction type")) or "GL",
                    # Payee and memo, as the older QuickBooks layout: 'Acme Supplies - Invoice 123'
                    "Description": " - ".join(p for p in (text(r.get("Name")), text(r.get("Description"))) if p),
                    "Reference": text(r.get("No.")),
                    # The payee / customer and the other side of the entry, kept as their own columns too (Name and
                    # Split on the GL and the K tabs)
                    "Name": text(r.get("Name")) or None,
                    "Split": next((text(v) for k, v in r.items() if str(k).strip().lower() in ("split", "split account")
                                   and pd.notna(v) and text(v)), None),
                    "Tracking": " / ".join(t for t in (text(r.get("Class")), text(r.get("Location"))) if t),
                    "Debit": dr,
                    "Credit": cr,
                    "Parent_Account": (current_account if open_headings and open_headings[-1].lower() == dist_acc.lower()
                                       else dist_acc or current_account),
                    # A line in another currency, whatever the export's capitals
                    **{name: next((v for k, v in r.items() if str(k).strip().lower() == name.lower() and pd.notna(v)), None)
                       for name in ("Exchange Rate", "Foreign Amount", "Currency")},
                    # The VAT columns when the export has them (every line keeps its VAT code and amount), whatever
                    # the export calls them
                    "VAT": _qb_vat_amount(r),
                    "VAT Code": next((text(v) for k, v in r.items() if VAT_CODE_HEAD.match(str(k).strip()) and pd.notna(v)),
                                     None),
                })
            else:
                # Xero structure
                first_val = str(r.get("Date", "")).strip() if pd.notna(r.get("Date")) else ""
                if first_val.lower() == "opening balance":
                    try:
                        opening_balances[current_account] = float(r.get("Debit") or 0) - float(r.get("Credit") or 0)
                    except (TypeError, ValueError):
                        pass
                    continue
                # Account header line: '- Rent' / 'Rent' / '0000 - Sales' with no amounts
                if first_val.startswith("- ") or (pd.isna(r.get("Debit")) and pd.isna(r.get("Credit")) and first_val and not LedgerCleaning._is_date_value(r.get("Date"))):
                    current_account = first_val.lstrip("- ").strip()
                    continue
                
                has_debit = pd.notna(r.get("Debit"))
                has_credit = pd.notna(r.get("Credit"))
                if (has_debit or has_credit) and LedgerCleaning._is_date_value(r.get("Date")):
                    row_dict = r.to_dict()
                    row_dict["Parent_Account"] = current_account
                    clean_rows.append(row_dict)

        result = pd.DataFrame(clean_rows) if clean_rows else raw_df.dropna(how="all")
        result.attrs["opening_balances"] = opening_balances
        return result

    @staticmethod
    def _clean_quickbooks_classic_gl(raw_df: pd.DataFrame, header_idx: int, headers: List[str]) -> pd.DataFrame:
        """QuickBooks general ledger in the older layout: the account is repeated in the first column of every line,
        the second column holds the account heading or 'Total for ...', and the columns are Date, Transaction Type,
        No., Name, Memo/Description, Split, Amount, Balance, Debit, Credit.
        Sub-accounts are indented under the last un-indented account above them, and are named 'Parent:Child'
        (e.g. 'Sales:J Smith' and 'Sub-Contractors:J Smith' are two different accounts)."""
        col = {h.lower(): i for i, h in enumerate(headers) if h and h.lower() != "nan"}
        # Newer exports name the date 'Transaction date'
        if "date" not in col and "transaction date" in col:
            col["date"] = col["transaction date"]

        def value(row: List[Any], name: str) -> Any:
            i = col.get(name)
            v = row[i] if i is not None and i < len(row) else None
            return None if v is None or (isinstance(v, float) and v != v) else v

        def amount(v: Any) -> float:
            try:
                return float(str(v).replace(",", "").replace("£", "").strip()) if v is not None else 0.0
            except ValueError:
                return 0.0

        # Debit and Credit columns, or only a signed Amount ('this account went up'), turned to sides against the TB
        sides_given = "debit" in col or "credit" in col
        rows, opening_balances = [], {}
        pending_opening: Dict[str, float] = {}   # natural-sign opening, until a line shows the account's side
        parent = heading = ""
        for raw in raw_df.iloc[header_idx + 1:].values.tolist():
            first = raw[0] if isinstance(raw[0], str) else ""
            when = value(raw, "date")
            listed = value(raw, "account")
            listed = str(listed).strip() if listed is not None else ""
            beginning = any(str(v).strip().lower() == "beginning balance" for v in (when, listed) if v is not None)
            if first.strip():
                indented = first != first.lstrip()
                if not indented:
                    parent = first.strip()
                account = heading = f"{parent}:{first.strip()}" if indented and parent else first.strip()
            else:
                # Newer exports leave the first column blank on the lines: the account is in the 'Account' column,
                # or is the heading above the lines (the line for the opening balance never names it)
                account = listed if listed and not beginning else heading
            if not account:
                continue
            if beginning:
                pending_opening[account] = amount(value(raw, "balance"))
                continue
            if when is None:
                continue  # heading or 'Total for ...' line
            if sides_given:
                debit, credit = amount(value(raw, "debit")), amount(value(raw, "credit"))
            else:
                signed = amount(value(raw, "amount"))
                debit, credit = max(signed, 0.0), max(-signed, 0.0)
            if not debit and not credit:
                continue
            started = account if account in pending_opening else heading if heading in pending_opening else None
            if started is not None:
                # The running balance shows which side the account keeps its balance on
                start, after = pending_opening.pop(started), amount(value(raw, "balance"))
                credit_side = abs(after - (start + credit - debit)) < abs(after - (start + debit - credit))
                opening_balances[account] = -start if credit_side else start
            name, memo = value(raw, "name"), value(raw, "memo/description")
            rows.append({
                "Date": pd.to_datetime(when, dayfirst=True, errors="coerce"),
                "Source": value(raw, "transaction type") or "GL",
                "Description": " - ".join(str(p).strip() for p in (name, memo) if p is not None and str(p).strip()),
                "Reference": value(raw, "no.") or "",
                # The payee / customer and the other side of the entry as their own columns
                "Name": str(name).strip() if name is not None and str(name).strip() else None,
                "Split": next((str(v).strip() for v in (value(raw, "split"), value(raw, "split account"))
                               if v is not None and str(v).strip()), None),
                "Tracking": " / ".join(str(t).strip() for t in (value(raw, "class"), value(raw, "location")) if t),
                "VAT": (amount(value(raw, "vat amount")) if value(raw, "net amount") is not None
                        and abs(abs(debit - credit) - abs(amount(value(raw, "net amount")))) < 0.01
                        and value(raw, "vat code") is not None else None),
                "VAT Code": value(raw, "vat code"),
                "Debit": debit,
                "Credit": credit,
                "Parent_Account": account,
                # A line in another currency: its rate and own amount, kept beside the line
                "Exchange Rate": value(raw, "exchange rate"),
                "Foreign Amount": value(raw, "foreign amount"),
                "Currency": value(raw, "currency"),
            })
        # Accounts with an opening balance and no lines this year: no line shows their side, and QuickBooks gives the
        # balance as on the balance sheet (liabilities and equity positive), so those turn to credits (negative).
        # Assets, including accumulated depreciation (already negative), keep their sign.
        for account, start in pending_opening.items():
            leaf = account.split(":")[-1]
            opening_balances[account] = -start if CREDIT_SIDE_NAME.search(leaf) and not DEBIT_SIDE_NAME.search(leaf) else start
        LedgerCleaning._balance_guessed_openings(opening_balances, [a for a in pending_opening if opening_balances.get(a)])
        result = pd.DataFrame(rows)
        result.attrs["opening_balances"] = opening_balances
        result.attrs["explicit_sides"] = sides_given  # debits and credits are given, no need to orient against the TB
        return result

    @staticmethod
    def _balance_guessed_openings(opening: Dict[str, float], guessed: List[str]) -> List[str]:
        """Last year's closing balances add up to zero. When they do not, the sides guessed from account names (accounts
        with no lines this year, e.g. 'CIS Withheld', '... - drawings') are the doubt: turn the fewest of them so the
        total is zero. Returns the accounts turned (nothing changes when no combination balances)."""
        from itertools import combinations
        total = round(sum(opening.values()), 2)
        if abs(total) < 0.01 or not guessed:
            return []
        candidates = sorted(guessed, key=lambda a: -abs(opening[a]))[:16]
        for size in range(1, min(len(candidates), 4) + 1):
            for combo in combinations(candidates, size):
                if abs(total - 2 * sum(opening[a] for a in combo)) < 0.01:
                    for a in combo:
                        opening[a] = -opening[a]
                    return list(combo)
        return []

    @staticmethod
    def _is_date_value(value: Any) -> bool:
        if isinstance(value, (datetime, date, pd.Timestamp)):
            return True
        return bool(re.match(r"^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$", str(value).strip()))
