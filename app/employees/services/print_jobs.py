"""Printing many orders as one PDF in the background (the register's «Сонгосныг хэвлэх» with more than a few orders).

A job is a folder `<PRINT_JOBS_ROOT>/<token>/` holding `status.json` and, once built, `result.pdf`. Files (not a
database table) so it needs no migration and works when the site runs as more than one process. The PDF is built
by a daemon thread in the process that took the request; a restart of the server while it runs loses that job
(the status then turns to «failed» after STALE_AFTER seconds and the user presses «Дахин оролдох»).
Only the user who started a job can read its status or file. Folders older than KEEP_FOR seconds are removed.
"""

import json
import logging
import re
import secrets
import shutil
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from accounts.audit import Category, record_safe
from accounts.models import User
from django.conf import settings
from django.db import connections

from employees import access
from employees.models import HrOrder, OrderState
from employees.services import order_docs

logger = logging.getLogger(__name__)

BACKGROUND_FROM = 11  # this many orders or more are built in the background; fewer are built while the user waits
LIMIT = 100  # orders in one printout (the register's cap, ORDER_PRINT_LIMIT)
KEEP_FOR = 24 * 3600
STALE_AFTER = 10 * 60
TOKEN = re.compile(r"[A-Za-z0-9_-]{16,64}")
NOTHING = "Хэвлэх тушаал алга."
FAILED = "Бэлтгэж чадсангүй."
RESTARTED = "Бэлтгэх үед алдаа гарлаа (сервер дахин ассан байж болно)."


def _root() -> Path:
    return Path(settings.PRINT_JOBS_ROOT)


def _folder(token: str) -> Path | None:
    return _root() / token if TOKEN.fullmatch(token) else None  # a token is never a path


def _write(folder: Path, data: dict[str, Any]) -> None:
    temp = folder / "status.tmp"
    temp.write_text(json.dumps(data), encoding="utf-8")
    temp.replace(folder / "status.json")  # one step, so a poll never reads a half-written file


def _sweep() -> None:
    root = _root()
    if not root.is_dir():
        return
    limit = time.time() - KEEP_FOR
    for folder in root.iterdir():
        try:
            if folder.is_dir() and folder.stat().st_mtime < limit:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:  # gone meanwhile
            continue


def _chosen(user: User, ids: Sequence[int]) -> list[HrOrder]:
    """The same orders the instant print takes: the user's visible people, not cancelled, register order."""
    return list(
        HrOrder.objects.filter(pk__in=ids, employee__in=access.visible_employees(user))
        .exclude(state=OrderState.CANCELLED)
        .select_related("employee")
        .order_by("date", "pk")[:LIMIT]
    )


def _label(order: HrOrder) -> str:
    return f"Тушаал № {order.number or 'дугаар байхгүй'}, ажилтны код {order.employee.code}"


def run(token: str, user_id: int, ids: Sequence[int]) -> None:
    """Build the PDF of the job and write its result. Never raises (it runs in a thread nobody waits for)."""
    folder = _folder(token)
    if folder is None:
        return
    try:
        user = User.objects.get(pk=user_id)
        chosen = _chosen(user, ids)
        if not chosen:
            _write(folder, {**_read(folder), "state": "failed", "message": NOTHING})
            return
        data, printed = order_docs.render_pdf_many(chosen, user)
        (folder / "result.pdf").write_bytes(data)
        for order in printed:
            record_safe(Category.EXPORT, "download_order", actor=user, message=_label(order))
        _write(folder, {**_read(folder), "state": "ready", "count": len(printed)})
    except order_docs.OrderDocError:
        _write(folder, {**_read(folder), "state": "failed", "message": NOTHING})
    except Exception:  # noqa: BLE001  (the user must see «failed», not a job that stays «preparing»)
        logger.exception("print job %s failed", token)
        _write(folder, {**_read(folder), "state": "failed", "message": FAILED})


def _run_in_thread(token: str, user_id: int, ids: Sequence[int]) -> None:
    try:
        run(token, user_id, ids)
    finally:
        connections.close_all()  # this thread's own database connection; the web request's is not touched


def _read(folder: Path) -> dict[str, Any]:
    try:
        data = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def start(user: User, ids: Sequence[int]) -> str:
    """Start a job for these order ids and return its token. With PRINT_JOBS_INLINE (tests) it runs at once."""
    _sweep()
    token = secrets.token_urlsafe(18)
    folder = _root() / token
    folder.mkdir(parents=True)
    _write(folder, {"user": user.pk, "state": "running", "created": time.time(), "count": len(ids)})
    if getattr(settings, "PRINT_JOBS_INLINE", False):
        run(token, user.pk, list(ids))
    else:
        threading.Thread(target=_run_in_thread, args=(token, user.pk, list(ids)), daemon=True, name=f"print-{token[:6]}").start()
    return token


def status(user: User, token: str) -> dict[str, Any] | None:
    """`{state: running|ready|failed, count, message}` of the user's own job, else None (unknown or not theirs)."""
    folder = _folder(token)
    if folder is None or not folder.is_dir():
        return None
    data = _read(folder)
    if data.get("user") != user.pk:
        return None
    state = data.get("state", "failed")
    if state == "running" and time.time() - float(data.get("created", 0)) > STALE_AFTER:
        return {"state": "failed", "count": data.get("count", 0), "message": RESTARTED}
    return {"state": state, "count": data.get("count", 0), "message": data.get("message", "")}


def pdf_path(user: User, token: str) -> Path | None:
    """The finished PDF of the user's own job, else None."""
    info = status(user, token)
    folder = _folder(token)
    if info is None or info["state"] != "ready" or folder is None:
        return None
    path = folder / "result.pdf"
    return path if path.is_file() else None
