"""System log service: record() writes one SystemLogEntry.

Design: docs/superpowers/specs/2026-10-29-audit-logs-design.md
"""

import logging

from django.db import models, transaction
from django.http import HttpRequest

from accounts import audit_context
from accounts.models import SystemLogEntry, User

logger = logging.getLogger(__name__)


class Category(models.TextChoices):
    ACCESS = "access", "Нэвтрэлт, эрх"
    SETTINGS = "settings", "Тохиргоо"
    IMPORT = "import", "Импорт, MACS"
    EXPORT = "export", "Экспорт, татаж авалт"
    # Employee records and the checklists built on them. No DB field has choices, so no migration.
    HR = "hr", "Ажилтан, HR"


# Action code -> Mongolian label. Codes are stored in the database; labels are for screens.
ACTIONS: dict[str, str] = {
    "login": "Нэвтэрсэн",
    "login_failed": "Нэвтрэх оролдлого амжилтгүй",
    "logout": "Системээс гарсан",
    "password_changed": "Нууц үгээ солисон",
    "password_reset": "Нууц үг түр нууцаар сэргээсэн",
    "login_created": "Нэвтрэх эрх үүсгэсэн",
    "user_active_changed": "Нэвтрэх эрх идэвхтэй эсэх солигдсон",
    "superuser_changed": "Супер эрх солигдсон",
    "staff_changed": "Админ хэсэгт орох эрх солигдсон",
    "groups_changed": "Ролийн бүлэг солигдсон",
    "permissions_changed": "Тусгай эрх солигдсон",
    "setting_added": "Тохиргоо нэмсэн",
    "setting_changed": "Тохиргоо өөрчилсөн",
    "setting_deleted": "Тохиргоо устгасан",
    "staff_import": "Ажилтны мэдээлэл импортолсон",
    "staff_import_download": "Импортын загвар татсан",
    "staff_import_rejected_download": "Алдаатай мөрүүд татсан",
    "order_template_download": "Тушаалын загвар татсан",
    "macs_sync": "MACS-ийн өгөгдлийг синк хийсэн",
    "export_report": "Тайлан экспортолсон",
    "export_list": "Жагсаалт экспортолсон",
    "export_log": "Бүртгэл экспортолсон",
    "print_page": "Хуудас хэвлэсэн",
    "download_order": "Тушаал татсан",
    "position_slot_overridden": "Орон тоо дүүрсэн ч ажилд авахыг зөвшөөрсөн",
    "module_switched": "Модуль асаасан, унтраасан",
    "position_slot_added": "Орон тооны мөр нэмсэн",
    "position_slot_changed": "Орон тооны мөр өөрчилсөн",
    "position_slot_deleted": "Орон тооны мөр устгасан",
    "checklist_started": "Ажлаас гарах жагсаалт эхлүүлсэн",
    "checklist_task_ticked": "Жагсаалтын даалгаврыг биелсэн гэж тэмдэглэсэн",
    "checklist_task_unticked": "Жагсаалтын даалгаврын биелэлтийг буцаасан",
    "checklist_cancelled": "Ажлаас гарах жагсаалт цуцалсан",
    "vacancy_created": "Ажлын байр нээсэн",
    "vacancy_changed": "Ажлын байр өөрчилсөн",
    "candidate_added": "Ажил хүсэгч нэмсэн",
    "candidate_moved": "Ажил хүсэгчийг шат шилжүүлсэн",
    "candidate_rejected": "Ажил хүсэгчийг татгалзсан",
    "candidate_reopened": "Ажил хүсэгчийг дахин нээсэн",
    "candidate_hired": "Ажил хүсэгчийг ажилд авсан",
    "candidate_commented": "Ажил хүсэгчид сэтгэгдэл бичсэн",
    "candidate_file_added": "Ажил хүсэгчийн файл нэмсэн",
    "candidate_file_downloaded": "Ажил хүсэгчийн файл татсан",
    "candidates_purged": "Хуучин ажил хүсэгчдыг устгасан",
    "selfform_created": "Ажилтны маягтын холбоос үүсгэсэн",
    "selfform_revoked": "Ажилтны маягтын холбоосыг цуцалсан",
    "selfform_extended": "Ажилтны маягтын холбоосын хугацааг сунгасан",
    "selfform_submitted": "Ажилтан маягтаа илгээсэн",
    "selfform_sent_back": "Ажилтны маягтыг засахаар буцаасан",
    "selfform_rejected": "Ажилтны маягтыг татгалзсан",
    "selfform_confirmed": "Ажилтны маягтыг баталгаажуулсан",
    "selfform_purged": "Ажилтны маягтын хуучин өгөгдлийг устгасан",
}


def record(
    category: str,
    action: str,
    *,
    actor: User | None = None,
    message: str = "",
    target_type: str = "",
    target_label: str = "",
    changes: list[dict[str, str]] | None = None,
    ip: str | None = None,
) -> SystemLogEntry:
    """Write one entry. actor and ip default to the current request's user and IP.

    Raises on database failure; use record_safe() where the audited action must not fail.
    """
    if actor is None:
        actor = audit_context.current_user()
    if ip is None:
        ip = audit_context.current_ip()
    return SystemLogEntry.objects.create(
        actor=actor,
        actor_name=actor.username if actor is not None else "",
        category=category,
        action=action,
        message=message,
        target_type=target_type,
        target_label=target_label,
        changes=changes or [],
        ip=ip,
    )


def record_safe(
    category: str,
    action: str,
    *,
    actor: User | None = None,
    message: str = "",
    target_type: str = "",
    target_label: str = "",
    changes: list[dict[str, str]] | None = None,
    ip: str | None = None,
) -> SystemLogEntry | None:
    """Like record(), but a failure is logged and swallowed, so the audited action still goes ahead.

    The savepoint keeps a failed insert from breaking an outer transaction.
    """
    try:
        with transaction.atomic():
            return record(
                category,
                action,
                actor=actor,
                message=message,
                target_type=target_type,
                target_label=target_label,
                changes=changes,
                ip=ip,
            )
    except Exception:
        logger.exception("System log entry was not saved: %s %s", category, action)
        return None


def record_export(
    request: HttpRequest,
    action: str,
    what: str,
    *,
    filters: str = "",
    rows: int | None = None,
) -> None:
    """Log one export, print or download by the request's user. `filters` is a readable label (never the raw
    query string) and `rows` the row count. Never raises: the export itself must go ahead either way."""
    user = getattr(request, "user", None)
    actor = user if user is not None and user.is_authenticated else None
    parts = [what]
    if filters:
        parts.append(filters)
    if rows is not None:
        parts.append(f"{rows} мөр")
    record_safe(Category.EXPORT, action, actor=actor, message=" · ".join(parts))
