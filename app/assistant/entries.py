"""The help entries the assistant may answer with, and who may see each one.

Each entry is one screen or action of the system, written in plain Mongolian. `need` reuses the same rights rules as
the screens and the Ctrl+K palette, so an entry is offered only to a user who may open what it describes.
"""

from datetime import date

from accounts.models import User
from employees.palette import _LEAVE_PERMS, _allowed, _may_request_leave, _sees_requests
from leave.services.approvers import approval_enabled, may_decide

from assistant.areas import (
    admin_settings,
    checklist,
    doc_templates,
    employee,
    log,
    me,
    order,
    recruit,
    report,
    saved_views,
    today,
)
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


def _leave_setup(user: User, day: date) -> bool:
    """The holidays and the leave settings pages: the leave settings right (Admin)."""
    return user.has_perm("leave.manage_leave_settings")


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
    HelpEntry(
        key="leave.edit",
        title="Бүртгэсэн чөлөөг засах, цуцлах",
        steps=(
            "Дээд цэсний «Чөлөө, амралт» хуудасны «Бүртгэл» табыг нээнэ.",
            "Засах чөлөөгөө жагсаалтаас олж мөрийг нь дарна. Төрөл, огноог засаад «Хадгалах» дарна.",
            "Хараахан эхлээгүй чөлөөг цуцлах бол мөрийн «Цуцлах» товч дарна.",
            "Аль хэдийн эхэлсэн чөлөөг устгахгүй, мөрийн «Буруу гэж тэмдэглэх» товчоор буруу бүртгэл гэж тэмдэглэнэ.",
        ),
        url_name="leave:list",
        modal=False,
        need=_record,
        labels=("Чөлөө, амралт", "Бүртгэл", "Хадгалах", "Цуцлах", "Буруу гэж тэмдэглэх"),
        words=("чөлөө засах", "чөлөө цуцлах", "буруу бүртгэсэн чөлөө", "чөлөөний огноо өөрчлөх"),
        examples=("оруулсан амралтын огноог өөрчлөх", "буруу бүртгэсэн чөлөөг хэрхэн хасах вэ"),
        note="Цуцалсан чөлөөний хоног амралтын үлдэгдэлд буцаж нэмэгдэнэ.",
    ),
    HelpEntry(
        key="leave.holidays",
        title="Баярын өдөр бүртгэх",
        steps=(
            "Дээд цэсний «Чөлөө, амралт» хуудсанд орж, «Тохиргоо» цэснээс «Баярын өдрүүд»-ийг нээнэ.",
            "Баярын огноо, нэрийг бичээд «Нэмэх» дарна.",
            "Жил бүр давтагддаг тогтмол баярыг нэг дор оруулах бол «Тогтмол баярыг бөглөх» дарна.",
        ),
        url_name="leave:holidays",
        modal=False,
        need=_leave_setup,
        labels=("Чөлөө, амралт", "Тохиргоо", "Баярын өдрүүд", "Нэмэх", "Тогтмол баярыг бөглөх"),
        words=("баяр", "амралтын өдөр", "цагаан сар", "улсын баяр", "ажлын өдөр тоолох"),
        examples=("цагаан сарын амралтын өдрийг хаана тэмдэглэх вэ", "засгийн газрын нэмэлт амралтыг оруулах"),
        note=(
            "Бямба, ням гараг үргэлж амралтын өдөр. Цагаан сар зэрэг хөдөлгөөнт баяр, нэмж зарласан амралтыг гараар "
            "нэмнэ. Тухайн жилийн баяр бүртгээгүй бол чөлөөний ажлын өдрийг буруу тоолно."
        ),
    ),
    HelpEntry(
        key="leave.settings",
        title="Чөлөөний төрөл, батлах журмыг тохируулах",
        steps=(
            "Дээд цэсний «Чөлөө, амралт» хуудсанд орж, «Тохиргоо» цэснээс «Амралтын төрөл, тохиргоо»-г нээнэ.",
            "Шинэ төрөл нэмэх бол «Төрөл нэмэх» дарж нэр, цалинтай эсэх, ээлжийн амралтаас хасах эсэхийг сонгоно.",
            "Хүсэлтийг хэн батлахыг «Чөлөөний хүсэлтийг хэн батлах вэ» хэсэгт сонгоод «Хадгалах» дарна.",
        ),
        url_name="leave:settings",
        modal=False,
        need=_leave_setup,
        labels=(
            "Чөлөө, амралт",
            "Тохиргоо",
            "Амралтын төрөл, тохиргоо",
            "Төрөл нэмэх",
            "Чөлөөний хүсэлтийг хэн батлах вэ",
            "Хадгалах",
            "Ээлжийн амралтаас хасна",
        ),
        words=("чөлөөний төрөл", "төрөл нэмэх", "батлагч", "ээлжийн амралтын эрх", "амралтын тохиргоо"),
        examples=("шинэ төрлийн чөлөө нэмэх", "чөлөөний хүсэлтийг хэн батлахыг сонгох"),
        note=(
            "Ашиглагдаж байгаа чөлөөний төрлийг устгах боломжгүй. "
            "«Ээлжийн амралтаас хасна» гэж тэмдэглэсэн төрөл ээлжийн амралтын үлдэгдэлд тооцогдохгүй."
        ),
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
    """The entries the user may be shown on `day`: the fixed ENTRIES in their order, then the entries built now from the
    database: the user's saved report views (areas/saved_views.py), and the checklist and order templates an admin
    keeps (areas/doc_templates.py)."""
    fixed = [entry for entry in ENTRIES if entry.need(user, day)]
    dynamic = [*saved_views.entries_for(user, day), *doc_templates.entries_for(user, day)]
    return fixed + [entry for entry in dynamic if entry.need(user, day)]
