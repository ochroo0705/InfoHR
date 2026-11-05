"""Help entries for the reports «Тайлан» (inventory rows 50-57 of docs/assistant-coverage-inventory.md).

Every built report of `reports.registry` gets one generated entry, except the leave reports (the leave area's entries
answer for those). The catalogue, the export buttons and the saved views are written by hand.

Every report page has «Хэвлэх» and «Цэвэрлэх». «Excel» needs the export right (accounts.export_lists) and «Багана» is
only on the reports that let the user pick columns, so the generated entries do not quote them.
«Хадгалах» is only on the reports that keep saved views (staff-list). A saved view is renamed and deleted by its author
or by a user with reports.manage_saved_views (`reports.views._may_change`).
The module-level import of `reports.registry` is safe: it has no cycle with assistant and
touches no database at import, so the reports are not looked up at call time.
"""

from datetime import date

from accounts.models import User
from reports import registry
from reports.catalogue import CATALOGUE
from reports.types import Report

from assistant.entry import HelpEntry

# The leave reports: no `report.*` entry is generated for them. «leave-balance» and «leave-requests» are answered by the
# leave area's entries; the other four have the written entries below.
LEAVE_REPORT_KEYS = frozenset(
    {"annual-leave", "leave-balance", "leave-requests", "absences", "away-on-date", "absence-totals"}
)

# The old names of each report, as the catalogue keeps them (found by a typed word, as the Ctrl+K palette does).
_FORMER_NAMES: dict[str, tuple[str, ...]] = {entry.key: entry.aliases for entry in CATALOGUE}


def _viewer(user: User, day: date) -> bool:
    return user.has_perm("reports.view_reports")


def _saved_view(user: User, day: date) -> bool:
    return registry.can_open(user, registry.REPORTS["staff-list"])


def _generated(report: Report) -> HelpEntry:
    """The entry for one built report: the same right as the report page (`registry.can_open`)."""

    def need(user: User, day: date) -> bool:
        return registry.can_open(user, report)

    return HelpEntry(
        key=f"report.{report.key}",
        title=report.title,
        steps=("«Тайлан» цэснээс энэ тайланг сонгоно.",),
        url_name="reports:report",
        modal=False,
        need=need,
        labels=("Тайлан", "Цэвэрлэх"),
        words=_FORMER_NAMES.get(report.key, ()),
        url_args=(report.key,),
    )


def _leave_report(key: str, steps: tuple[str, ...], examples: tuple[str, ...]) -> HelpEntry:
    """A written entry for a leave report that has no entry of the leave area (the same right as the report page)."""
    report = registry.REPORTS[key]

    def need(user: User, day: date) -> bool:
        return registry.can_open(user, report)

    return HelpEntry(
        key=f"report.{key}",
        title=report.title,
        steps=steps,
        url_name="reports:report",
        modal=False,
        need=need,
        labels=("Тайлан", report.title),
        words=_FORMER_NAMES.get(key, ()),
        examples=examples,
        url_args=(key,),
    )


_WRITTEN: tuple[HelpEntry, ...] = (
    HelpEntry(
        key="report.catalogue",
        title="Тайлангийн жагсаалт",
        steps=(
            "Дээд цэсний «Тайлан» хуудсанд орно. Тайлангууд бүлгээр харагдана.",
            "Хайлтын талбарт тайлангийн нэр, хуучин нэр эсвэл тайлбараар нь бичвэл жагсаалт шүүгдэнэ.",
        ),
        url_name="reports:catalogue",
        modal=False,
        need=_viewer,
        labels=("Тайлан",),
        words=("тайлангийн жагсаалт", "тайлан хаана байна", "хуучин тайлан", "MACS-ийн тайлан"),
        examples=("тайлангуудаа хаанаас харах вэ",),
        note=("Саарал харагдах тайлан одоогоор бэлэн биш байна. Таны эрх хүрэхгүй тайлан жагсаалтад огт харагдахгүй."),
    ),
    HelpEntry(
        key="report.export",
        title="Тайланг хэвлэх, Excel-ээр татах, баганыг сонгох",
        steps=(
            "«Тайлан» хуудаснаас хүссэн тайлангаа жагсаалтаас сонгоно. "
            "Тайлангийн хуудсанд шүүлтүүр, эрэмбээ тохируулна.",
            "Хэвлэхийн тулд «Хэвлэх» дарна. Хэвлэх хуудас шинэ цонхонд нээгдэнэ.",
            "Excel файл татах товч байвал түүнийг дарна. "
            "Файл нь дэлгэц дээрх багана, эрэмбэ, бүлэглэлттэй яг адил гарна.",
            "Харуулах баганыг сонгох бол «Багана» дарна. Энэ товч зарим тайланд л байна, жишээ нь «Ажилтны хүснэгт»-д.",
        ),
        url_name="reports:catalogue",
        modal=False,
        need=_viewer,
        labels=("Тайлан", "Хэвлэх", "Багана", "Ажилтны хүснэгт"),
        words=("тайлан хэвлэх", "excel татах", "тайланг excel-ээр авах", "баганыг сонгох"),
        examples=("тайланг цаасан дээр гаргах хэрэгтэй", "хүснэгтээ excel болгож хадгалах"),
        note=(
            "Excel татах товч зөвхөн тайлан татах эрхтэй (accounts.export_lists) хэрэглэгчид харагдана. Эрхгүй бол "
            "хэвлэх л боломжтой. Татсан файл, хэвлэсэн хуудас бүр системийн бүртгэлд тэмдэглэгдэнэ."
        ),
    ),
    _leave_report(
        "annual-leave",
        steps=(
            "«Тайлан» цэснээс «Ээлжийн амралт: эрх, эдэлсэн, үлдсэн» тайланг сонгоно.",
            "Хүссэн огноогоо өгөхөд ажилтан бүрийн ээлжийн амралтын эрх, эдэлсэн, үлдсэн хоног гарна.",
        ),
        examples=("ажилтан бүрийн ээлжийн амралт хэд үлдсэнийг нэг дор харах", "амралтын эрх, эдэлсэн хоногийн тайлан"),
    ),
    _leave_report(
        "absences",
        steps=(
            "«Тайлан» цэснээс «Чөлөөний түүх (хугацаагаар)» тайланг сонгоно.",
            "Хугацаагаа сонгоход хэн хэзээ чөлөө авсан нь мөр мөрөөр гарна.",
        ),
        examples=("энэ улиралд хэн хэзээ чөлөө авсныг харах", "чөлөөний түүхийг хугацаагаар нь гаргах"),
    ),
    _leave_report(
        "away-on-date",
        steps=(
            "«Тайлан» цэснээс «Чөлөөтэй буюу байхгүй ажилчид» тайланг сонгоно.",
            "Огноогоо өгөхөд тэр өдөр ажил дээрээ байхгүй ажилтнууд гарна.",
        ),
        examples=("маргааш хэн ажилдаа ирэхгүй байгааг харах", "тухайн өдөр хэн чөлөөтэй байгааг жагсаах"),
    ),
    _leave_report(
        "absence-totals",
        steps=(
            "«Тайлан» цэснээс «Чөлөө, таслалт, хоцролтын нийлбэр» тайланг сонгоно.",
            "Хугацаагаа сонгоход ажилтан бүрийн нийт хоног, цаг нэг мөрөнд нэгтгэгдэж гарна.",
        ),
        examples=("ажилтан бүрийн таслалт, хоцролтын нийлбэрийг харах", "хэн хэдэн өдөр чөлөө авсныг нэгтгэж үзэх"),
    ),
    HelpEntry(
        key="report.saved_view",
        title="Тайлангийн харагдац хадгалах, засах",
        steps=(
            "«Ажилтны хүснэгт» тайланд шүүлтүүр, баганаа тохируулаад «Хадгалах» дарна. Харагдацад нэр өгөөд хадгална.",
            "Хадгалсан харагдацыг тайлангийн дээд талын харагдацын жагсаалтаас сонгоно.",
            "Тухайн харагдацыг сонгосон үед гарах «Засах» товчоор нэрийг нь солих эсвэл «Устгах» дарж устгана.",
        ),
        url_name="reports:report",
        modal=False,
        need=_saved_view,
        labels=("Ажилтны хүснэгт", "Хадгалах", "Засах", "Устгах"),
        words=("харагдац хадгалах", "тайланг хадгалах", "хадгалсан харагдац", "харагдацыг устгах"),
        examples=("шүүсэн тайлангаа дараа ашиглахаар хадгалах", "хадгалсан харагдацын нэрийг солих"),
        note=(
            "Анхаар: харагдац устгахад зөвхөн хадгалсан тохиргоо устна, тайлангийн өгөгдөл устахгүй. "
            "Харагдацыг зөвхөн хадгалсан хүн эсвэл тайлангийн харагдац удирдах эрхтэй хэрэглэгч засах, "
            "устгах боломжтой."
        ),
        url_args=("staff-list",),
    ),
)

# The written entries first, then one generated entry per built non-leave report in the registry's order.
ENTRIES: tuple[HelpEntry, ...] = (
    *_WRITTEN,
    *(_generated(report) for report in registry.REPORTS.values() if report.key not in LEAVE_REPORT_KEYS),
)
