"""Help entries for «Миний хуудас» and the password change (inventory rows 75-76).

«Миний хуудас» is the page of the employee linked to the login, so it needs that link (`employees.access.own_employee`).
«Нууц үг солих» is for every signed-in user.
"""

from datetime import date

from accounts.models import User
from employees.access import own_employee

from assistant.entry import HelpEntry


def _own_record(user: User, day: date) -> bool:
    return own_employee(user) is not None


def _signed_in(user: User, day: date) -> bool:
    return user.is_active


ENTRIES: tuple[HelpEntry, ...] = (
    HelpEntry(
        key="me.page",
        title="Миний хуудас",
        steps=(
            "Баруун дээд буланд байгаа өөрийн нэрийн цэсээс «Миний хуудас» сонгоно. "
            "Хүний нөөцийн эрхгүй хэрэглэгчийн дээд цэсэнд «Миний хуудас» гэсэн товч бас байна.",
            "Хуудсанд таны ажлын мэдээлэл, амралтын үлдэгдэл, хүсэлтүүд болон таны гүйцэтгэх даалгавар харагдана.",
        ),
        url_name="me",
        modal=False,
        need=_own_record,
        labels=("Миний хуудас",),
        words=("миний хуудас", "өөрийн хуудас", "миний мэдээлэл"),
        examples=("өөрийн ажлын мэдээллээ хаанаас харах вэ", "миний үлдэгдэл хаана харагдах вэ"),
        note="Хуудас зөвхөн ажилтны бүртгэлтэй, өөрийн мэдээлэлтэй хэрэглэгчид харагдана.",
    ),
    HelpEntry(
        key="me.password",
        title="Нууц үг солих",
        steps=(
            "Дээд талын баруун буланд байгаа өөрийн нэрийн цэсийг нээгээд «Нууц үг солих» сонгоно.",
            "Хуучин нууц үгээ, дараа нь шинэ нууц үгээ бичнэ. Түр нууц үгээр орсон бол хуучин нууц үг асуухгүй.",
            "«Хадгалах» товчийг дарна.",
        ),
        url_name="password_change",
        modal=False,
        need=_signed_in,
        labels=("Нууц үг солих", "Хадгалах"),
        words=("нууц үг солих", "нууц үгээ өөрчлөх", "нууц үг сольж"),
        examples=("нууц үгээ хэрхэн солих вэ", "пассвордоо хаанаас өөрчлөх вэ"),
        note="Нууц үгээ мартсан бол нэвтрэх боломжгүй. Тэр тохиолдолд системийн админд хандана.",
    ),
)
