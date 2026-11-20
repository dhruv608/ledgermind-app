"""A loan account's lender who is a person (FRS 102 s33): asked who they are; banks,
finance companies, overseas companies and platform customers are not people."""

from backend.app.services.sop.related_party import LENDER_WORDS, PERSON_NAME


def person(name: str) -> bool:
    return bool(PERSON_NAME.fullmatch(name)) and not LENDER_WORDS.search(name)


def test_people_are_asked_about():
    assert person("Ian Example") and person("Mr John Example") and person("Jane Mary Example")


def test_lenders_that_are_not_people():
    for name in ("Funding Circle", "Lloyds Bank", "Iwoca", "HMRC", "Amazon Capital Services", "Square Customer",
                 "Example Canada Inc", "Example Hungary Kft", "American Express", "Loan repayment", "Transfer"):
        assert not person(name), name


def test_names_with_inner_capitals_and_hyphens():
    for name in ("George McExample", "Sean O'Example", "Anna Smith-Example", "MacExample Ross"):
        assert person(name), name
    assert not person("George Repayment")
