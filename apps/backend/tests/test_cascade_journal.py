from pathlib import Path

import pytest

from app.storage.cascade_journal import CascadeJournal


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


def test_recover_completes_a_cascade_interrupted_before_commit(tmp_path: Path) -> None:
    # Simulate a hard kill: build the cascade dir by hand exactly as begin() would,
    # then never commit.
    journal = CascadeJournal(tmp_path)
    cascade_id = journal._prepare(operation="approve", record_keys=["aa"])  # test seam
    staged = tmp_path / ".cascade" / cascade_id / "staged" / "aa"
    staged.mkdir(parents=True)
    (staged / "record.json").write_bytes(b'{"a": 1}')

    assert journal.recover() == [cascade_id]

    assert (tmp_path / "aa" / "record.json").read_bytes() == b'{"a": 1}'
    assert not (tmp_path / ".cascade" / cascade_id).exists()


def test_recover_is_idempotent(tmp_path: Path) -> None:
    journal = CascadeJournal(tmp_path)
    with journal.begin(operation="approve", record_keys=["aa"]) as staging:
        staging.stage("aa", "record.json", b'{"a": 1}')
    assert journal.recover() == []          # nothing left to do
    assert (tmp_path / "aa" / "record.json").read_bytes() == b'{"a": 1}'


def test_recover_discards_a_cascade_with_no_readable_intent(tmp_path: Path) -> None:
    orphan = tmp_path / ".cascade" / "deadbeef"
    (orphan / "staged" / "aa").mkdir(parents=True)
    (orphan / "staged" / "aa" / "record.json").write_bytes(b'{"a": 1}')
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
