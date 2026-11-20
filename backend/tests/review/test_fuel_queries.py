"""DL-07 fuel with no company vehicle, DL-08 fuel and mileage both paid. Made-up job."""
import os
from datetime import date
from types import SimpleNamespace as N

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.queries.tb_rules import fuel_queries

CHART = {3081: N(std_name="Travel and subsistence expenses (Employee costs)", financial_class="Profit and Loss"),
         3082: N(std_name="Mileage allowance", financial_class="Profit and Loss"),
         4130: N(std_name="Motor vehicles - cost", financial_class="Balance Sheet")}


def L(code, account, desc, dr):
    return N(code=code, account=account, description=desc, debit=dr, credit=0.0, source="Expense", when=date(2024, 6, 1),
             reference="")


def test_fuel_with_no_vehicle_and_mileage():
    tb = [N(std_code=3081, net_amount=900.0, opening_amount=None, raw_account_name="Travel"),
          N(std_code=3082, net_amount=1200.0, opening_amount=None, raw_account_name="Mileage claims")]
    lines = [L(3081, "Travel", "Shell garage - fuel", 450.0), L(3081, "Travel", "Esso - petrol", 450.0)]
    refs = {q["ref"] for q in fuel_queries(CHART, tb, lines)}
    assert refs == {"DL-07", "DL-08"}


def test_fuel_with_a_company_vehicle_is_not_asked():
    tb = [N(std_code=3081, net_amount=900.0, opening_amount=None, raw_account_name="Travel"),
          N(std_code=4130, net_amount=15000.0, opening_amount=15000.0, raw_account_name="Van")]
    assert fuel_queries(CHART, tb, [L(3081, "Travel", "Diesel", 900.0)]) == []


def test_small_fuel_is_not_asked():
    tb = [N(std_code=3081, net_amount=90.0, opening_amount=None, raw_account_name="Travel")]
    assert fuel_queries(CHART, tb, [L(3081, "Travel", "Petrol", 90.0)]) == []
