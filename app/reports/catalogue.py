"""The catalogue of every old-program report (the «Тайлан» menu). Names were copied from the old program, then
reworded to be told apart; the old names stay searchable as `aliases`, `old_form` is the old form code."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    key: str  # the address /reports/<key>/ once built
    group: str  # a code from GROUPS
    title: str
    old_form: str  # the form name in the old MACS program, for HR to match against
    description: str
    aliases: tuple[str, ...] = ()  # the report's former names, still found by a typed word


GROUPS: tuple[tuple[str, str], ...] = (
    ("staff", "Ажилтны жагсаалт, судалгаа"),
    ("movement", "Шилжилт хөдөлгөөн, тушаал"),
    ("leave", "Чөлөө, ирц"),
    ("development", "Сургалт, эрүүл мэнд, үнэлгээ"),
    ("safety", "Хөдөлмөрийн аюулгүй байдал"),
    ("other", "Бусад"),
)

CATALOGUE: tuple[Entry, ...] = (
    Entry(
        "staff-list",
        "staff",
        "Ажилтны хүснэгт",
        "frmEmpList",
        "Нэг мөрөнд нэг ажилтан; хүссэн баганаа сонгож хүснэгт хийнэ",
        ("Ажилчдын жагсаалт", "Ажилтны товч анкет"),
    ),
    Entry(
        "children",
        "staff",
        "Ажилтнуудын хүүхдүүд",
        "frmRepChildren",
        "Хүүхэд бүрийг нас, эцэг эхийн хамт жагсаана",
        ("Хүүхдийн судалгаа",),
    ),
    Entry(
        "contacts",
        "staff",
        "Ажилчидтай холбоо барих",
        "frmRepContacting",
        "Ажилтнуудтай хэзээ, юуны учир холбогдсон",
        (),
    ),
    Entry(
        "engineers",
        "staff",
        "Инженер, техникийн ажилтны судалгаа",
        "frmRepNAZG",
        "Инженер, техникийн ажилтнуудын тоо оноор",
        (),
    ),
    Entry(
        "household-income",
        "staff",
        "Өрхийн амьжиргааны баталгаажих түвшний тайлан",
        "frmIncome",
        "Ажилтны өрхийн нэг гишүүнд ногдох орлого",
        (),
    ),
    Entry(
        "movements",
        "movement",
        "Орсон, шилжсэн, гарсан",
        "frmRepMovement",
        "Ажилд орсон, шилжсэн, дэвшсэн, буурсан, гарсан өөрчлөлтүүд; салбар, хэлтэс, төрлөөр шүүнэ",
        ("Ажилчдын шилжилт хөдөлгөөний тайлан",),
    ),
    Entry(
        "history",
        "movement",
        "Ажлын түүх: бүх өөрчлөлт",
        "frmHistoryList",
        "Цалин, гэрээ, урт чөлөө зэрэг бүх өөрчлөлтийг ажилтнаар нь шүүж харна",
        ("Шилжилт хөдөлгөөний жагсаалт",),
    ),
    Entry(
        "leavers",
        "movement",
        "Ажлаас чөлөөлөгдсөн ажилчдын судалгаа",
        "frmRepFiredWorkers",
        "Ажлаас гарсан ажилтнууд, шалтгаантай нь",
        (),
    ),
    Entry(
        "orders", "movement", "Хүний нөөцийн тушаалууд", "frmRepCommand", "Хугацаанд гарсан хүний нөөцийн тушаалууд", ()
    ),
    Entry(
        "discipline", "movement", "Ажилчдын сахилгын шийтгэл", "frmRepDiscipline", "Ногдуулсан сахилгын шийтгэлүүд", ()
    ),
    Entry("awards", "movement", "Ажилчдын шагнал урамшуулал", "frmRepAward", "Олгосон шагнал, урамшуулал", ()),
    Entry(
        "annual-leave",
        "leave",
        "Ээлжийн амралт: эрх, эдэлсэн, үлдсэн",
        "frmVacReport",
        "Ажилтан бүрийн ээлжийн амралт: эрх, эдэлсэн, үлдсэн",
        ("Ээлжийн амралтын тайлан",),
    ),
    Entry(
        "leave-balance",
        "leave",
        "Чөлөөний үлдэгдэл (төрлөөр)",
        "frmEntitRep",
        "Чөлөөний төрөл бүрээр ажилтан хэдийг эдэлж, хэд үлдсэнийг харуулна",
        ("Чөлөөний тайлан",),
    ),
    Entry(
        "absences",
        "leave",
        "Чөлөөний түүх (хугацаагаар)",
        "frmHoliday",
        "Сонгосон хугацаанд хэн хэзээ чөлөө авсныг мөр мөрөөр харуулна",
        ("Амралт, чөлөөний тайлан",),
    ),
    Entry(
        "absence-totals",
        "leave",
        "Чөлөө, таслалт, хоцролтын нийлбэр",
        "frmAbsentRep",
        "Ажилтан бүрийн нийт хоног, цагийг нэг мөрөнд нэгтгэнэ",
        ("Чөлөө, таслалт, хоцролтын тайлан",),
    ),
    Entry(
        "away-on-date",
        "leave",
        "Чөлөөтэй буюу байхгүй байгаа ажилчдын жагсаалт",
        "frmLeaveEmps",
        "Тухайн өдөр ажил дээрээ байхгүй ажилтнууд",
        (),
    ),
    Entry(
        "leave-requests",
        "leave",
        "Чөлөөний хүсэлтүүд",
        "frmLeaveList",
        "Хүсэлт бүрийг төлвөөр нь (хүлээгдэж буй, батлагдсан, татгалзсан) харуулна",
        ("Чөлөө хүссэн жагсаалт",),
    ),
    Entry("training", "development", "Сургалтын тайлан", "frmTrainingRep", "Ажилтнуудын хамрагдсан сургалтууд", ()),
    Entry(
        "skill-tasks", "development", "Ур чадварын даалгавар", "frmSkillWorkRep", "Ур чадварын даалгавар, хэлтсээр", ()
    ),
    Entry(
        "health-checks",
        "development",
        "Эрүүл мэндийн үзлэгт хамрагдсан тайлан",
        "frmRepBody",
        "Эрүүл мэндийн үзлэгт хамрагдсан ажилтнууд",
        (),
    ),
    Entry(
        "performance",
        "development",
        "Нэмэгдэх гүйцэтгэлийн үнэлгээний тайлан",
        "frmAddedValRep",
        "Ажилтны гүйцэтгэлийн үнэлгээ улирлаар",
        (),
    ),
    Entry(
        "performance-summary",
        "development",
        "Ажилчдын гүйцэтгэлийн үнэлгээний нэгтгэл",
        "frmAddedValRep2",
        "Гүйцэтгэлийн үнэлгээний нэгтгэл",
        (),
    ),
    Entry("accidents", "safety", "Үйлдвэрийн ослын тайлан", "frmRepFacc1", "Хугацаанд гарсан үйлдвэрлэлийн осол", ()),
    Entry("poisoning", "safety", "Хурц хордлогын тайлан", "frmRepFacc2", "Хугацаанд гарсан хурц хордлого", ()),
    Entry("loans", "other", "Зээл олгосон тайлан", "frmLoanRep", "Ажилтнуудад олгосон зээл", ()),
    Entry(
        "gifts-given",
        "other",
        "Олгосон бэлгүүд",
        "frmGivenPresent",
        "Өмнө нь олгосон бэлгийг хүүхэд бүрээр харуулна",
        ("Хүүхдэд бэлэг олгосон жагсаалт",),
    ),
    Entry(
        "gifts-due",
        "other",
        "Бэлэг авах хүүхдүүд (энэ жил)",
        "frmChildPresent",
        "Энэ жил бэлэг авах насны хүүхдүүд",
        ("Хүүхдэд бэлэг олгох",),
    ),
    Entry(
        "complaints",
        "other",
        "Үйлчлүүлэгчийн санал, гомдлын тайлан",
        "frmComplaintRep",
        "Үйлчлүүлэгчийн санал, гомдол",
        (),
    ),
)
