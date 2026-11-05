"""Help entries for the Lists screen «Жагсаалтууд» (inventory rows 61-63 of docs/assistant-coverage-inventory.md).

Every list page and «Утгын холбоо» need lists.manage_lists (`lists.views`, the same check as the top bar's «Тохиргоо»
group). The names of the lists are `lists.registry.LISTS`; they are the words of the entry that adds, edits and
deletes an entry.
"""

from datetime import date

from accounts.models import User
from lists.registry import LISTS

from assistant.entry import HelpEntry

_LIST_NAMES = tuple(spec.label for spec in LISTS.values())


def _manages(user: User, day: date) -> bool:
    return user.has_perm("lists.manage_lists")


ENTRIES: tuple[HelpEntry, ...] = (
    HelpEntry(
        key="list.index",
        title="Жагсаалтуудын хуудас",
        steps=(
            "Дээд цэсний «Тохиргоо» хэсгээс «Жагсаалтууд»-ыг сонгоно.",
            "Жагсаалт бүр дээр хэдэн бичлэг байгааг харна. Засах жагсаалтаа дарж нээнэ.",
        ),
        url_name="lists:index",
        modal=False,
        need=_manages,
        labels=("Тохиргоо", "Жагсаалтууд"),
        words=("жагсаалтууд", "сонголтын жагсаалт", "жагсаалтын хуудас"),
        examples=("ажилтны бүртгэлийн сонголтын жагсаалтууд хаана байдаг вэ",),
    ),
    HelpEntry(
        key="list.entry",
        title="Жагсаалтын бичлэг нэмэх, засах, устгах",
        steps=(
            "«Жагсаалтууд» хуудаснаас жагсаалтаа нээнэ.",
            "Шинэ бичлэг нэмэх бол «Нэмэх» дарж нэрээ бичээд «Хадгалах» дарна. Жагсаалтаас хамаарч код, хэмжээ зэрэг "
            "бусад талбар ч гарна. «Сум, дүүрэг»-ийг нэмэхийн өмнө «Аймаг, хот»-оо сонгоно.",
            "Бичлэг засах бол мөр дээр дарна. Нээгдсэн цонхонд өөрчлөөд «Хадгалах» дарна.",
            "Устгах бол бичлэгээ нээгээд цонхны «Устгах» дарна.",
        ),
        url_name="lists:index",
        modal=False,
        need=_manages,
        labels=("Жагсаалтууд", "Нэмэх", "Хадгалах", "Устгах", "Сум, дүүрэг", "Аймаг, хот"),
        words=_LIST_NAMES + ("бичлэг нэмэх", "бичлэг засах", "бичлэг устгах"),
        examples=("банкны жагсаалтад шинэ банк нэмэх хэрэгтэй", "ашиглагдаж байгаа бичлэгийг устгаж болох уу"),
        note=("Анхаар: устгасан бичлэгийг буцааж сэргээхгүй. Өөр хэсэгт ашиглагдаж байгаа бичлэгийг устгах боломжгүй."),
    ),
    HelpEntry(
        key="list.meaning",
        title="Утгын холбоо",
        steps=(
            "«Жагсаалтууд» хуудасны доод хэсэгт «Утгын холбоо» байна.",
            "Программ зарим утгыг тодорхой бичлэгээр таньдаг. Жишээ нь «Монгол улс» бол иргэншилд монгол гэж тооцох "
            "улсыг сонгоно.",
            "«Нас барсан» бол ажлаас гарсан шалтгаан нь нас барсан гэж тэмдэглэгдэнэ.",
            "Жагсаалт бүрт тохирох бичлэгээ сонгоод «Хадгалах» дарна.",
        ),
        url_name="lists:meaning",
        modal=False,
        need=_manages,
        labels=("Жагсаалтууд", "Утгын холбоо", "Монгол улс", "Нас барсан", "Хадгалах"),
        words=("утгын холбоо", "монгол улс гэж тооцох", "нас барсан гэж тэмдэглэх", "иргэншил"),
        examples=("иргэншлийн сонголтод монгол гэж юуг тооцдог вэ",),
    ),
)
