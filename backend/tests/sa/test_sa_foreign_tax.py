"""Foreign tax documents (made-up): sorted as one, read as a point, another person's left out (R-SA106-05, -07)."""

from backend.app.sa.extract import foreign_tax as F
from backend.app.sa.extract.classify import classify


def test_sorted_and_read():
    assert classify("SARS ITA34 Notice of assessment", "scan.pdf") == "FOREIGN_TAX"
    assert classify("Avis d'impôt sur le revenu 2025", "letter.pdf") == "FOREIGN_TAX"
    assert classify("", "Pollard NZ Tax - 2026 - IR3NR.pdf") == "FOREIGN_TAX"
    f = F.clean({"country": "zaf", "period_from": "2025-03-01", "period_to": "2026-02-28", "currency": "ZAR",
                 "income": [{"kind": "pension", "amount": "120,000"}], "tax": 18000})
    status, notes = F.checks(f, "2025-26", "Chris Example")
    assert status == "CHECK" and "R-SA106-05" in notes[0] and F.summary(f) == "ZAF ZAR pension 120,000.00"
    g = F.clean({"person": "Alex Other", "income": []})
    assert F.checks(g, "2025-26", "Chris Example")[0] == "CHECK" and g["other_person"]
