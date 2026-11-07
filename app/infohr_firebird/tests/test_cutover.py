"""Unit tests for the cut-over helpers (no database needed), and the fb_cutover command.

The command tests run fb_cutover in a subprocess (run_manage, like their neighbours), with DB_ENGINE=firebird and the
copy as FIREBIRD_NAME. gbak is a fake .cmd file that copies files, set through FB_GBAK, so the tests do not need a
working gbak login. They skip without FB_TEMPLATE_FDB because they open a copy of the template.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
from django.core.management.base import CommandError

from infohr_firebird.cutover import (
    compare_counts,
    gbak_backup_args,
    gbak_database_name,
    gbak_restore_args,
    is_scratch_name,
    redact,
    refuse_live,
)
from infohr_firebird.management.commands import fb_cutover as cutover_module
from infohr_firebird.testdb import run_manage


def test_scratch_name_accepted() -> None:
    assert is_scratch_name(r"E:\x\MACS_clone.fdb") is True


def test_live_name_rejected() -> None:
    assert is_scratch_name(r"E:\x\MACSXE4DB.FDB") is False


def test_scratch_marker_is_case_insensitive() -> None:
    assert is_scratch_name(r"E:\x\MACS_CLONE.FDB") is True
    assert is_scratch_name("E:/x/Restore-Check.fdb") is True
    assert is_scratch_name("E:/x/Scratch_copy.fdb") is True


def test_only_file_name_is_checked_not_folder() -> None:
    assert is_scratch_name(r"E:\clone_tests\MACSXE4DB.FDB") is False


def test_refuse_live_raises_plain_message() -> None:
    with pytest.raises(ValueError, match="test copy"):
        refuse_live(r"E:\x\MACSXE4DB.FDB")


def test_refuse_live_passes_scratch_name() -> None:
    refuse_live(r"E:\x\MACS_clone.fdb")


def test_backup_args_have_no_password() -> None:
    args = gbak_backup_args("a.fdb", "b.fbk", "SYSDBA")
    assert args == ["-b", "-user", "SYSDBA", "a.fdb", "b.fbk"]
    assert "-password" not in args


def test_restore_args_use_create_flag() -> None:
    args = gbak_restore_args("b.fbk", r"E:\x\MACS_clone.fdb", "SYSDBA")
    assert args == ["-c", "-user", "SYSDBA", "b.fbk", r"E:\x\MACS_clone.fdb"]
    assert "-password" not in args


def test_restore_refuses_live_target() -> None:
    with pytest.raises(ValueError):
        gbak_restore_args("b.fbk", r"E:\x\MACSXE4DB.FDB", "SYSDBA")


def test_compare_counts_reports_changed_table() -> None:
    lines = compare_counts({"A": 1, "B": 2}, {"A": 1, "B": 3})
    assert len(lines) == 1
    assert "B" in lines[0]


def test_compare_counts_reports_missing_table() -> None:
    lines = compare_counts({"A": 1}, {})
    assert len(lines) == 1
    assert "A" in lines[0]


def test_compare_counts_equal_is_empty() -> None:
    assert compare_counts({"A": 1, "B": 2}, {"A": 1, "B": 2}) == []


def test_redact_replaces_every_occurrence() -> None:
    assert redact("pw=abc and abc", "abc") == "pw=*** and ***"


def test_redact_empty_secret_is_noop() -> None:
    assert redact("x", "") == "x"


# --- fb_cutover command (subprocess, fake gbak) ---------------------------------------------------------------------

# Fake gbak. Arguments are "-b|-c -user NAME SOURCE TARGET", so SOURCE is %~4 and TARGET is %~5. The fake copies the
# file and echoes the value of ISC_PASSWORD (to stderr), so the tests can prove that the command redacts it.
FAKE_OK_BODY = 'echo gbak notes: %ISC_PASSWORD% 1>&2\r\ncopy /Y "%~4" "%~5" >nul\r\nexit /b 0'
FAKE_FAIL_BODY = "echo gbak: login failed for %ISC_PASSWORD% 1>&2\r\nexit /b 1"


def _fake_gbak(folder: Path, name: str, body: str) -> str:
    path = folder / name
    path.write_text("@echo off\r\n" + body + "\r\n", encoding="ascii")
    return str(path)


def _cutover(args: list[str], clone: str, gbak: str) -> subprocess.CompletedProcess[str]:
    return run_manage(["fb_cutover", *args], DB_ENGINE="firebird", FIREBIRD_NAME=clone, FB_GBAK=gbak)


def test_restore_check_prints_restore_ok(fb_clone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gbak = _fake_gbak(tmp_path, "fake_gbak_ok.cmd", FAKE_OK_BODY)
    monkeypatch.setenv("FB_ADMIN_PASSWORD", "test-only-pw")
    backup = tmp_path / "backup.fbk"
    scratch = tmp_path / "restore-check.fdb"
    made = _cutover(["backup", "--to", str(backup)], fb_clone, gbak)
    assert made.returncode == 0, made.stdout + made.stderr
    checked = _cutover(["restore-check", "--backup", str(backup), "--scratch", str(scratch)], fb_clone, gbak)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "RESTORE OK" in checked.stdout
    assert "RESTORE DIFFERS" not in checked.stdout
    assert scratch.is_file()


def _add_live_row(clone: str) -> None:
    """A MACS-style save after the backup: one new row in the live copy.

    The template is a raw MACS copy (no HR tables), so the row goes into CASHBALANCE: one nullable column and no rows.
    The insert names the table's only column, read from the system tables.
    """
    column_sql = "select trim(rdb$field_name) from rdb$relation_fields where rdb$relation_name = 'CASHBALANCE'"
    code = (
        "from django.db import connection as db; cur = db.cursor(); "  # noqa: S608 (fixed table name, no input)
        f"cur.execute({column_sql!r}); col = cur.fetchone()[0]; "
        "cur.execute('insert into CASHBALANCE (' + col + ') values (0)')"
    )
    proc = run_manage(["shell", "-c", code], DB_ENGINE="firebird", FIREBIRD_NAME=clone)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_backup_writes_counts_sidecar(fb_clone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gbak = _fake_gbak(tmp_path, "fake_gbak_ok.cmd", FAKE_OK_BODY)
    monkeypatch.setenv("FB_ADMIN_PASSWORD", "test-only-pw")
    backup = tmp_path / "sidecar.fbk"
    made = _cutover(["backup", "--to", str(backup)], fb_clone, gbak)
    assert made.returncode == 0, made.stdout + made.stderr
    sidecar = tmp_path / "sidecar.fbk.counts.json"
    counts = json.loads(sidecar.read_text(encoding="utf-8"))
    assert isinstance(counts, dict)
    assert counts
    assert all(isinstance(value, int) for value in counts.values())


def test_restore_check_uses_counts_taken_at_backup_time(
    fb_clone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gbak = _fake_gbak(tmp_path, "fake_gbak_ok.cmd", FAKE_OK_BODY)
    monkeypatch.setenv("FB_ADMIN_PASSWORD", "test-only-pw")
    backup = tmp_path / "live_change.fbk"
    made = _cutover(["backup", "--to", str(backup)], fb_clone, gbak)
    assert made.returncode == 0, made.stdout + made.stderr
    _add_live_row(fb_clone)  # the live database changes after the backup was taken
    scratch = tmp_path / "restore-check-live.fdb"
    checked = _cutover(["restore-check", "--backup", str(backup), "--scratch", str(scratch)], fb_clone, gbak)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "RESTORE OK" in checked.stdout
    assert "RESTORE DIFFERS" not in checked.stdout
    assert "compared with the counts taken at backup time" in checked.stdout
    assert "no counts file" not in checked.stdout
    assert "holds a full copy of customer data" in checked.stdout
    assert scratch.is_file()


def test_restore_check_without_counts_file_falls_back_to_live(
    fb_clone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gbak = _fake_gbak(tmp_path, "fake_gbak_ok.cmd", FAKE_OK_BODY)
    monkeypatch.setenv("FB_ADMIN_PASSWORD", "test-only-pw")
    backup = tmp_path / "no_sidecar.fbk"
    made = _cutover(["backup", "--to", str(backup)], fb_clone, gbak)
    assert made.returncode == 0, made.stdout + made.stderr
    (tmp_path / "no_sidecar.fbk.counts.json").unlink()
    scratch = tmp_path / "restore-check-fallback.fdb"
    checked = _cutover(["restore-check", "--backup", str(backup), "--scratch", str(scratch)], fb_clone, gbak)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "WARNING: no counts file: compared with the live database, run with MACS stopped" in checked.stdout
    assert "RESTORE OK" in checked.stdout


def test_backup_refuses_existing_counts_file(fb_clone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gbak = _fake_gbak(tmp_path, "fake_gbak_ok.cmd", FAKE_OK_BODY)
    monkeypatch.setenv("FB_ADMIN_PASSWORD", "test-only-pw")
    target = tmp_path / "counts_taken.fbk"
    counts_file = tmp_path / "counts_taken.fbk.counts.json"
    counts_file.write_text("{}", encoding="utf-8")
    proc = _cutover(["backup", "--to", str(target)], fb_clone, gbak)
    assert proc.returncode != 0
    assert "already exists" in proc.stderr
    assert not target.exists()
    assert counts_file.read_text(encoding="utf-8") == "{}"


def test_restore_check_refuses_live_style_scratch_name(
    fb_clone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gbak = _fake_gbak(tmp_path, "fake_gbak_ok.cmd", FAKE_OK_BODY)
    monkeypatch.setenv("FB_ADMIN_PASSWORD", "test-only-pw")
    backup = tmp_path / "backup.fbk"
    backup.write_bytes(b"not used")
    live_style = tmp_path / "MACSXE4DB.FDB"
    proc = _cutover(["restore-check", "--backup", str(backup), "--scratch", str(live_style)], fb_clone, gbak)
    assert proc.returncode != 0
    assert "test copy" in proc.stderr
    assert not live_style.exists()


def test_backup_refuses_existing_file_and_leaves_it_untouched(
    fb_clone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gbak = _fake_gbak(tmp_path, "fake_gbak_ok.cmd", FAKE_OK_BODY)
    monkeypatch.setenv("FB_ADMIN_PASSWORD", "test-only-pw")
    existing = tmp_path / "existing.fbk"
    existing.write_bytes(b"keep me")
    proc = _cutover(["backup", "--to", str(existing)], fb_clone, gbak)
    assert proc.returncode != 0
    assert "already exists" in proc.stderr
    assert existing.read_bytes() == b"keep me"


def test_backup_refuses_missing_password_with_plain_message(
    fb_clone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gbak = _fake_gbak(tmp_path, "fake_gbak_ok.cmd", FAKE_OK_BODY)
    monkeypatch.delenv("FB_ADMIN_PASSWORD", raising=False)
    target = tmp_path / "new.fbk"
    proc = _cutover(["backup", "--to", str(target)], fb_clone, gbak)
    assert proc.returncode != 0
    assert "FB_ADMIN_PASSWORD is not set" in proc.stderr
    assert not target.exists()


def test_admin_password_never_appears_in_output_or_errors(
    fb_clone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "s3cr3t-test"  # noqa: S105 (dummy value)
    monkeypatch.setenv("FB_ADMIN_PASSWORD", secret)
    ok_gbak = _fake_gbak(tmp_path, "gbak_ok.cmd", FAKE_OK_BODY)
    ok = _cutover(["backup", "--to", str(tmp_path / "ok.fbk")], fb_clone, ok_gbak)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert secret not in ok.stdout + ok.stderr
    assert "***" in ok.stdout + ok.stderr

    bad_target = tmp_path / "bad.fbk"
    fail_gbak = _fake_gbak(tmp_path, "gbak_fail.cmd", FAKE_FAIL_BODY)
    failed = _cutover(["backup", "--to", str(bad_target)], fb_clone, fail_gbak)
    assert failed.returncode != 0
    assert secret not in failed.stdout + failed.stderr
    assert "***" in failed.stdout + failed.stderr
    assert not bad_target.exists()


def test_report_without_snapshot_is_not_ready_not_a_crash(fb_clone: str, tmp_path: Path) -> None:
    gbak = _fake_gbak(tmp_path, "fake_gbak_ok.cmd", FAKE_OK_BODY)
    proc = _cutover(["report", "--snapshot", str(tmp_path / "missing.json")], fb_clone, gbak)
    assert proc.returncode != 0
    assert "Traceback" not in proc.stderr
    assert "structure verify: FAIL - not checked" in proc.stdout
    assert proc.stdout.strip().splitlines()[-1] == "NOT READY"


def test_gbak_name_with_host_and_port() -> None:
    assert gbak_database_name("localhost", "3050", r"E:\db\MACS_clone.fdb") == r"localhost/3050:E:\db\MACS_clone.fdb"


def test_gbak_name_with_host_without_port() -> None:
    assert gbak_database_name("localhost", "", r"E:\db\MACS_clone.fdb") == r"localhost:E:\db\MACS_clone.fdb"


def test_gbak_name_without_host_is_plain_path() -> None:
    assert gbak_database_name("", "3050", r"E:\db\MACS_clone.fdb") == r"E:\db\MACS_clone.fdb"


def test_restore_check_refuses_empty_admin_password(
    fb_clone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gbak = _fake_gbak(tmp_path, "fake_gbak_ok.cmd", FAKE_OK_BODY)
    monkeypatch.setenv("FB_ADMIN_PASSWORD", "test-only-pw")
    backup = tmp_path / "empty_pw.fbk"
    made = _cutover(["backup", "--to", str(backup)], fb_clone, gbak)
    assert made.returncode == 0, made.stdout + made.stderr
    monkeypatch.setenv("FB_ADMIN_PASSWORD", "")
    scratch = tmp_path / "restore-check-empty-pw.fdb"
    checked = _cutover(["restore-check", "--backup", str(backup), "--scratch", str(scratch)], fb_clone, gbak)
    assert checked.returncode != 0
    assert "FB_ADMIN_PASSWORD is not set" in checked.stderr
    assert not scratch.exists()


@pytest.mark.parametrize("kind", ["empty", "corrupt", "directory"])
def test_restore_check_refuses_unusable_counts_file_without_fallback(
    kind: str, fb_clone: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gbak = _fake_gbak(tmp_path, "fake_gbak_ok.cmd", FAKE_OK_BODY)
    monkeypatch.setenv("FB_ADMIN_PASSWORD", "test-only-pw")
    backup = tmp_path / f"bad_counts_{kind}.fbk"
    made = _cutover(["backup", "--to", str(backup)], fb_clone, gbak)
    assert made.returncode == 0, made.stdout + made.stderr
    sidecar = tmp_path / f"bad_counts_{kind}.fbk.counts.json"
    if kind == "directory":
        sidecar.unlink()
        sidecar.mkdir()
    elif kind == "empty":
        sidecar.write_bytes(b"")
    else:
        sidecar.write_text("{not json", encoding="utf-8")
    scratch = tmp_path / f"restore-check-bad-{kind}.fdb"
    checked = _cutover(["restore-check", "--backup", str(backup), "--scratch", str(scratch)], fb_clone, gbak)
    assert checked.returncode != 0
    assert "restore-check refused" in checked.stderr
    assert "no counts file" not in checked.stdout
    assert "RESTORE" not in checked.stdout
    assert not scratch.exists()


def _partial_sidecar_write(path: str, counts: dict[str, int]) -> None:
    Path(path).write_text("{", encoding="utf-8")  # a partial file, as a disk-full error can leave it
    raise OSError("disk full (test)")


def test_failed_sidecar_write_removes_new_backup_and_partial_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FB_ADMIN_PASSWORD", "test-only-pw")
    monkeypatch.setattr(
        cutover_module, "_firebird_config", lambda alias: {"ENGINE": "infohr_firebird", "NAME": "x_clone.fdb"}
    )
    monkeypatch.setattr(cutover_module, "_row_counts", lambda config: {"A": 1})

    def fake_gbak(args: list[str], password: str) -> tuple[int, str]:
        Path(args[-1]).write_bytes(b"backup bytes")
        return 0, ""

    monkeypatch.setattr(cutover_module, "_run_gbak", fake_gbak)
    monkeypatch.setattr(cutover_module, "_write_counts", _partial_sidecar_write)
    target = tmp_path / "partial_sidecar.fbk"
    with pytest.raises(CommandError, match="counts file could not be written"):
        cutover_module.Command()._backup("default", str(target))
    assert not target.exists()
    assert not (tmp_path / "partial_sidecar.fbk.counts.json").exists()


def test_backup_source_uses_host_and_port(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FB_ADMIN_PASSWORD", "test-only-pw")
    monkeypatch.setattr(
        cutover_module,
        "_firebird_config",
        lambda alias: {
            "ENGINE": "infohr_firebird",
            "NAME": "E:/db/MACS_clone.fdb",
            "HOST": "localhost",
            "PORT": "3050",
        },
    )
    monkeypatch.setattr(cutover_module, "_row_counts", lambda config: {"A": 1})
    seen: list[list[str]] = []

    def fake_gbak(args: list[str], password: str) -> tuple[int, str]:
        seen.append(args)
        Path(args[-1]).write_bytes(b"backup bytes")
        return 0, ""

    monkeypatch.setattr(cutover_module, "_run_gbak", fake_gbak)
    cutover_module.Command()._backup("default", str(tmp_path / "host_source.fbk"))
    assert seen[0][-2] == "localhost/3050:E:/db/MACS_clone.fdb"


def test_restore_target_uses_host_and_counts_through_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FB_ADMIN_PASSWORD", "test-only-pw")
    backup = tmp_path / "host_restore.fbk"
    backup.write_bytes(b"backup bytes")
    scratch = tmp_path / "restore-check-host.fdb"
    monkeypatch.setattr(
        cutover_module,
        "_firebird_config",
        lambda alias: {"ENGINE": "infohr_firebird", "NAME": "x", "HOST": "localhost"},
    )
    counted: list[dict[str, str]] = []

    def fake_counts(config: dict[str, str]) -> dict[str, int]:
        counted.append(config)
        return {"A": 1}

    monkeypatch.setattr(cutover_module, "_row_counts", fake_counts)
    seen: list[list[str]] = []

    def fake_gbak(args: list[str], password: str) -> tuple[int, str]:
        seen.append(args)
        return 0, ""  # the fake does not create the file; the counts are faked too

    monkeypatch.setattr(cutover_module, "_run_gbak", fake_gbak)
    cutover_module.Command()._restore_check("default", str(backup), str(scratch))
    assert seen[0][-1] == f"localhost:{os.path.abspath(str(scratch))}"
    assert counted[-1]["HOST"] == "localhost"


SIDE_SAVES_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "fb_macs_side_saves.py"

# Runs inside manage.py shell. The script's setup() picks shift id 9000 + (tag % 900); a shift with that id is put in
# first, so setup's INSERT must fail, and cleanup must leave the pre-existing shift alone.
_SHIFT_COLLISION_CODE = """
import importlib.util
from datetime import date
from django.db import connection as db
spec = importlib.util.spec_from_file_location("side_saves", "__SCRIPT__")
side = importlib.util.module_from_spec(spec)
spec.loader.exec_module(side)
tag = "abcdef"
shift_id = 9000 + (int(tag, 16) % 900)
with db.cursor() as cur:
    cur.execute("INSERT INTO shifts (id, name) VALUES (%s, %s)", [shift_id, "PRE-EXISTING"])
ctx = side.Ctx(tag=tag, today=date(2026, 11, 7))
try:
    raised = False
    try:
        side.setup(ctx)
    except Exception:
        raised = True
    assert raised, "setup did not raise on the duplicate shift id"
    assert ctx.shift_added is None, ctx.shift_added
    side.cleanup(ctx)
    with db.cursor() as cur:
        cur.execute("SELECT name FROM shifts WHERE id = %s", [shift_id])
        rows = cur.fetchall()
    assert len(rows) == 1 and str(rows[0][0]).strip() == "PRE-EXISTING", rows
    print("PROOF OK")
finally:
    with db.cursor() as cur:
        cur.execute("DELETE FROM shifts WHERE id = %s", [shift_id])
"""


def test_side_saves_shift_collision_keeps_preexisting_shift(fb_clone: str) -> None:
    code = _SHIFT_COLLISION_CODE.replace("__SCRIPT__", str(SIDE_SAVES_SCRIPT).replace("\\", "/"))
    proc = run_manage(["shell", "-c", code], DB_ENGINE="firebird", FIREBIRD_NAME=fb_clone)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PROOF OK" in proc.stdout
