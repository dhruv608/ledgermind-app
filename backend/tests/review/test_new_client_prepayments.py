"""Firm setting for prepayments of a client with none last year: empty = ask, 0 = post every one, an amount = from it."""
import json

from backend.app.core.database import SessionLocal
from backend.app.models.firm_settings import FirmSetting
from backend.app.services.review.adjustments import firm_new_client_prepayments


def test_setting_values():
    db = SessionLocal()
    try:
        db.query(FirmSetting).filter(FirmSetting.key == "new_client_prepayments").delete()
        db.commit()
        assert firm_new_client_prepayments(db) is None                      # not set: ask
        for value, want in ((0, 0.0), (250, 250.0), (None, None)):
            row = db.get(FirmSetting, "new_client_prepayments") or FirmSetting(key="new_client_prepayments")
            row.value = json.dumps({"amount": value})
            db.add(row)
            db.commit()
            assert firm_new_client_prepayments(db) == want
    finally:
        db.query(FirmSetting).filter(FirmSetting.key == "new_client_prepayments").delete()
        db.commit()
        db.close()


def test_stated_period_is_sure():
    """Post when LM is sure: the bill's own dates, the rates year or the month it names; not 'annual'."""
    from datetime import date
    from backend.app.services.sop.prepayments import period_is_stated, service_period
    paid = date(2025, 9, 1)
    assert period_is_stated(service_period("Insurance 01/09/2025 to 31/08/2026", paid)[2])
    assert period_is_stated(service_period("Business rates 2025/26", date(2025, 4, 2))[2])
    assert period_is_stated(service_period("Rent - Nov 2025", date(2025, 10, 25))[2])
    assert not period_is_stated(service_period("Annual software subscription", paid)[2])
    assert not period_is_stated("only payment this year to 'X': a yearly plan assumed")
