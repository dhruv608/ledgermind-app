"""The upload screen asks how far the upload has got; only a stage number is kept, per upload id."""
from backend.app.services.ingestion import upload_progress as up


def test_stage_kept_per_upload():
    up.mark("abcd1234-test", 3)
    assert up.stage_of("abcd1234-test")["stage"] == 3
    assert up.stage_of("never-started-1")["stage"] == 0
    assert len(up.stage_of("abcd1234-test")["stages"]) == 4


def test_bad_ids_ignored():
    up.mark("../../etc/passwd", 2)          # not a valid id: nothing written outside the folder
    assert up.stage_of("../../etc/passwd")["stage"] == 0
    up.mark(None, 1)                        # no id sent (an older screen): the upload goes on
