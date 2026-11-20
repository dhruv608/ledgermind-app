"""Pages with no law in them are kept out of the law base (they only crowd real answers out of a search)."""
from backend.app.services.kb.store import is_placeholder

W = "(This content has been withheld because of exemptions in the Freedom of Information Act 2000)"


def test_placeholder_pages():
    assert is_placeholder(W)
    assert is_placeholder(f"{W} - {W} {W} - {W}")
    assert is_placeholder("This page has been archived information is now included within TSEM5220, 5300 and 5350.")
    assert is_placeholder("This is the archival message of the site")
    assert is_placeholder("This guidance has been withdrawn with effect from 30 June 2023. Please refer to ESM0500.")
    assert is_placeholder("Contents")
    assert is_placeholder("This chapter contains the following:")


def test_real_law_is_kept():
    assert not is_placeholder("The small pool limit is £1,000.")
    assert not is_placeholder(f"{W} The official rate from 6 April 2025 is 3.75%.")
    assert not is_placeholder("Contents of a VAT invoice: your name, address and VAT registration number.")
