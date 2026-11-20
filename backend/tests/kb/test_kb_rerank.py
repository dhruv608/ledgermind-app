"""The law search's AI re-ranker and its all-words query."""
import backend.app.core.bedrock as bedrock
from backend.app.services.kb.store import _all_words, rerank

PIECES = [(11, "TSEM3041 Tax rates", "Trust rate 45%..."), (12, "EIM31240 Approved mileage rates", "55 pence..."),
          (13, "BIM75005 Simplified expenses", "55p...")]


def test_reranker_puts_the_models_choice_first(monkeypatch):
    monkeypatch.setattr(bedrock.bedrock_ai, "invoke_model_reporting", lambda *a, **k: ("[1, 2]", "m"))
    assert rerank("mileage rate 2026-27", PIECES) == [12, 13, 11]


def test_reranker_keeps_the_search_order_when_the_model_fails(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no model")
    monkeypatch.setattr(bedrock.bedrock_ai, "invoke_model_reporting", boom)
    assert rerank("q", PIECES) == [11, 12, 13]
    monkeypatch.setattr(bedrock.bedrock_ai, "invoke_model_reporting", lambda *a, **k: ("[7, 0, 0]", "m"))
    assert rerank("q", PIECES) == [11, 12, 13]                      # out of range dropped, repeats once


def test_all_words_query():
    assert _all_words("ATED threshold value") == "ated & threshold & value"
    assert _all_words("Dividend tax rates 2026-27") == "dividend & tax & rates & 2026"
    assert _all_words("What is VAT?") == ""                           # one subject word: no all-words search
