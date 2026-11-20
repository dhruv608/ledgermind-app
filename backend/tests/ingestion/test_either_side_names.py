"""Names on either side by their balance: corporation tax as the year's charge or the tax owed, consulting as fees paid
or earned."""
from types import SimpleNamespace as N

from backend.app.services.mapping.mapping_parts.checks import MappingChecks

COA = {c: N(std_name=n, category="") for c, n in ((3800, "Corporation tax charge"), (5310, "Corporation tax"),
                                                   (3304, "Consultancy fees"), (440, "Other trading income"))}


def _run(name, code, net, opening=0.0, source="RULE"):
    r = {"std_code": code, "std_name": "", "match_source": source, "mapping_reason": ""}
    MappingChecks._either_side([{"name": name, "net": net, "opening": opening}], [r], COA)
    return r["std_code"]


def test_corporation_tax_charge_and_owed():
    assert _run("Corporation Tax", 5310, 14980.68) == 3800                 # the year's charge, nothing b/f
    assert _run("Corporation Tax", 3800, -16046.42) == 5310                # owed to HMRC
    assert _run("Corporation Tax", 5310, 2000.0, opening=-16046.42) == 5310  # last year's tax paid off: still owed side


def test_consulting_paid_or_earned_and_accountant_codes_kept():
    assert _run("Consulting", 440, 8200.0) == 3304
    assert _run("Consultancy income", 440, -9000.0) == 440                  # not an either-side name
    assert _run("Consulting", 440, 8200.0, source="MEMORY") == 440         # the accountant's own choice stays
