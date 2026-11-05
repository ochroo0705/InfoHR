"""Help entries for the checklists «Чеклист» (inventory rows 44-49 of docs/assistant-coverage-inventory.md).

«Миний даалгавар» is the owner's list: any signed-in user may open it (`checklists.views.mine`), and it is empty for a
user who owns no task. The employee page's Ажил tab holds the offboarding panel (`checklists/_employee_section.html`):
undo and cancel need `access.can_untick` / `access.can_cancel` (manage_employees), starting needs `access.can_start`
(the termination right). The templates are the Admin's (manage_checklists), as the admin screens check.
"""

from datetime import date

from accounts.models import User
from checklists import access as checklist_access

from assistant.entry import HelpEntry


def _signed_in(user: User, day: date) -> bool:
    return user.is_active


def _undo(user: User, day: date) -> bool:
    return checklist_access.can_untick(user)


def _start(user: User, day: date) -> bool:
    return checklist_access.can_start(user)


def _templates(user: User, day: date) -> bool:
    return user.has_perm("checklists.manage_checklists")


ENTRIES: tuple[HelpEntry, ...] = (
    HelpEntry(
        key="checklist.mine",
        title="Миний даалгавар",
        steps=(
            "Дээд талын «Хайх» товчийг дарж «Миний даалгавар» гэж бичээд сонгоно. Өнөөдрийн хуудасны "
            "даалгавар таныг хүлээж байна гэсэн мэдэгдлийг дарж ч нээж болно.",
            "Жагсаалтад таны биелүүлэх даалгавар, хугацаа нь эхлээд дуусах нь дээрээ харагдана.",
            "Биелүүлсэн даалгавраа мөрийн баруун талын товчоор тэмдэглэнэ. Тэр даруй жагсаалтаас алга болно.",
        ),
        url_name="checklists:mine",
        modal=False,
        need=_signed_in,
        labels=("Хайх", "Миний даалгавар"),
        words=("миний даалгавар", "надад оноогдсон даалгавар", "хийх ажлууд", "даалгавар тэмдэглэх"),
        examples=("миний хийх ёстой даалгаврууд хаана харагдах вэ", "надад оноогдсон даалгаврыг хаанаас харах вэ"),
        note=(
            "Даалгаврыг зөвхөн хариуцагч нь тэмдэглэнэ; Админ аль ч нээлттэй даалгаврыг тэмдэглэж болно. "
            "Даалгавар байхгүй бол хуудас хоосон харагдана."
        ),
    ),
    HelpEntry(
        key="checklist.undo",
        title="Жагсаалтын даалгаврыг буцаах, жагсаалтыг цуцлах",
        steps=(
            "Ажилтны хуудсыг нээгээд «Ажил» табыг сонгоно.",
            "«Ажлаас гарах жагсаалт» хэсгийн биелсэн даалгаврын баруун талд байгаа «Буцаах» товчийг дарвал "
            "даалгавар дахин идэвхтэй болно.",
            "Жагсаалтыг бүхэлд нь болиулах бол хэсгийн гарчгийн баруун талд байгаа «Цуцлах» товчийг дарна.",
        ),
        url_name="employees:list",
        modal=False,
        need=_undo,
        labels=("Ажил", "Ажлаас гарах жагсаалт", "Буцаах", "Цуцлах"),
        words=(
            "даалгаврыг буцаах",
            "жагсаалтыг цуцлах",
            "буруу тэмдэглэсэн даалгавар",
            "ажлаас гарах жагсаалтыг цуцлах",
        ),
        examples=("буруу тэмдэглэсэн даалгаврыг яаж буцаах вэ", "ажлаас гарах жагсаалтыг хаанаас цуцлах вэ"),
        note=(
            "Анхаар: «Цуцлах» дарсан жагсаалтыг буцааж нээхгүй. Нээлттэй даалгавар нь цаашид үргэлжлэхгүй, "
            "дахин эхлүүлбэл шинэ жагсаалт үүснэ. "
            "Хоёулаа ажилтан засах эрхтэй хүнд л харагдана. Ажлаас чөлөөлөх өөрчлөлтөд аль хэдийн холбогдсон "
            "жагсаалтыг буцаах, цуцлах боломжгүй."
        ),
        person_tab="work",
    ),
    HelpEntry(
        key="checklist.start",
        title="Ажлаас гарах жагсаалт эхлүүлэх",
        steps=(
            "Ажилтны хуудсыг нээгээд «Ажил» табыг сонгоно.",
            "«Ажлаас гарах жагсаалт» хэсэгт «Сүүлийн ажлын өдөр»-ийг сонгоод «Жагсаалт эхлүүлэх» дарна.",
            "Даалгаврууд хариуцагч бүрийн жагсаалтад очно.",
        ),
        url_name="employees:list",
        modal=False,
        need=_start,
        labels=("Ажил", "Ажлаас гарах жагсаалт", "Сүүлийн ажлын өдөр", "Жагсаалт эхлүүлэх"),
        words=("ажлаас гарах жагсаалт", "жагсаалт эхлүүлэх", "ажлаас гарах даалгавар", "сүүлийн ажлын өдөр"),
        examples=("ажилтан ажлаасаа гарахад жагсаалтаа хаанаас эхлүүлэх вэ", "ажлаас гарах жагсаалтыг хаанаас нээх вэ"),
        note=(
            "Ажлаас гарах жагсаалт ажлаас чөлөөлөх өөрчлөлтөөс өмнө эхэлдэг. "
            "Жагсаалтын загвар байхгүй бол энэ хэсэг харагдахгүй."
        ),
        person_tab="work",
    ),
    HelpEntry(
        key="checklist.templates",
        title="Жагсаалтын загвар засах",
        steps=(
            "Админы цэсийн «Тохиргоо» хэсгээс «Жагсаалтын загвар»-ыг сонгоно.",
            "Засах загвараа нээгээд даалгавар бүрт «Хариуцах»-д эрхтэй роль (бүлэг) эсвэл «Шууд удирдлага»-ыг сонгоно. "
            "Тухайн ролийн хүн байхгүй бол Админ хүлээнэ.",
            "«Хугацаа (өдөр)» талбарт загвар эхлэх өдрөөс хэдэн өдрийн дараах хугацааг бичээд хадгална. "
            "Хасах утгатай байж болно.",
        ),
        url_name="admin:checklists_checklisttemplate_changelist",
        modal=False,
        need=_templates,
        labels=("Тохиргоо", "Жагсаалтын загвар", "Хариуцах", "Шууд удирдлага", "Хугацаа (өдөр)"),
        words=("жагсаалтын загвар", "загвар засах", "даалгаврын загвар", "загварт даалгавар нэмэх"),
        examples=("ажлаас гарах жагсаалтын даалгаврыг хаанаас тохируулах вэ", "даалгаврын загварыг яаж засах вэ"),
        note=(
            "Загвар засахад одоо явж буй жагсаалт өөрчлөгдөхгүй; шинэ загвар дараа эхлэх жагсаалтад хамаарна. "
            "Зөвхөн Админ засах эрхтэй."
        ),
    ),
)
