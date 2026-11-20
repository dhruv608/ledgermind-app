"""Rent found in the person's own bank (made-up payers): the payer's name from the bank line (R-SA105-01)."""

from backend.app.sa.property_bank import payer_of


def test_the_payer_from_the_line():
    assert payer_of("CR HULME JG RENT") == payer_of("HULME JG APRIL RENT") == "HULME JG"
    assert payer_of("ENTICOTT K RENT A SOMERS RD") == "ENTICOTT K A SOMERS RD"
    assert payer_of("Mateusz Tomf Rent") == "MATEUSZ TOMF"


def test_a_dividend_payer_from_the_line():
    from backend.app.sa.bank_dividends import payer_of as div_payer
    assert div_payer("CR C GREGORY AND CO DIVIDEND") == div_payer("C GREGORY AND CO DIVIDEND") == "C GREGORY AND CO"


def test_an_agents_statement_names_the_agent():
    # A performer's agent's statement (no account number): its payments into the bank are then the same money, net
    from types import SimpleNamespace as NS
    from backend.app.sa.books import _agent_words
    agent = NS(lines=[NS(description="From A Studio Ltd for recording", money_out=0.0),
                      NS(description="Less commission due to Bright Voices Management @ 15% + VAT", money_out=630.0)])
    bank = NS(lines=[NS(description="Less commission due to Some Bank Ltd @ 1%", money_out=5.0)])
    assert _agent_words([("file 12", None, agent), ("1357", "HSBC", bank)]) == {"bright", "voices"}
