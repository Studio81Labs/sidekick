import shutil
import threading
import time
from pathlib import Path

import pytest

from app.storage.cascade_journal import (
    CascadeCorruptionError,
    CascadeJournal,
    CascadeRecoveryReport,
    CascadeReentryError,
    _durable_replace,
    _fsync_directory,
)


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

    assert journal.recover() == CascadeRecoveryReport()

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

    assert journal.recover() == CascadeRecoveryReport()

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

    assert journal.recover() == CascadeRecoveryReport(completed=(cascade_id,))

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

    assert journal.recover() == CascadeRecoveryReport(completed=(cascade_id,))

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

    assert journal.recover() == CascadeRecoveryReport(completed=(cascade_id,))

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
    cascade_dir = tmp_path / ".cascade" / cascade_id
    shutil.rmtree(cascade_dir / "staged")
    journal._mark_ready(cascade_id)

    with pytest.raises(CascadeCorruptionError):
        journal._commit(cascade_dir)


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

    recovered: list[CascadeRecoveryReport] = []
    entered_recover = threading.Event()

    def run_recover() -> None:
        entered_recover.set()
        recovered.append(journal.recover())

    recover_thread = threading.Thread(target=run_recover, daemon=True)
    recover_thread.start()
    # Without this the whole race window can be skipped by a starved
    # scheduler and the test passes vacuously.
    assert entered_recover.wait(timeout=5), "recover thread never called recover()"
    # Give an unlocked recover() every chance to interleave before the
    # cascade is allowed to finish.
    time.sleep(0.2)
    # The lock must still be holding it here: recover() cannot legitimately
    # return while a cascade is parked inside its begin() block. An
    # unserialised recover() would already have swept and appended.
    assert not recovered, "recover() ran to completion while a cascade was open"
    finish.set()

    cascade_thread.join(timeout=5)
    recover_thread.join(timeout=5)
    assert not cascade_thread.is_alive()
    assert not recover_thread.is_alive()

    # By the time recover() got the lock the cascade had committed and
    # removed itself, so there was nothing left to finish or quarantine.
    assert recovered == [CascadeRecoveryReport()]
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
    assert journal.recover() == CascadeRecoveryReport()  # nothing left to do
    assert (tmp_path / "aa" / "record.json").read_bytes() == b'{"a": 1}'


def test_recover_discards_a_cascade_with_no_readable_intent(tmp_path: Path) -> None:
    orphan = tmp_path / ".cascade" / "deadbeef"
    (orphan / "staged" / "aa" / "content").mkdir(parents=True)
    (orphan / "staged" / "aa" / "content" / "record.json").write_bytes(b'{"a": 1}')
    # no intent.json at all
    journal = CascadeJournal(tmp_path)

    assert journal.recover() == CascadeRecoveryReport()
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


def test_recover_quarantines_a_corrupt_cascade_and_finishes_the_rest(
    tmp_path: Path,
) -> None:
    """One unusable cascade directory must not abort the startup sweep.

    Left to propagate, CascadeCorruptionError escapes recover()'s loop, so
    the corrupt directory is never cleaned up, every later sweep dies on it
    the same way, and the half-applied cascades recovery exists to finish
    are stranded - a permanent boot failure.
    """
    journal = CascadeJournal(tmp_path)
    corrupt_id, healthy_id = "0" * 32, "f" * 32   # corrupt sorts first
    cascade_root = tmp_path / ".cascade"

    corrupt_dir = cascade_root / corrupt_id
    (corrupt_dir / "evidence").mkdir(parents=True)
    (corrupt_dir / "evidence" / "intent.json").write_bytes(b"{}")
    (corrupt_dir / "ready").write_bytes(b"")     # ready, but no staged/ at all

    healthy_dir = cascade_root / healthy_id
    (healthy_dir / "staged" / "bb" / "content").mkdir(parents=True)
    (healthy_dir / "staged" / "bb" / "content" / "record.json").write_bytes(b'{"b": 2}')
    (healthy_dir / "ready").write_bytes(b"")

    report = journal.recover()

    assert report == CascadeRecoveryReport(
        completed=(healthy_id,), quarantined=(corrupt_id,)
    )
    # The healthy cascade behind the corrupt one still finished.
    assert (tmp_path / "bb" / "record.json").read_bytes() == b'{"b": 2}'
    assert not healthy_dir.exists()
    # The corrupt one was preserved, not deleted, and is out of the way.
    assert not corrupt_dir.exists()
    quarantined = cascade_root / "corrupt" / corrupt_id
    assert (quarantined / "evidence" / "intent.json").read_bytes() == b"{}"
    assert (quarantined / "ready").is_file()


def test_recover_does_not_sweep_its_own_quarantine_directory(tmp_path: Path) -> None:
    """The quarantine holds evidence, not cascades. A later sweep must not
    see it as a cascade with no ready marker and rmtree it."""
    journal = CascadeJournal(tmp_path)
    corrupt_id = "0" * 32
    corrupt_dir = tmp_path / ".cascade" / corrupt_id
    corrupt_dir.mkdir(parents=True)
    (corrupt_dir / "ready").write_bytes(b"")

    assert journal.recover() == CascadeRecoveryReport(quarantined=(corrupt_id,))
    # Quarantining is a one-time event; the sweep is clean afterwards and
    # the evidence survives it.
    assert journal.recover() == CascadeRecoveryReport()
    assert (tmp_path / ".cascade" / "corrupt" / corrupt_id / "ready").is_file()


def test_begin_rejects_a_record_key_that_targets_the_journals_own_directory(
    tmp_path: Path,
) -> None:
    """A record key of '.cascade' writes into the journal's scratch
    namespace: staging '.cascade/<32 hex>/ready' publishes a marker for a
    cascade that never existed and poisons every later recover()."""
    journal = CascadeJournal(tmp_path)
    with pytest.raises(ValueError, match="record key"):
        with journal.begin(operation="approve", record_keys=[".cascade"]):
            pass
    assert not (tmp_path / ".cascade").exists()


def test_mark_ready_makes_the_staged_tree_durable_before_the_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The marker promises the staged tree will be replayed, so the tree
    has to be durable before the promise is.

    _durable_replace fsyncs only the directory holding the file it wrote,
    so staged/<key>'s entry in staged/, and content/'s entry in
    staged/<key>, are never made durable by staging alone - yet all of them
    are read *after* the marker. A crash could leave the marker durable
    over a staged tree that is gone, and _commit cannot detect it because
    an empty staged/ is a legitimate cascade.
    """
    journal = CascadeJournal(tmp_path)
    cascade_id = journal._prepare(operation="approve", record_keys=["aa"])
    cascade_dir = tmp_path / ".cascade" / cascade_id
    content = cascade_dir / "staged" / "aa" / "content"
    content.mkdir(parents=True)
    (content / "record.json").write_bytes(b'{"a": 1}')
    (cascade_dir / "staged" / "aa" / "deletes").mkdir()

    events: list[tuple[str, Path]] = []

    def spy_fsync(directory: Path) -> None:
        events.append(("fsync", Path(directory).resolve()))
        _fsync_directory(directory)

    def spy_replace(target: Path, payload: bytes) -> None:
        events.append(("write", Path(target).resolve()))
        _durable_replace(target, payload)

    monkeypatch.setattr(
        "app.storage.cascade_journal._fsync_directory", spy_fsync
    )
    monkeypatch.setattr(
        "app.storage.cascade_journal._durable_replace", spy_replace
    )

    journal._mark_ready(cascade_id)

    marker = (cascade_dir / "ready").resolve()
    assert ("write", marker) in events
    marker_written_at = events.index(("write", marker))
    for directory in (
        content,
        cascade_dir / "staged" / "aa" / "deletes",
        cascade_dir / "staged" / "aa",
        cascade_dir / "staged",
        cascade_dir,
        tmp_path / ".cascade",
        tmp_path,
    ):
        event = ("fsync", directory.resolve())
        assert event in events, f"{directory} was never fsynced"
        assert events.index(event) < marker_written_at, (
            f"{directory} was only fsynced after the ready marker was written"
        )


def test_stage_rejects_a_path_that_normalises_to_the_record_namespace(
    tmp_path: Path,
) -> None:
    """'x/..' resolves to staged/<key>/content itself. Staging it renames
    the temp file *onto* that path, creating a file where a directory
    belongs, after which _commit_record skips the record entirely and the
    whole cascade commits nothing while reporting success."""
    live = tmp_path / "aa"
    live.mkdir()
    (live / "record.json").write_bytes(b"OLD")
    journal = CascadeJournal(tmp_path)

    with pytest.raises(ValueError, match="must stay inside"):
        with journal.begin(operation="approve", record_keys=["aa"]) as staging:
            staging.stage("aa", "x/..", b"PAYLOAD")

    assert (live / "record.json").read_bytes() == b"OLD"
    assert not any((tmp_path / ".cascade").iterdir())


def test_stage_delete_rejects_a_path_that_normalises_to_the_record_namespace(
    tmp_path: Path,
) -> None:
    """Same defect on the deletes/ side, where it additionally makes a
    later legitimate stage_delete raise FileExistsError."""
    journal = CascadeJournal(tmp_path)
    with pytest.raises(ValueError, match="must stay inside"):
        with journal.begin(operation="reapprove", record_keys=["aa"]) as staging:
            staging.stage_delete("aa", "y/..")
            staging.stage_delete("aa", "decisions/r1-g0.json")
    assert not any((tmp_path / ".cascade").iterdir())


def test_stage_rejects_a_dot_dot_component_that_normalises_back_inside(
    tmp_path: Path,
) -> None:
    """A '..' that lands back inside the record is still refused: the
    check is on the components, not on where they happen to resolve."""
    journal = CascadeJournal(tmp_path)
    with pytest.raises(ValueError, match="must stay inside"):
        with journal.begin(operation="approve", record_keys=["aa"]) as staging:
            staging.stage("aa", "decisions/../record.json", b"{}")
    assert not (tmp_path / "aa").exists()


def test_begin_refuses_re_entry_instead_of_deadlocking(tmp_path: Path) -> None:
    """The journal lock is held across the caller's whole block and is not
    reentrant, so a nested begin() would otherwise block forever on an
    untimed acquire."""
    journal = CascadeJournal(tmp_path)
    with journal.begin(operation="approve", record_keys=["aa"]) as staging:
        staging.stage("aa", "record.json", b'{"a": 1}')
        with pytest.raises(CascadeReentryError):
            with journal.begin(operation="approve", record_keys=["bb"]):
                pass
    # The outer cascade is unharmed and still commits.
    assert (tmp_path / "aa" / "record.json").read_bytes() == b'{"a": 1}'


def test_recover_refuses_re_entry_from_inside_an_open_cascade(tmp_path: Path) -> None:
    journal = CascadeJournal(tmp_path)
    with journal.begin(operation="approve", record_keys=["aa"]) as staging:
        staging.stage("aa", "record.json", b'{"a": 1}')
        with pytest.raises(CascadeReentryError):
            journal.recover()
    assert (tmp_path / "aa" / "record.json").read_bytes() == b'{"a": 1}'


def test_the_journal_lock_is_still_released_after_a_refused_re_entry(
    tmp_path: Path,
) -> None:
    """Refusing must not leave the lock in a state that blocks the next
    caller - the guard raises before it ever touches the lock."""
    journal = CascadeJournal(tmp_path)
    with journal.begin(operation="approve", record_keys=["aa"]) as staging:
        staging.stage("aa", "record.json", b'{"a": 1}')
        with pytest.raises(CascadeReentryError):
            journal.recover()

    done = threading.Event()

    def run_recover() -> None:
        journal.recover()
        done.set()

    thread = threading.Thread(target=run_recover, daemon=True)
    thread.start()
    assert done.wait(timeout=5), "journal lock was left held after a refused re-entry"
