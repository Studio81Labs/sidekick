import shutil
import threading
import time
from pathlib import Path

import pytest

from app.storage.cascade_journal import CascadeCorruptionError, CascadeJournal


def test_cascade_commit_publishes_every_staged_file(tmp_path: Path) -> None:
    journal = CascadeJournal(tmp_path)
    with journal.begin(operation="approve", record_keys=["aa", "bb"]) as staging:
        staging.stage("aa", "record.json", b'{"a": 1}')
        staging.stage("bb", "record.json", b'{"b": 2}')
        assert not (tmp_path / "aa" / "record.json").exists()   # nothing live yet
    assert (tmp_path / "aa" / "record.json").read_bytes() == b'{"a": 1}'
    assert (tmp_path / "bb" / "record.json").read_bytes() == b'{"b": 2}'
    assert not (tmp_path / ".cascade").exists() or not any((tmp_path / ".cascade").iterdir())


def test_cascade_discards_every_change_when_the_block_raises(tmp_path: Path) -> None:
    journal = CascadeJournal(tmp_path)
    with pytest.raises(RuntimeError):
        with journal.begin(operation="approve", record_keys=["aa"]) as staging:
            staging.stage("aa", "record.json", b'{"a": 1}')
            raise RuntimeError("cascade failed")
    assert not (tmp_path / "aa" / "record.json").exists()
    assert not any((tmp_path / ".cascade").iterdir())


def test_recover_discards_a_cascade_interrupted_before_commit(tmp_path: Path) -> None:
    # Simulate a hard kill: build the cascade dir by hand exactly as begin() would,
    # then never mark it ready and never commit.
    journal = CascadeJournal(tmp_path)
    cascade_id = journal._prepare(operation="approve", record_keys=["aa"])  # test seam
    staged = tmp_path / ".cascade" / cascade_id / "staged" / "aa" / "content"
    staged.mkdir(parents=True)
    (staged / "record.json").write_bytes(b'{"a": 1}')

    assert journal.recover() == []

    assert not (tmp_path / "aa" / "record.json").exists()
    assert not (tmp_path / ".cascade" / cascade_id).exists()


def test_recover_discards_a_cascade_that_never_reached_commit(tmp_path: Path) -> None:
    """A crash mid-staging must apply nothing, not a partial set."""
    journal = CascadeJournal(tmp_path)
    cascade_id = journal._prepare(operation="approve", record_keys=["aa", "bb"])
    staged = tmp_path / ".cascade" / cascade_id / "staged" / "aa" / "content"
    staged.mkdir(parents=True)
    (staged / "record.json").write_bytes(b'{"a": 1}')
    # "bb" was never staged and no ready marker was written.

    assert journal.recover() == []

    assert not (tmp_path / "aa" / "record.json").exists()
    assert not (tmp_path / "bb" / "record.json").exists()
    assert not (tmp_path / ".cascade" / cascade_id).exists()


def test_recover_completes_a_cascade_that_reached_commit(tmp_path: Path) -> None:
    """With the marker present, replay finishes the cascade for every named key."""
    journal = CascadeJournal(tmp_path)
    cascade_id = journal._prepare(operation="approve", record_keys=["aa", "bb"])
    for key, payload in (("aa", b'{"a": 1}'), ("bb", b'{"b": 2}')):
        staged = tmp_path / ".cascade" / cascade_id / "staged" / key / "content"
        staged.mkdir(parents=True)
        (staged / "record.json").write_bytes(payload)
    journal._mark_ready(cascade_id)          # test seam, mirrors _prepare

    assert journal.recover() == [cascade_id]

    assert (tmp_path / "aa" / "record.json").read_bytes() == b'{"a": 1}'
    assert (tmp_path / "bb" / "record.json").read_bytes() == b'{"b": 2}'


def test_recover_completes_a_committing_cascade_despite_an_unreadable_intent(
    tmp_path: Path,
) -> None:
    """After the ready marker, commit may already have applied some renames,
    so finishing is the only safe action - the intent is not consulted."""
    journal = CascadeJournal(tmp_path)
    cascade_id = journal._prepare(operation="approve", record_keys=["aa", "bb"])
    for key, payload in (("aa", b'{"a": 1}'), ("bb", b'{"b": 2}')):
        staged = tmp_path / ".cascade" / cascade_id / "staged" / key / "content"
        staged.mkdir(parents=True)
        (staged / "record.json").write_bytes(payload)
    journal._mark_ready(cascade_id)
    # Simulate a torn write of the intent, and a commit that got as far as "aa".
    (tmp_path / ".cascade" / cascade_id / "intent.json").write_bytes(b"{not json")
    (tmp_path / "aa").mkdir()
    (tmp_path / "aa" / "record.json").write_bytes(b'{"a": 1}')

    assert journal.recover() == [cascade_id]

    assert (tmp_path / "aa" / "record.json").read_bytes() == b'{"a": 1}'
    assert (tmp_path / "bb" / "record.json").read_bytes() == b'{"b": 2}'
    assert not (tmp_path / ".cascade" / cascade_id).exists()


def test_recover_finishes_a_cascade_where_one_key_already_published(
    tmp_path: Path,
) -> None:
    """A crash mid-commit can leave one key already renamed live and
    another still sitting in staged/; replay must finish the rest without
    needing to re-touch the one that already landed - this is the actual
    "already published, no longer staged" shape commit leaves behind,
    distinct from a staged copy that merely survives alongside the live
    file."""
    journal = CascadeJournal(tmp_path)
    cascade_id = journal._prepare(operation="approve", record_keys=["aa", "bb"])
    # "aa" already made it to its live location, exactly as a real commit
    # leaves it once os.replace has consumed the staged copy - there is no
    # staged/aa left at all.
    (tmp_path / "aa").mkdir()
    (tmp_path / "aa" / "record.json").write_bytes(b'{"a": 1}')
    # "bb" is still waiting in staged/, never yet renamed.
    staged_bb = tmp_path / ".cascade" / cascade_id / "staged" / "bb" / "content"
    staged_bb.mkdir(parents=True)
    (staged_bb / "record.json").write_bytes(b'{"b": 2}')
    journal._mark_ready(cascade_id)

    assert journal.recover() == [cascade_id]

    assert (tmp_path / "aa" / "record.json").read_bytes() == b'{"a": 1}'
    assert (tmp_path / "bb" / "record.json").read_bytes() == b'{"b": 2}'
    assert not (tmp_path / ".cascade" / cascade_id).exists()


def test_commit_refuses_a_cascade_missing_its_staged_directory(tmp_path: Path) -> None:
    """A ready cascade with no staged/ at all is corruption - begin() and
    recover() both always create one, even empty - so it must raise
    rather than silently discard or silently no-op over a half-applied
    cascade."""
    journal = CascadeJournal(tmp_path)
    cascade_id = journal._prepare(operation="approve", record_keys=["aa"])
    shutil.rmtree(tmp_path / ".cascade" / cascade_id / "staged")
    journal._mark_ready(cascade_id)

    with pytest.raises(CascadeCorruptionError):
        journal.recover()


def test_recover_cannot_destroy_a_cascade_that_is_still_open(tmp_path: Path) -> None:
    """A concurrent recover() - e.g. another process's startup sweep racing
    an in-flight begin() - must not destroy a cascade's staged files and
    let the caller believe its write landed when nothing was applied."""
    journal = CascadeJournal(tmp_path)
    staged = threading.Event()
    finish = threading.Event()

    def run_cascade() -> None:
        with journal.begin(operation="approve", record_keys=["aa"]) as staging:
            staging.stage("aa", "record.json", b'{"a": 1}')
            staged.set()
            finish.wait(timeout=5)

    cascade_thread = threading.Thread(target=run_cascade, daemon=True)
    cascade_thread.start()
    assert staged.wait(timeout=5), "cascade thread never reached staging"

    recovered: list[str] = []

    def run_recover() -> None:
        recovered.extend(journal.recover())

    recover_thread = threading.Thread(target=run_recover, daemon=True)
    recover_thread.start()
    # Give an unlocked recover() every chance to interleave before the
    # cascade is allowed to finish.
    time.sleep(0.2)
    finish.set()

    cascade_thread.join(timeout=5)
    recover_thread.join(timeout=5)
    assert not cascade_thread.is_alive()
    assert not recover_thread.is_alive()

    assert (tmp_path / "aa" / "record.json").read_bytes() == b'{"a": 1}'


def test_begin_rejects_a_record_key_that_could_escape_its_directory(tmp_path: Path) -> None:
    """An absolute or dot-dot record key must never reach stage(): begin()
    is the only checkpoint that can refuse it before a cascade even opens."""
    journal = CascadeJournal(tmp_path)
    with pytest.raises(ValueError, match="record key"):
        with journal.begin(operation="approve", record_keys=["../escape"]):
            pass
    assert not (tmp_path.parent / "escape").exists()
    assert not (tmp_path / ".cascade").exists()


def test_stage_publishes_a_file_whose_name_ends_in_unlink(tmp_path: Path) -> None:
    """A content file that happens to be named *.unlink must publish as
    itself, not be misread as a deletion marker for a different file."""
    live = tmp_path / "aa"
    live.mkdir()
    (live / "notes").write_bytes(b"OLD")
    journal = CascadeJournal(tmp_path)
    with journal.begin(operation="approve", record_keys=["aa"]) as staging:
        staging.stage("aa", "notes.unlink", b"NEW")
    assert (live / "notes.unlink").read_bytes() == b"NEW"
    assert (live / "notes").read_bytes() == b"OLD"   # untouched


def test_stage_rejects_an_empty_or_dot_only_relative_path(tmp_path: Path) -> None:
    journal = CascadeJournal(tmp_path)
    with pytest.raises(ValueError, match="must not be empty"):
        with journal.begin(operation="approve", record_keys=["aa"]) as staging:
            staging.stage("aa", "", b"{}")


def test_stage_delete_rejects_an_empty_or_dot_only_relative_path(tmp_path: Path) -> None:
    journal = CascadeJournal(tmp_path)
    with pytest.raises(ValueError, match="must not be empty"):
        with journal.begin(operation="approve", record_keys=["aa"]) as staging:
            staging.stage_delete("aa", ".")


def test_recover_is_idempotent(tmp_path: Path) -> None:
    journal = CascadeJournal(tmp_path)
    with journal.begin(operation="approve", record_keys=["aa"]) as staging:
        staging.stage("aa", "record.json", b'{"a": 1}')
    assert journal.recover() == []          # nothing left to do
    assert (tmp_path / "aa" / "record.json").read_bytes() == b'{"a": 1}'


def test_recover_discards_a_cascade_with_no_readable_intent(tmp_path: Path) -> None:
    orphan = tmp_path / ".cascade" / "deadbeef"
    (orphan / "staged" / "aa" / "content").mkdir(parents=True)
    (orphan / "staged" / "aa" / "content" / "record.json").write_bytes(b'{"a": 1}')
    # no intent.json at all
    journal = CascadeJournal(tmp_path)

    assert journal.recover() == []
    assert not orphan.exists()
    assert not (tmp_path / "aa" / "record.json").exists()   # never guessed at


def test_staged_deletion_removes_the_live_file_on_commit(tmp_path: Path) -> None:
    live = tmp_path / "aa" / "decisions"
    live.mkdir(parents=True)
    (live / "r1-g0.json").write_bytes(b"{}")
    journal = CascadeJournal(tmp_path)
    with journal.begin(operation="reapprove", record_keys=["aa"]) as staging:
        staging.stage_delete("aa", "decisions/r1-g0.json")
    assert not (live / "r1-g0.json").exists()


def test_stage_rejects_a_path_escaping_its_record(tmp_path: Path) -> None:
    journal = CascadeJournal(tmp_path)
    with pytest.raises(ValueError, match="must stay inside"):
        with journal.begin(operation="approve", record_keys=["aa"]) as staging:
            staging.stage("aa", "../../escape.json", b"{}")


def test_stage_rejects_a_record_key_absent_from_the_intent(tmp_path: Path) -> None:
    journal = CascadeJournal(tmp_path)
    with pytest.raises(ValueError, match="not named by this cascade"):
        with journal.begin(operation="approve", record_keys=["aa"]) as staging:
            staging.stage("bb", "record.json", b"{}")
