"""Voice questions are written out in English only: one Transcribe stream, so one charge."""
from backend.app.core import ai_usage
from backend.app.services.assistant import voice


def test_english_only_one_stream(monkeypatch):
    asked = []

    async def fake(pcm, language):
        asked.append(language)
        return "what is the vat threshold", 0.9

    monkeypatch.setattr(voice, "_stream", fake)
    assert voice.transcribe_pcm(b"\0" * 32000) == "what is the VAT threshold"
    assert asked == ["en-IN"] and voice.LANGUAGES == ("en-IN",)
    # The meter charges one stream: 10 seconds is billed as the 15-second minimum
    assert ai_usage.transcribe_cost(10, streams=len(voice.LANGUAGES)) == 15 * ai_usage.TRANSCRIBE_PER_SECOND
