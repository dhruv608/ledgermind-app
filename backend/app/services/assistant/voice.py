"""Voice questions: speech written out by AWS Transcribe (in our own AWS account in London, so nothing spoken leaves
it). The browser records the microphone and sends 16 kHz 16-bit mono PCM (no converter needed on the server).
Written out in Indian English only: one stream, so one charge a question. Hindi words come back in English letters
as best Transcribe can; the chat model reads them."""

import asyncio
from typing import List, Tuple

RATE = 16000
CHUNK = 8 * 1024                    # bytes a message (about a quarter of a second)
MAX_SECONDS = 120
REGION = "eu-west-2"
LANGUAGE = "en-IN"
LANGUAGES = (LANGUAGE,)          # the streams a question is charged for (the cost meter)
# Words of the trade, spelled as an accountant writes them
VOCAB_HINTS = {"vat": "VAT", "hmrc": "HMRC", "paye": "PAYE", "p sixty": "P60", "p forty five": "P45", "cis": "CIS"}


def _credentials():
    from amazon_transcribe.auth import StaticCredentialResolver
    from backend.app.core.config import settings
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        return StaticCredentialResolver(access_key_id=settings.AWS_ACCESS_KEY_ID,
                                        secret_access_key=settings.AWS_SECRET_ACCESS_KEY)
    return None                     # the server's AWS role


async def _stream(pcm: bytes, language: str) -> Tuple[str, float]:
    """(the words, how sure Transcribe is on average) in one language."""
    from amazon_transcribe.client import TranscribeStreamingClient
    from amazon_transcribe.handlers import TranscriptResultStreamHandler

    finals: List[str] = []
    sure: List[float] = []

    class Handler(TranscriptResultStreamHandler):
        async def handle_transcript_event(self, event):
            for r in event.transcript.results:
                if not r.is_partial and r.alternatives:
                    finals.append(r.alternatives[0].transcript)
                    sure.extend(i.confidence for i in r.alternatives[0].items if i.confidence is not None)

    creds = _credentials()
    client = TranscribeStreamingClient(region=REGION, credential_resolver=creds) if creds else TranscribeStreamingClient(region=REGION)
    stream = await client.start_stream_transcription(language_code=language, media_sample_rate_hz=RATE, media_encoding="pcm")

    async def feed():
        for i in range(0, len(pcm), CHUNK):
            await stream.input_stream.send_audio_event(audio_chunk=pcm[i:i + CHUNK])
        await stream.input_stream.end_stream()

    await asyncio.gather(feed(), Handler(stream.output_stream).handle_events())
    text = " ".join(x.strip() for x in finals if x.strip())
    return text, (sum(sure) / len(sure) if sure else 0.0)


def tidy(text: str) -> str:
    import re
    for said, written in VOCAB_HINTS.items():
        text = re.sub(rf"\b{said}\b", written, text, flags=re.I)
    return text.strip()


def transcribe_pcm(pcm: bytes) -> str:
    """The words in 16 kHz 16-bit mono PCM audio (up to MAX_SECONDS), in English."""
    pcm = pcm[: RATE * 2 * MAX_SECONDS]
    if len(pcm) % 2:
        pcm = pcm[:-1]
    return tidy(asyncio.run(_stream(pcm, LANGUAGE))[0])
