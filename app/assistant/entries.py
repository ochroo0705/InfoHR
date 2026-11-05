"""The help entries the assistant may answer with, and who may see each one.

Each entry is one screen or action of the system, written in plain Mongolian. `need` reuses the same rights rules as
the screens and the Ctrl+K palette, so an entry is offered only to a user who may open what it describes.
"""

from datetime import date

from accounts.models import User
from employees.palette import _LEAVE_PERMS, _allowed, _may_request_leave, _sees_requests
from leave.services.approvers import approval_enabled, may_decide

from assistant.areas import admin_settings, checklist, employee, log, me, order, recruit, report, today
from assistant.areas import list as list_area
from assistant.entry import HelpEntry

__all__ = ["ENTRIES", "ENTRY_BY_KEY", "HelpEntry", "allowed_entries"]


def _record(user: User, day: date) -> bool:
    return all(_allowed(user, perm) for perm in _LEAVE_PERMS)


def _request(user: User, day: date) -> bool:
    return _may_request_leave(user)


def _decide(user: User, day: date) -> bool:
    return approval_enabled(user) and may_decide(user, day)


def _requests(user: User, day: date) -> bool:
    return _sees_requests(user) and not _decide(user, day)


def _view(user: User, day: date) -> bool:
    return user.has_perm("leave.view_leave")


_LEAVE_ENTRIES: tuple[HelpEntry, ...] = (
    HelpEntry(
        key="leave.record",
        title="Чөлөө бүртгэх",
        steps=(
            "Дээд цэсний «Чөлөө, амралт» хуудсанд «Чөлөө бүртгэх» товч дарна.",
            "Ажилтан, чөлөөний төрөл, эхлэх, дуусах огноог сонгоно.",
            "«Хадгалах» товч дарна.",
        ),
        url_name="leave:add",
        modal=True,
        need=_record,
        labels=("Чөлөө, амралт", "Чөлөө бүртгэх", "Хадгалах"),
        words=("амралт оруулах", "чөлөө оруулах", "өвчний чөлөө", "ээлжийн амралт", "отпуск"),
        examples=("ажилтанд чөлөө яаж оруулах вэ", "амралт бүртгэх хаана байдаг вэ", "чөлөө нэмэх"),
        note="Ажилтны хуудасны чөлөөний хэсэгт ч мөн «Чөлөө бүртгэх» товч бий.",
    ),
    HelpEntry(
        key="leave.request",
        title="Чөлөө хүсэх",
        steps=(
            "Дээд цэсээс «Миний хуудас» руу орно.",
            "«Чөлөө хүсэх» товч дарна.",
            "Төрөл, огноогоо сонгоод «Хүсэлт илгээх» дарна.",
            "Батлагч шийдвэрлэхэд «Миний хуудас»-нд харагдана.",
        ),
        url_name="leave:request_new",
        modal=True,
        need=_request,
        labels=("Миний хуудас", "Чөлөө хүсэх", "Хүсэлт илгээх"),
        words=("чөлөө авах", "амралт авах", "хүсэлт гаргах"),
        examples=("би яаж чөлөө авах вэ", "амралтын хүсэлт хаанаас гаргах вэ", "чөлөө хүсэх"),
    ),
    HelpEntry(
        key="leave.decide",
        title="Чөлөөний хүсэлт батлах, татгалзах",
        steps=(
            "Дээд цэсний «Хүсэлт» хуудсыг нээнэ. Батлах хүсэлт ирсэн үед энэ цэс харагдана.",
            "Хүсэлтээ нээнэ.",
            "«Батлах» эсвэл «Татгалзах» товч дарна. Татгалзвал шалтгаанаа бичнэ.",
        ),
        url_name="leave:requests",
        modal=False,
        need=_decide,
        labels=("Хүсэлт", "Батлах", "Татгалзах"),
        words=("зөвшөөрөх", "батлах", "татгалзах", "хүсэлт шийдэх"),
        examples=("хүсэлт яаж батлах вэ", "ирсэн хүсэлтийг хаанаас зөвшөөрөх вэ"),
    ),
    HelpEntry(
        key="leave.requests",
        title="Чөлөөний хүсэлтүүдийг харах",
        steps=(
            "Дээд цэсний «Чөлөө, амралт» цэснээс «Хүсэлт» хуудсыг нээнэ.",
            "Хүсэлтүүдийг төлөвөөр нь шүүж харна.",
        ),
        url_name="leave:requests",
        modal=False,
        need=_requests,
        labels=("Чөлөө, амралт", "Хүсэлт"),
        words=("хүсэлтүүд", "ирсэн хүсэлт"),
        examples=("хүсэлтүүдийг хаанаас харах вэ",),
        note="Батлах эрх зөвхөн тохиргоонд заасан батлагчид байна.",
    ),
    HelpEntry(
        key="leave.balances",
        title="Амралтын үлдэгдэл харах",
        steps=(
            "Дээд цэсний «Чөлөө, амралт» хуудсанд орно.",
            "«Үлдэгдэл» табыг сонгоод ажилтнаа хайна.",
        ),
        url_name="leave:balances",
        modal=False,
        need=_view,
        labels=("Чөлөө, амралт", "Үлдэгдэл"),
        words=("үлдэгдэл", "хоног үлдсэн", "амралтын хоног"),
        examples=("амралтын үлдэгдэл хаана харах вэ", "хэдэн хоног үлдсэнийг шалгах"),
    ),
    HelpEntry(
        key="leave.calendar",
        title="Багийн хуанли",
        steps=(
            "Дээд цэсний «Чөлөө, амралт» хуудсанд орно.",
            "«Багийн хуанли» табыг сонгоод сар, хэлтсээ сонгоно.",
        ),
        url_name="leave:calendar",
        modal=False,
        need=_view,
        labels=("Чөлөө, амралт", "Багийн хуанли"),
        words=("хуанли", "хэн амарч байна", "чөлөөтэй хүмүүс"),
        examples=("энэ сард хэн чөлөөтэй вэ", "багийн хуанли хаана байна"),
    ),
)

# Each area's ENTRIES, in the order the areas are listed (the leave entries first, then the areas in the fixed order).
ENTRIES: tuple[HelpEntry, ...] = (
    *_LEAVE_ENTRIES,
    *today.ENTRIES,
    *employee.ENTRIES,
    *order.ENTRIES,
    *recruit.ENTRIES,
    *checklist.ENTRIES,
    *report.ENTRIES,
    *log.ENTRIES,
    *list_area.ENTRIES,
    *admin_settings.ENTRIES,
    *me.ENTRIES,
)

ENTRY_BY_KEY: dict[str, HelpEntry] = {entry.key: entry for entry in ENTRIES}


def allowed_entries(user: User, day: date) -> list[HelpEntry]:
    """The entries the user may be shown on `day`, in ENTRIES order."""
    return [entry for entry in ENTRIES if entry.need(user, day)]
