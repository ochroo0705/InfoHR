"""Run each HR app's test suite on a migrated Firebird copy and sort the results.

Run from the repo root:  .venv\\Scripts\\python scripts\\fb_test_inventory.py

For every app (in APPS order) it runs, with the Firebird switch on:
  1. pytest app/<app> --collect-only -q   (records the test count and the test files)
  2. pytest app/<app> -q -p no:cacheprovider -rfE --tb=line
If step 2 runs longer than TIMEOUT_S, only the process this script started is killed, the
app is recorded as timed out, and every test file of that app is run on its own (one pytest
per file). At most MAX_WORKERS pytest processes run at once.

Output, in OUT_DIR (the ledger's inventory folder):
  <app>.collect.txt   output of the collect-only run
  <app>.txt           output of the full run (partial output if it timed out)
  <app>/<file>.txt    output of each per-file rerun, only for an app that timed out
  summary.json        counts, seconds and status per app and per file
A table is printed. Nothing is fixed, staged or committed by this script.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
TEMPLATE = ROOT / "db" / "work" / "template_clone.fdb"
OUT_DIR = ROOT / ".superpowers" / "sdd" / "2026-11-07-firebird3-whole-test-suite" / "inventory"

APPS = [
    "lists",
    "accounts",
    "macs",
    "logs",
    "checklists",
    "recruitment",
    "leave",
    "reports",
    "assistant",
    "employees",
]
MAX_WORKERS = 3
TIMEOUT_S = 60 * 60
RUN_ARGS = ["-q", "-p", "no:cacheprovider", "-rfE", "--tb=line"]
COLLECT_ARGS = ["--collect-only", "-q", "-p", "no:cacheprovider"]

# Only one pytest process may run at a time per slot; apps and file reruns share these slots.
SLOTS = threading.BoundedSemaphore(MAX_WORKERS)

COLLECTED_RE = re.compile(r"(\d+)(?:/\d+)? tests? collected")
COUNT_RE = re.compile(r"(\d+) (passed|failed|errors?|skipped)\b")
SUMMARY_RE = re.compile(r"\bin ([\d.]+)s\b")


def fb_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "INFOHR_TEST_DB": "firebird",
            "DB_ENGINE": "firebird",
            "FB_TEMPLATE_FDB": str(TEMPLATE),
            "FIREBIRD_NAME": "unused",
            # Output is written to files: UTF-8 keeps Cyrillic test output from failing on cp1252.
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return env


def run_pytest(args: list[str], out_path: Path) -> dict[str, Any]:
    """Run one pytest process into out_path. Kills only that process on timeout."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(VENV_PY), "-m", "pytest", *args]
    with SLOTS:
        start = time.monotonic()
        timed_out = False
        with out_path.open("wb") as fh:
            fh.write(f"# {' '.join(cmd)}\n".encode())
            fh.flush()
            # The command is a fixed list built here (venv python, pytest, fixed arguments), not user input.
            proc = subprocess.Popen(  # noqa: S603
                cmd, cwd=ROOT, env=fb_env(), stdout=fh, stderr=subprocess.STDOUT
            )
            try:
                code = proc.wait(timeout=TIMEOUT_S)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.kill()
                code = proc.wait()
                fh.write(f"\n=== TIMED OUT after {TIMEOUT_S} s: process {proc.pid} killed ===\n".encode())
        seconds = round(time.monotonic() - start, 1)
    text = out_path.read_text(encoding="utf-8", errors="replace")
    return {"exit": code, "timed_out": timed_out, "seconds": seconds, "text": text}


def parse_summary(text: str) -> dict[str, Any] | None:
    """Counts from pytest's last summary line ('N passed, M failed, K errors in 12.3s')."""
    lines = [line for line in text.splitlines() if SUMMARY_RE.search(line)]
    if not lines:
        return None
    last = lines[-1]
    counts: dict[str, Any] = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for number, word in COUNT_RE.findall(last):
        key = "errors" if word.startswith("error") else word
        counts[key] = int(number)
    counts["pytest_seconds"] = float(SUMMARY_RE.search(last).group(1))  # type: ignore[union-attr]
    return counts


def collect(app: str) -> dict[str, Any]:
    run = run_pytest([f"app/{app}", *COLLECT_ARGS], OUT_DIR / f"{app}.collect.txt")
    text = run["text"]
    match = COLLECTED_RE.search(text)
    if match:
        collected: int | None = int(match.group(1))
    elif "no tests collected" in text:
        collected = 0
    else:
        collected = None
    files: list[str] = []
    for line in text.splitlines():
        if "::" not in line:
            continue
        head = line.split("::", 1)[0].strip().replace("\\", "/")
        if head.endswith(".py") and head not in files:
            files.append(head)
    return {"collected": collected, "files": files, "exit": run["exit"], "timed_out": run["timed_out"]}


def status_of(exit_code: Any, summary: dict[str, Any] | None) -> str:
    if summary is None:
        return f"no summary (exit {exit_code})"
    if exit_code in (0, 1):
        return "ok" if exit_code == 0 else "ok (test failures)"
    return f"exit {exit_code}"


def run_app(app: str) -> dict[str, Any]:
    col = collect(app)
    rec: dict[str, Any] = {
        "app": app,
        "collected": col["collected"],
        "collect_exit": col["exit"],
        "files": col["files"],
    }
    run = run_pytest([f"app/{app}", *RUN_ARGS], OUT_DIR / f"{app}.txt")
    summary = parse_summary(run["text"])
    if not run["timed_out"]:
        rec.update(
            split=False,
            exit=run["exit"],
            seconds=run["seconds"],
            timed_out_files=[],
            status=status_of(run["exit"], summary),
            **{k: (summary or {}).get(k) for k in ("passed", "failed", "errors", "skipped")},
            pytest_seconds=(summary or {}).get("pytest_seconds"),
        )
        return rec

    # The app timed out: run every test file on its own, MAX_WORKERS at a time.
    def one_file(path: str) -> dict[str, Any]:
        name = path.replace("/", "__") + ".txt"
        result = run_pytest([path, *RUN_ARGS], OUT_DIR / app / name)
        file_summary = parse_summary(result["text"])
        return {
            "file": path,
            "exit": result["exit"],
            "timed_out": result["timed_out"],
            "seconds": result["seconds"],
            "summary": file_summary,
            "status": "timed out" if result["timed_out"] else status_of(result["exit"], file_summary),
        }

    rerun_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        per_file = list(pool.map(one_file, col["files"]))
    rerun_seconds = round(time.monotonic() - rerun_start, 1)
    totals = {k: 0 for k in ("passed", "failed", "errors", "skipped")}
    for item in per_file:
        for key in totals:
            totals[key] += (item["summary"] or {}).get(key) or 0
    timed_out_files = [item["file"] for item in per_file if item["timed_out"]]
    rec.update(
        split=True,
        exit="split",
        # Wall time of the app: the timed-out attempt plus the per-file reruns.
        seconds=round(run["seconds"] + rerun_seconds, 1),
        timed_out_files=timed_out_files,
        status=f"timed out, rerun by file ({len(timed_out_files)} file(s) timed out)",
        files_run=per_file,
        pytest_seconds=None,
        **totals,
    )
    return rec


def run_app_safe(app: str) -> dict[str, Any]:
    try:
        return run_app(app)
    except Exception as exc:  # recorded, not hidden: the table shows the error
        return {
            "app": app,
            "status": f"script error: {exc!r}",
            "collected": None,
            "passed": None,
            "failed": None,
            "errors": None,
            "skipped": None,
            "seconds": None,
            "split": False,
        }


def fmt(value: Any) -> str:
    return "-" if value is None else str(value)


def print_table(records: list[dict[str, Any]]) -> None:
    cols = ["app", "collected", "passed", "failed", "errors", "skipped", "seconds", "status"]
    print("| " + " | ".join(cols) + " |")
    print("|" + "|".join("---" for _ in cols) + "|")
    for rec in records:
        row = [rec["app"]] + [fmt(rec.get(c)) for c in cols[1:]]
        print("| " + " | ".join(row) + " |")


def main() -> int:
    if not VENV_PY.exists():
        print(f"missing {VENV_PY}")
        return 2
    if not TEMPLATE.exists():
        print(f"missing template {TEMPLATE}")
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now().isoformat(timespec="seconds")
    by_app: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(run_app_safe, app): app for app in APPS}
        for future in as_completed(futures):
            rec = future.result()
            by_app[rec["app"]] = rec
            print(f"finished {rec['app']}: {rec.get('status')} (collected {fmt(rec.get('collected'))})", flush=True)
    records = [by_app[app] for app in APPS]
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "started": started,
                "finished": datetime.now().isoformat(timespec="seconds"),
                "template": str(TEMPLATE),
                "apps": records,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print()
    print_table(records)
    print()
    print(f"summary: {summary_path}")
    leftovers = sorted(p.name for p in (ROOT / "db" / "work").glob("scratch6_*"))
    print(f"scratch copies left in db/work: {leftovers or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
