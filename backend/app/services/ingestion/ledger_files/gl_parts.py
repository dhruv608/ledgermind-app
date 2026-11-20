"""A general ledger split over several files (one export per quarter or month, as QuickBooks and Xero split a big
ledger). The parts are read the same way and joined into one ledger:

- an exact copy of a part (same bytes) is read once;
- every other part is kept, even one that looks like it predates the year: the TB sets the period, and dropping a part
  leaves the ledger short of the TB;
- the opening balances are the earliest part's (a later part's opening is the earlier part's closing).
"""

from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

def distinct_parts(files: List[Tuple[str, bytes, Any]]) -> List[Tuple[str, bytes, Any]]:
    """The parts with an exact copy left out (the first of each kept)."""
    seen, out = set(), []
    for f in files:
        if f[1] in seen:
            continue
        seen.add(f[1])
        out.append(f)
    return out


def join_parts(parts: List[pd.DataFrame], period_end: Optional[date]) -> pd.DataFrame:
    """One ledger from its parts in date order, with the earliest part's openings."""
    dated = []
    for df in parts:
        if df is None or df.empty or "Date" not in df.columns:
            continue
        first = pd.to_datetime(df["Date"], errors="coerce").min()
        dated.append((first if pd.notna(first) else pd.Timestamp.max, df))
    if not dated:
        return pd.DataFrame()
    dated.sort(key=lambda x: x[0])
    joined = pd.concat([df for _, df in dated], ignore_index=True)
    attrs: Dict[str, Any] = dict(dated[0][1].attrs)
    attrs["explicit_sides"] = all(df.attrs.get("explicit_sides") for _, df in dated)
    attrs["parts"] = len(dated)
    joined.attrs = attrs
    return joined


def read_parts(files: List[Tuple[str, bytes, Any]], read_one: Callable[[str, Any], pd.DataFrame],
               period_end: Optional[date]) -> pd.DataFrame:
    """Every part read with read_one(name, excel file) and joined; one part is returned as it is read."""
    files = distinct_parts(files)
    frames = [read_one(name, xl) for name, _, xl in files if xl is not None]
    if len(frames) == 1:
        return frames[0]
    return join_parts(frames, period_end)
