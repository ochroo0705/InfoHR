"""Help entries for «Тохиргоо» (inventory rows 64-74 of docs/assistant-coverage-inventory.md).

The position-slot plan (`employees.views_slots`) needs employees.manage_position_slots. The Django admin («Админ хэсэг»)
checks each model's own permission and `is_staff` (the admin site's check), so each admin entry needs the view or change
right of its model. The Admin role group has no default rights on users, groups, company settings, order templates or
departments and positions, so those entries show only to a user who holds the rights; the recruitment settings and the
assistant pages are checked by their own admins (the Admin group or the view rights).
"""

from datetime import date

from accounts import modules
from accounts.models import User
from accounts.roles import ADMIN
from employees.models import CompanySettings

from assistant.entry import HelpEntry


def _slots(user: User, day: date) -> bool:
    return user.has_perm("employees.manage_position_slots")


def _slot_override(user: User, day: date) -> bool:
    """Shown only while the position-slot limit is switched on (CompanySettings.enforce_position_slots)."""
    return _slots(user, day) and CompanySettings.objects.filter(pk=1, enforce_position_slots=True).exists()


def _admin_site(user: User, *perms: str) -> bool:
    """The admin site's check (staff) and the model's view or change right."""
    return user.is_staff and any(user.has_perm(perm) for perm in perms)


def _users(user: User, day: date) -> bool:
    return _admin_site(user, "accounts.view_user", "accounts.change_user")


def _roles(user: User, day: date) -> bool:
    return _admin_site(user, "auth.view_group", "auth.change_group")


def _company(user: User, day: date) -> bool:
    return _admin_site(user, "employees.view_companysettings", "employees.change_companysettings")


def _order_templates(user: User, day: date) -> bool:
    return _admin_site(user, "employees.view_ordertemplate", "employees.change_ordertemplate")


def _departments(user: User, day: date) -> bool:
    """The entry opens the department page, so the department right is needed (positions: see the note)."""
    return _admin_site(user, "macs.view_department", "macs.change_department")


def _recruitment_settings(user: User, day: date) -> bool:
    """The recruitment settings admin: staff, and superuser or the Admin group (recruitment/admin.py)."""
    return (
        modules.enabled("recruitment")
        and user.is_staff
        and (user.is_superuser or user.groups.filter(name=ADMIN).exists())
    )


def _assistant(user: User, day: date) -> bool:
    """The entry opens the question log, which needs view_helpquestion (its admin has no change right)."""
    return _admin_site(user, "assistant.view_helpquestion")


ENTRIES: tuple[HelpEntry, ...] = (
    HelpEntry(
        key="settings.slots",
        title="Орон тооны төлөвлөгөө",
        steps=(
            "Дээд цэсний «Тохиргоо» хэсгээс «Орон тооны төлөвлөгөө»-г сонгоно.",
            "Жилийг хуудасны өмнөх, дараагийн жилийн товчоор солино. "
            "Мөр бүрт орон тоо, ашиглаж буй тоо, сул орон тоо харагдана.",
        ),
        url_name="employees:slots",
        modal=False,
        need=_slots,
        labels=("Тохиргоо", "Орон тооны төлөвлөгөө", "Ашиглаж буй", "Сул"),
        words=("орон тооны төлөвлөгөө", "орон тоо", "сул орон тоо", "ашиглаж буй орон тоо", "албан тушаалын орон тоо"),
        examples=("энэ жилийн орон тооны төлөвлөгөөг хаанаас харах вэ", "албан тушаал бүрийн сул орон тоог харах"),
        note="Өмнөх болон дараагийн жилийн төлөвлөгөөг ч мөн адил харна.",
    ),
    HelpEntry(
        key="settings.slot_edit",
        title="Орон тооны мөр нэмэх, засах, устгах",
        steps=(
            "«Орон тооны төлөвлөгөө» хуудсанд «Нэмэх» дарна. Албан тушаал, салбар, төрөл, он, орон тоог бөглөөд "
            "«Хадгалах» дарна.",
            "Жагсаалтын мөр дээр дарвал засварлах цонх нээгдэнэ. Тэнд орон тоог өөрчлөөд «Хадгалах» дарна.",
            "Мөрийг устгах бол засварлах цонхны «Устгах» дарна.",
        ),
        url_name="employees:slots",
        modal=False,
        need=_slots,
        labels=("Орон тооны төлөвлөгөө", "Нэмэх", "Хадгалах", "Устгах"),
        words=("орон тоо нэмэх", "орон тоо засах", "орон тооны мөр", "орон тоо устгах", "төлөвлөгөөний мөр"),
        examples=("нягтлан албан тушаалд орон тоо нэмэх хэрэгтэй", "орон тооны мөрийн тоог засах"),
        note=(
            "Анхаар: устгасан орон тооны мөр бүрмөсөн устна. Нэг албан тушаал, салбар, төрөл, оны хувьд нэг мөр байна."
        ),
    ),
    HelpEntry(
        key="settings.slot_override",
        title="Орон тооны хязгаар",
        steps=(
            "«Орон тооны төлөвлөгөө» хуудасны «Сул» тоо 0 болсон албан тушаалд ажилд авах, дахин авах хориглогдоно.",
            "Орон тооны хязгаарыг давах эрхтэй хүн ажилд авах маягтад шалтгаан бичвэл зөвшөөрч болно.",
        ),
        url_name="employees:slots",
        modal=False,
        need=_slot_override,
        labels=("Орон тооны төлөвлөгөө", "Сул", "Байгууллагын тохиргоо", "Орон тоогоор хязгаарлах"),
        words=("орон тооны хязгаар", "орон тоо дүүрсэн", "орон тоогоор хязгаарлах", "ажилд авахыг зөвшөөрөх"),
        examples=("орон тоо дүүрсэн үед ажилд авч болох уу",),
        note=(
            "Энэ хязгаар зөвхөн «Орон тоогоор хязгаарлах» асаалттай үед хүчинтэй. Асаалтгүй бол орон тоо шалгагдахгүй, "
            "зөвхөн төлөвлөгөө хөтлөгдөнө. Асаалтыг Админ солино: «Байгууллагын тохиргоо»-г зөвхөн Админ хэсгийн "
            "эрхтэй хүн нээнэ."
        ),
    ),
    HelpEntry(
        key="settings.users",
        title="Хэрэглэгчид, нууц үг, үзэх хүрээ",
        steps=(
            "«Тохиргоо» хэсгээс Админ хэсэгт орж, зүүн талын цэснээс «Хэрэглэгчид»-ийг сонгоно.",
            "Хэрэглэгчийн мөрийг нээгээд «Түр нууц үг үүсгэх» дарвал шинэ түр нууц үг нэг удаа харагдана. "
            "Ажилтан анх нэвтрэхдээ солино.",
            "«Үзэх хүрээ» хэсэгт хэрэглэгч аль салбар, хэлтсийн ажилтныг харахыг тохируулна.",
            "Ажлаас гарсан хүний «Идэвхтэй»-г унтраана.",
        ),
        url_name="admin:accounts_user_changelist",
        modal=False,
        need=_users,
        labels=("Тохиргоо", "Хэрэглэгчид", "Түр нууц үг үүсгэх", "Үзэх хүрээ", "Идэвхтэй"),
        words=("хэрэглэгч", "хэрэглэгч нэмэх", "нэвтрэх эрх", "түр нууц үг", "хэрэглэгч идэвхгүй болгох"),
        examples=("шинэ хэрэглэгчийн түр нууц үгийг хаанаас үүсгэх вэ", "хэрэглэгчийн харах хүрээг хэрхэн тохируулах"),
        note="Сүүлийн супер админыг унтраах, эрхийг нь хасах боломжгүй.",
    ),
    HelpEntry(
        key="settings.roles",
        title="Эрхийн бүлгүүд",
        steps=(
            "«Тохиргоо» хэсгээс Админ хэсэгт орж, зүүн талын цэснээс «Эрхийн бүлгүүд»-ийг сонгоно.",
            "Бүлгийг нээгээд эрхийн карт дээр хэрэгтэй эрхийг тэмдэглэнэ эсвэл арилгана.",
            "«Хадгалах» дарна.",
        ),
        url_name="admin:auth_group_changelist",
        modal=False,
        need=_roles,
        labels=("Тохиргоо", "Эрхийн бүлгүүд", "Хадгалах"),
        words=("эрхийн бүлэг", "бүлгийн эрх", "эрх өөрчлөх", "роль"),
        examples=("ажилтны эрхийн бүлэгт эрх нэмэх хаана вэ", "бүлгийн эрхийг хэрхэн солих вэ"),
        note="Бүлгийн эрх өөрчлөгдөхөд тухайн бүлгийн бүх хэрэглэгч шинэ эрхээр ажиллана.",
    ),
    HelpEntry(
        key="settings.company",
        title="Байгууллагын тохиргоо",
        steps=(
            "«Тохиргоо» хэсгээс Админ хэсэгт орж, «Байгууллагын тохиргоо»-г нээнэ.",
            "Байгууллагын нэр, захирлын нэрийг бичнэ.",
            "«Тушаал шаардах өөрчлөлтүүд» хэсэгт тушаалаар батлуулах өөрчлөлтийн төрлүүдийг тэмдэглэнэ.",
            "«Орон тоогоор хязгаарлах»-ыг асаавал орон тоо дүүрсэн үед ажилд авахыг хориглоно.",
            "«Хадгалах» дарна.",
        ),
        url_name="admin:employees_companysettings_changelist",
        modal=False,
        need=_company,
        labels=(
            "Тохиргоо",
            "Байгууллагын тохиргоо",
            "Тушаал шаардах өөрчлөлтүүд",
            "Орон тоогоор хязгаарлах",
            "Хадгалах",
        ),
        words=("байгууллагын тохиргоо", "тушаал шаардах", "байгууллагын нэр", "захирлын нэр"),
        examples=(
            "байгууллагын нэр, захирлын нэрийг хаанаас засах вэ",
            "тушаалгүйгээр хадгалах өөрчлөлтийг хаанаас тохируулах",
        ),
        note="Тушаал шаардахгүй гэж тохируулсан өөрчлөлтийг тушаалгүйгээр хадгалж, хүчинтэй өдрөөс нь мөрдөнө.",
    ),
    HelpEntry(
        key="settings.order_templates",
        title="Тушаалын загварууд",
        steps=(
            "«Тохиргоо» хэсгээс Админ хэсэгт орж, «Тушаалын загварууд»-ыг нээнэ.",
            "Тушаалын төрлийг нээгээд Word (.docx) загвар файлаа оруулна. "
            "Файл оруулаагүй бол стандарт загвар ашиглагдана.",
            "«Хадгалах» дарна.",
        ),
        url_name="admin:employees_ordertemplate_changelist",
        modal=False,
        need=_order_templates,
        labels=("Тохиргоо", "Тушаалын загварууд", "Хадгалах"),
        words=("тушаалын загвар", "word загвар", "docx загвар", "тушаал хэвлэх загвар"),
        examples=("тушаалын word загварыг хаанаас солих вэ", "стандарт тушаалын загварыг өөрийн файлаар солих"),
        note="Зөвхөн .docx файл, 5 MB-аас ихгүй оруулна. Загварт буруу талбарын нэр байвал хадгалахгүй.",
    ),
    HelpEntry(
        key="settings.departments",
        title="Хэлтэс, албан тушаал",
        steps=(
            "«Тохиргоо» хэсгээс Админ хэсэгт орж, «Хэлтсүүд»-ийг нээнэ.",
            "Нэрийг нь бичээд «Идэвхтэй»-г тэмдэглэнэ. Нэр солиход ажилтны бүртгэлд шинэ нэр харагдана.",
            "Ашиглагдаж байгаа хэлтсийг устгах боломжгүй.",
            "Албан тушаалыг «Албан тушаалууд» хуудаснаас ижил журмаар засна; тэр хуудсыг нээх эрх хэрэгтэй.",
        ),
        url_name="admin:macs_department_changelist",
        modal=False,
        need=_departments,
        labels=("Тохиргоо", "Хэлтсүүд", "Албан тушаалууд", "Идэвхтэй"),
        words=("хэлтэс", "албан тушаал", "хэлтэс нэмэх", "албан тушаал нэмэх", "хэлтсийн нэр"),
        examples=("шинэ хэлтэс нэмэх хэрэгтэй", "албан тушаалын нэрийг хаанаас солих вэ"),
    ),
    HelpEntry(
        key="settings.recruitment",
        title="Ажилд авах тохиргоо",
        steps=(
            "«Тохиргоо» хэсгээс Админ хэсэгт орж, «Ажилд авах тохиргоо»-г нээнэ. Зөвхөн нэг мөр байна.",
            "Мөрийг нээгээд татгалзсан ажил хүсэгчийг хадгалах хугацааг сараар бичнэ.",
            "«Хадгалах» дарна.",
        ),
        url_name="admin:recruitment_recruitmentsettings_changelist",
        modal=False,
        need=_recruitment_settings,
        labels=("Тохиргоо", "Ажилд авах тохиргоо", "Хадгалах"),
        words=("ажилд авах тохиргоо", "татгалзсан хадгалах хугацаа", "анкет хадгалах хугацаа"),
        examples=("татгалзсан өргөдлийг хэдэн сар хадгалдаг вэ", "ажил хүсэгчийн хадгалах хугацааг хаанаас өөрчлөх вэ"),
        note=(
            "Анхаар: хугацаа дууссан татгалзсан ажил хүсэгчийг ажилд авах хэсгийн цэвэрлэх хуудаснаас "
            "бүрмөсөн устгаж болно."
        ),
    ),
    HelpEntry(
        key="settings.assistant",
        title="Туслахын асуултууд, засвар",
        steps=(
            "«Тохиргоо» хэсгээс Админ хэсэгт орж, «Туслахын асуултууд»-ыг нээнэ. "
            "Хэрэглэгчдийн асуулт, хариулт харагдана.",
            "Буруу хариулт гарсан асуултын мөрийн «Засах» дарвал зөв хариулттай шинэ жишээ нээгдэнэ.",
            "«Сурсан жишээ, тест» хуудсанд засварыг идэвхтэй болгох эсвэл идэвхгүй болгоно.",
        ),
        url_name="admin:assistant_helpquestion_changelist",
        modal=False,
        need=_assistant,
        labels=("Тохиргоо", "Туслахын асуултууд", "Засах", "Сурсан жишээ, тест"),
        words=("туслах асуулт", "асуултын бүртгэл", "туслахыг засах", "буруу хариулт засах", "сурсан жишээ"),
        examples=("туслахын буруу хариултыг хаанаас засах вэ", "туслахын асуултын жагсаалтыг хаанаас харах вэ"),
        note=(
            "Асуултыг засах, устгах боломжгүй. «Засах» товч зөвхөн засвар нэмэх эрхтэй хүнд харагдана. "
            "Засварыг идэвхтэй эсвэл идэвхгүй болгоход засвар өөрчлөх эрх хэрэгтэй; устгахгүй."
        ),
    ),
)
