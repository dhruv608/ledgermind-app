"""Embed every knowledge base piece again with the model in the settings (KB_EMBED_PROVIDER / MODEL / DIMS), after
changing it: the vectors of two models cannot be compared, so all of them are redone. The pages are not fetched
again (the text is in the database).

    python backend/scripts/kb_reembed.py                          # with the settings' own region
    python backend/scripts/kb_reembed.py eu-west-2 us-east-1      # Bedrock: share the work between regions

The same Bedrock model gives the same vectors in every region, so a one-off run can use several regions' limits
(Titan takes one text per request, and one region's limit makes 10,000 pieces slow) while the live app embeds its
questions in its own region. The new vectors go into a new column; it replaces the old one only when every piece is
done, so a run that stops can simply be started again."""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from backend.app.core.config import settings  # noqa: E402
from backend.app.core.database import engine  # noqa: E402
from backend.app.services.kb import embed  # noqa: E402
from backend.app.services.kb.store import _vec, embedding_setting  # noqa: E402

BATCH = 500
DIMS = settings.KB_EMBED_DIMS


# Calls a second to start each region at (London throttles above ~1.5, us-east-1 above ~3 when quiet; less over a
# long run): each region slows down when AWS says 'too many requests' and speeds up again slowly
RATES = {"eu-west-2": 0.8, "us-east-1": 1.5}
DEFAULT_RATE = 0.8
MIN_RATE = 0.2
THROTTLE_RETRIES = 30


class Pace:
    """Lets calls through no faster than its rate a second; slower after a throttle, a little faster after each
    success (up to the starting rate)."""
    def __init__(self, rate: float):
        self.top, self.rate, self.next, self.lock = rate, rate, 0.0, Lock()

    def throttled(self) -> None:
        with self.lock:
            self.rate = max(MIN_RATE, self.rate * 0.7)

    def ok(self) -> None:
        with self.lock:
            self.rate = min(self.top, self.rate * 1.02)

    def wait(self) -> None:
        with self.lock:
            now = time.time()
            at = max(now, self.next)
            self.next = at + 1.0 / self.rate
        if at > now:
            time.sleep(at - now)


def bulk_embedder(regions):
    """embed_documents spread over several Bedrock regions, each paced below its limit (Titan: one text per
    request), retried on throttling and dropped connections."""
    if settings.KB_EMBED_PROVIDER != "bedrock" or "cohere" in settings.KB_EMBED_MODEL or not regions:
        return embed.embed_documents
    from backend.app.core.s3 import aws_client
    lanes = [(aws_client("bedrock-runtime", r), Pace(RATES.get(r, DEFAULT_RATE)), RATES.get(r, DEFAULT_RATE))
             for r in regions]
    passing = ("Throttl", "Could not connect", "Connect", "Timeout", "timed out", "ServiceUnavailable", "InternalServer")

    def one(lane, t):
        client, pace, _ = lane
        body = json.dumps({"inputText": t[:embed.TITAN_MAX_CHARS], "dimensions": DIMS, "normalize": True})
        for attempt in range(THROTTLE_RETRIES):
            pace.wait()
            try:
                r = client.invoke_model(modelId=settings.KB_EMBED_MODEL, body=body)
                pace.ok()
                return embed._normalise(json.loads(r["body"].read())["embedding"])
            except Exception as e:
                if not any(w in f"{type(e).__name__} {e}" for w in passing) or attempt == THROTTLE_RETRIES - 1:
                    raise
                pace.throttled()
                time.sleep(min(2 ** min(attempt, 5), 30))

    def run(texts):
        # Each region takes a share of the texts in proportion to its pace
        total = sum(rate for *_, rate in lanes)
        shares, start = [], 0
        for i, lane in enumerate(lanes):
            n = len(texts) - start if i == len(lanes) - 1 else round(len(texts) * lane[2] / total)
            shares.append((lane, list(range(start, start + n))))
            start += n
        out = [None] * len(texts)
        with ThreadPoolExecutor(sum(max(4, int(rate * 3)) for *_, rate in lanes)) as pool:
            jobs = [(i, pool.submit(one, lane, texts[i])) for lane, idx in shares for i in idx]
            for i, job in jobs:
                out[i] = job.result()
        return out
    return run


def db(call):
    """A database step, done again on a fresh connection when the database dropped the old one."""
    for attempt in range(5):
        try:
            with engine.begin() as c:
                return call(c)
        except OperationalError:
            if attempt == 4:
                raise
            engine.dispose()
            time.sleep(5 * (attempt + 1))


def main() -> None:
    target = embedding_setting()
    with engine.begin() as c:
        saved = c.execute(text("SELECT value FROM law_meta WHERE key = 'embedding'")).scalar()
        if saved and json.loads(saved) == target:
            print("Already embedded with", target)
            return
        # A run left half done for another model: its vectors cannot be kept
        started_for = c.execute(text("SELECT value FROM law_meta WHERE key = 'embedding_new'")).scalar()
        if started_for and json.loads(started_for) != target:
            c.execute(text("ALTER TABLE law_chunks DROP COLUMN IF EXISTS embedding_new"))
        c.execute(text(f"ALTER TABLE law_chunks ADD COLUMN IF NOT EXISTS embedding_new halfvec({DIMS})"))
        c.execute(text("INSERT INTO law_meta (key, value) VALUES ('embedding_new', :v) "
                       "ON CONFLICT (key) DO UPDATE SET value = :v"), {"v": json.dumps(target)})
        total = c.execute(text("SELECT count(*) FROM law_chunks")).scalar()
    embed_many = bulk_embedder(sys.argv[1:])
    started, done = time.time(), 0
    while True:
        rows, left = db(lambda c: (
            c.execute(text("SELECT id, heading, text FROM law_chunks WHERE embedding_new IS NULL ORDER BY id "
                           "LIMIT :n"), {"n": BATCH}).fetchall(),
            c.execute(text("SELECT count(*) FROM law_chunks WHERE embedding_new IS NULL")).scalar()))
        if not rows:
            break
        vectors = embed_many([f"{r.heading}\n\n{r.text}" for r in rows])
        db(lambda c: c.execute(text(f"UPDATE law_chunks SET embedding_new = CAST(:v AS halfvec({DIMS})) WHERE id = :id"),
                               [{"id": r.id, "v": _vec(v)} for r, v in zip(rows, vectors)]))
        done += len(rows)
        rate = done / max(time.time() - started, 1)
        print(f"{total - left + len(rows)}/{total} pieces ({rate:.1f}/s, about {(left - len(rows)) / max(rate, 0.1) / 60:.0f} "
              f"min left)", flush=True)
    # Every piece done: the new vectors replace the old ones, with their search index
    with engine.begin() as c:
        c.execute(text("DROP INDEX IF EXISTS law_chunks_embedding"))
        c.execute(text("ALTER TABLE law_chunks DROP COLUMN embedding"))
        c.execute(text("ALTER TABLE law_chunks RENAME COLUMN embedding_new TO embedding"))
        c.execute(text("ALTER TABLE law_chunks ALTER COLUMN embedding SET NOT NULL"))
        c.execute(text("CREATE INDEX law_chunks_embedding ON law_chunks USING hnsw (embedding halfvec_cosine_ops)"))
        c.execute(text("UPDATE law_meta SET value = :v WHERE key = 'embedding'"), {"v": json.dumps(target)})
        c.execute(text("DELETE FROM law_meta WHERE key = 'embedding_new'"))
    print("Done: every piece embedded with", target, f"in {(time.time() - started) / 60:.0f} min")


if __name__ == "__main__":
    main()
