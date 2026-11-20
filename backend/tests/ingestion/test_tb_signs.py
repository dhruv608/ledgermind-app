"""C12: a TB whose whole P&L is the wrong way round (made as closing less opening) is warned on the Data check."""
import os
from types import SimpleNamespace as N

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.setup.extraction_checks import pl_reversed


class _Chart:
    SECTIONS = {0: "Sales", 410: "Sales", 3000: "Employee costs", 3304: "General admin", 4800: "Cash at bank"}

    def is_pl(self, code):
        return code < 4000

    def is_pre_tax_pl(self, code):
        return code < 4000

    def section(self, code):
        return self.SECTIONS.get(code)


def _t(code, net):
    return N(std_code=code, net_amount=net, opening_amount=None)


def test_reversed_pl_warned():
    # A movement TB made as closing less opening: income on the debit side, costs on the credit side
    tb = [_t(0, 60000.0), _t(410, 9000.0), _t(3000, -20000.0), _t(3304, -70000.0), _t(4800, 15000.0)]
    assert pl_reversed(tb, _Chart()) == (69000.0, 90000.0)


def test_normal_pl_not_warned():
    tb = [_t(0, -100000.0), _t(410, -500.0), _t(3000, 10000.0), _t(3304, 40000.0)]
    assert pl_reversed(tb, _Chart()) is None


def test_one_wrong_account_is_the_mapping_checks():
    # A refund or one wrong-side account: not the whole P&L
    tb = [_t(0, -50000.0), _t(410, 2000.0), _t(3000, 20000.0), _t(3304, -1500.0)]
    assert pl_reversed(tb, _Chart()) is None
