"""remove_copy: a test database copy that cannot be deleted must be reported (fix wave, finding 2).

No Firebird needed: these tests use a small temp file only.
"""

import warnings
from pathlib import Path

import pytest

from infohr_firebird.tests.copies import remove_copy


def test_remove_copy_deletes_a_normal_file_without_warning(tmp_path: Path) -> None:
    path = tmp_path / "copy.fdb"
    path.write_bytes(b"x")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        remove_copy(path)

    assert not path.exists()
    assert [w for w in caught if "test database copy" in str(w.message)] == []


def test_remove_copy_warns_when_the_file_cannot_be_deleted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "copy.fdb"
    path.write_bytes(b"x")

    def refuse(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("locked by another process")

    monkeypatch.setattr(Path, "unlink", refuse)
    monkeypatch.setattr("infohr_firebird.tests.copies.time.sleep", lambda seconds: None)

    with pytest.warns(UserWarning, match="could not delete test database copy") as recorded:
        remove_copy(path)

    assert str(path) in str(recorded[0].message)
