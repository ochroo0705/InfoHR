"""Help entries for the home page «Өнөөдөр» and its «Анхаарах» box (inventory rows 1-2).

The home page is the HR users' start page: it shows the company figures and who is away today. Only people the user may
see are counted (`access.visible_employees`), so the entries follow the top bar's rule: the «Өнөөдөр» link needs
`macs.view_employees`.
"""

from datetime import date

from accounts.models import User

from assistant.entry import HelpEntry


def _sees_home(user: User, day: date) -> bool:
    return user.has_perm("macs.view_employees")


ENTRIES: tuple[HelpEntry, ...] = (
    HelpEntry(
        key="today.home",
        title="Өнөөдрийн нүүр хуудас",
        steps=(
            "Дээд цэсний «Өнөөдөр» товчийг дарна.",
            "Хуудсанд ажилтны тоо, өнөөдөр хэн чөлөөтэй байгаа, удахгүй болох өдрүүд, компанийн тоо харагдана.",
        ),
        url_name="employees:today",
        modal=False,
        need=_sees_home,
        labels=("Өнөөдөр",),
        words=("нүүр хуудас", "эхлэл хуудас", "өнөөдөр"),
        examples=("нүүр хуудас хаана байна", "өнөөдрийн мэдээллээ хаанаас харах вэ"),
    ),
    HelpEntry(
        key="today.attention",
        title="Анхаарах зүйлийг «Мэдлээ» гэж тэмдэглэх",
        steps=(
            "Дээд цэсний «Өнөөдөр» хуудсанд орно.",
            "«Анхаарах» хэсгийг нээнэ. Тэнд хугацаа дуусах, бүрдүүлэлт дутуу гэх мэт зүйлс жагсана.",
            "Зүйлийн хажууд байгаа «Мэдлээ» товчийг дарна. Тэр зүйл таны жагсаалтаас түр алга болно.",
        ),
        url_name="employees:today",
        modal=False,
        need=_sees_home,
        labels=("Өнөөдөр", "Анхаарах", "Мэдлээ"),
        words=("анхаарах", "мэдлээ", "дахин харуулах", "нуух"),
        examples=("анхаарах зүйлийн жагсаалтыг хаах", "өнөөдрийн анхаарах хэсэгт гарсан зүйлийг нуух"),
        note=(
            "«Мэдлээ» зөвхөн таны өөрийн харагдах байдалд нөлөөлнө. Өгөгдөл өөрчлөгдвөл зүйл дахин гарч ирнэ. "
            "Нуусан зүйлийг буцаан харуулж болно."
        ),
    ),
)
