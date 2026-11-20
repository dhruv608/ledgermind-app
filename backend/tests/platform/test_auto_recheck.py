"""A change re-runs the checks by itself: only for a job whose checks ran before, never from inside a run."""
import threading
from types import SimpleNamespace as N

from backend.app.services.shared import activity
from backend.app.services.checks import runner


def _setup(monkeypatch, has_run=True):
    started = []
    monkeypatch.setattr(runner, "_latest", lambda db, eid: N(id=1) if has_run else None)
    monkeypatch.setattr(runner, "start_if_ready", lambda db, eng, trigger, user_id=None: started.append(trigger))
    db = N(get=lambda model, eid: N(id=eid))
    return db, started


def test_a_change_starts_the_checks(monkeypatch):
    db, started = _setup(monkeypatch)
    activity.recheck(db, "job-1")
    assert started == ["change"]


def test_not_before_the_first_run(monkeypatch):
    db, started = _setup(monkeypatch, has_run=False)
    activity.recheck(db, "job-1")
    assert started == []


def test_not_from_inside_a_run(monkeypatch):
    db, started = _setup(monkeypatch)
    t = threading.Thread(target=activity.recheck, args=(db, "job-1"), name="checks-job-1")
    t.start()
    t.join()
    assert started == []
