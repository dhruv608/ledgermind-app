"""F-P platform clearing (e-commerce rules): which platform a bank line is from."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.workbook.platform_tab import TAKINGS, platform_of


def test_platforms_from_bank_text():
    assert platform_of("Amazon Sales - Amazon Services Europe S.a.r.L. - AMAZON PAYMENTS UK") == "Amazon"
    assert platform_of("SHOPIFY PAYMENTS UK") == "Shopify"
    assert platform_of("PAYPAL TRANSFER") == "PayPal"
    assert platform_of("Etsy Ireland UC") == "Etsy"
    assert platform_of("Tesco Stores") is None


def test_restaurant_providers():
    assert platform_of("DELIVEROO - ROOFOODS LTD", TAKINGS) == "Deliveroo"
    assert platform_of("UBER EATS UK", TAKINGS) == "Uber Eats"
    assert platform_of("SumUp Payments Limited", TAKINGS) == "SumUp"
    assert platform_of("PAYMENTSENSE", TAKINGS) == "Dojo"
    assert platform_of("Booker Wholesale", TAKINGS) is None


def test_booking_and_payer_providers():
    from backend.app.services.workbook.platform_tab import BOOKINGS, PAYERS
    assert platform_of("FRESHA.COM payout", BOOKINGS) == "Fresha"
    assert platform_of("NHSBSA PAYMENTS", PAYERS) == "NHS"
    assert platform_of("Leeds City Council", PAYERS) == "Council"
    assert platform_of("Starbucks", PAYERS) is None


def test_no_backspace_in_the_patterns():
    from pathlib import Path
    import backend.app.services.workbook.platform_tab as m
    assert chr(8) not in Path(m.__file__).read_text(encoding="utf-8")
