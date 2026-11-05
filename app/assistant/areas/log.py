"""Help entries for the logs «Бүртгэл» (inventory rows 58-60 of docs/assistant-coverage-inventory.md).

The employee log needs macs.view_employees (`logs.views.employee_log`); the system log needs accounts.view_audit
(`logs.views.system_log`). The Excel download of each log needs accounts.export_lists: it is said in the note, not as
a label, because that switch can be turned off.
"""

from datetime import date

from accounts.models import User

from assistant.entry import HelpEntry

EXCEL_NOTE = "Жагсаалтыг Excel файлаар татах товч зөвхөн экспортлох эрхтэй хүнд харагдана."


def _employee_log(user: User, day: date) -> bool:
    return user.has_perm("macs.view_employees")


def _system_log(user: User, day: date) -> bool:
    return user.has_perm("accounts.view_audit")


ENTRIES: tuple[HelpEntry, ...] = (
    HelpEntry(
        key="log.employee",
        title="Ажилтны бүртгэл",
        steps=(
            "Дээд цэсээс «Бүртгэл»-ийг сонгоно (ихэвчлэн «Тайлан» цэсний доор байна). "
            "Нээгдсэн хуудсанд «Ажилтны бүртгэл» таб идэвхтэй байна.",
            "Хайлтад ажилтны нэр эсвэл өөрчлөлтийн тайлбарын үг бичнэ. «Хугацаа» талбараар огнооны хязгаар тавина.",
        ),
        url_name="logs:employee",
        modal=False,
        need=_employee_log,
        labels=("Тайлан", "Бүртгэл", "Ажилтны бүртгэл", "Хугацаа"),
        words=("ажилтны өөрчлөлтийн түүх", "хэн юу өөрчилсөн", "мэдээллийн түүх", "өөрчлөлтийн бүртгэл"),
        examples=("ажилтны мэдээлэл хэзээ өөрчлөгдсөнийг хаанаас харах вэ", "хэн ажилтны мэдээлэл засснаа харах"),
        note=EXCEL_NOTE,
    ),
    HelpEntry(
        key="log.system",
        title="Системийн бүртгэл",
        steps=(
            "Дээд цэсээс «Бүртгэл»-ийг сонгоно. «Системийн бүртгэл» табыг сонгоно.",
            "Хайлтад хэн хийснийг, IP хаяг эсвэл зорилтын үгийг бичиж шүүнэ. «Ангилал»-аар төрлөөр шүүнэ.",
        ),
        url_name="logs:system",
        modal=False,
        need=_system_log,
        labels=("Бүртгэл", "Системийн бүртгэл", "Ангилал"),
        words=("системийн бүртгэл", "нэвтрэлт", "хэн нэвтэрсэн", "IP хаяг", "эрх солигдсон"),
        examples=("систем дээр хэн нэвтэрснийг хаанаас харах вэ", "IP хаягаар үйлдлүүдийг шүүж харах"),
        note=f"Системийн бүртгэлд нэвтрэлт, эрх солигдох зэрэг системийн үйлдлүүд бичигдэнэ. {EXCEL_NOTE}",
    ),
)
