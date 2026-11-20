"""The firm's standard fee (net) is accrued gross for a client confirmed as not VAT registered."""
import json
from types import SimpleNamespace as N

import backend.app.services.review.accrual_journals as aj

FIRM = "the firm's standard accountancy fee (Firm settings)"


def _run(monkeypatch, registered, confirmed):
    monkeypatch.setattr(aj, "_last_fee", lambda e, db, tb: (1000.0, FIRM))
    monkeypatch.setattr(aj, "_pays_monthly", lambda e, db, tb: False)
    profile = N(is_vat_registered=registered, confirmed_fields=json.dumps(["is_vat_registered"] if confirmed else []))
    return aj._new_fee(N(profile=profile), None, [])


def test_not_registered_confirmed_is_gross(monkeypatch):
    fee, source = _run(monkeypatch, False, True)
    assert fee == 1200.0 and "plus VAT" in source


def test_registered_or_unconfirmed_stays_net(monkeypatch):
    assert _run(monkeypatch, True, True) == (1000.0, FIRM)
    assert _run(monkeypatch, False, False) == (1000.0, FIRM)
