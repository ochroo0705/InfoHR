"""The catalogue of every old-program report (the «Тайлан» menu). Names are copied from the old program."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    key: str  # the address /reports/<key>/ once built
    group: str  # a code from GROUPS
    title: str
    old_form: str  # the form name in the old MACS program, for HR to match against
    description: str


GROUPS: tuple[tuple[str, str], ...] = (
    ("staff", "Ажилтны жагсаалт, судалгаа"),
    ("movement", "Шилжилт хөдөлгөөн, тушаал"),
    ("leave", "Чөлөө, ирц"),
    ("development", "Сургалт, эрүүл мэнд, үнэлгээ"),
    ("safety", "Хөдөлмөрийн аюулгүй байдал"),
    ("other", "Бусад"),
)

CATALOGUE: tuple[Entry, ...] = (
    Entry("staff-list", "staff", "Ажилчдын жагсаалт", "frmEmpList", "Ажилтнуудын жагсаалт, баганаа өөрөө сонгоно"),
    Entry("employee-info", "staff", "Ажилчдын мэдээлэл", "frmReportEmp", "Ажилтан бүрийн үндсэн мэдээлэл"),
    Entry(
        "statistics",
        "staff",
        "Дэлгэрэнгүй хайлт, статистик",
        "frmGenReport",
        "Ажилтнуудын тоо хүйс, боловсрол, хот зэрэг шинжээр",
    ),
    Entry("ages", "staff", "Ажилтнуудын насны судалгаа", "frmAgingReport", "Ажилтнууд насны бүлгээр"),
    Entry(
        "elders",
        "staff",
        "Өндөр настнуудын судалгаа",
        "frmElderList",
        "Өндөр настай ажилтнууд, холбоо барих мэдээлэлтэй",
    ),
    Entry("children", "staff", "Хүүхдийн судалгаа", "frmRepChildren", "Ажилтнуудын хүүхэд, насаар нь"),
    Entry(
        "sizes", "staff", "Гутал, хувцасны хэмжээний судалгаа", "frmSizeReport", "Ажилтан бүрийн хувцас, гутлын хэмжээ"
    ),
    Entry(
        "contacts", "staff", "Ажилчидтай холбоо барих", "frmRepContacting", "Ажилтнуудтай хэзээ, юуны учир холбогдсон"
    ),
    Entry(
        "engineers",
        "staff",
        "Инженер, техникийн ажилтны судалгаа",
        "frmRepNAZG",
        "Инженер, техникийн ажилтнуудын тоо оноор",
    ),
    Entry(
        "household-income",
        "staff",
        "Өрхийн амьжиргааны баталгаажих түвшний тайлан",
        "frmIncome",
        "Ажилтны өрхийн нэг гишүүнд ногдох орлого",
    ),
    Entry(
        "movements",
        "movement",
        "Ажилчдын шилжилт хөдөлгөөний тайлан",
        "frmRepMovement",
        "Хугацаанд ажилд орсон, шилжсэн, гарсан ажилтнууд",
    ),
    Entry(
        "history", "movement", "Шилжилт хөдөлгөөний жагсаалт", "frmHistoryList", "Ажилтны ажлын түүх, өөрчлөлт бүрээр"
    ),
    Entry(
        "leavers",
        "movement",
        "Ажлаас чөлөөлөгдсөн ажилчдын судалгаа",
        "frmRepFiredWorkers",
        "Ажлаас гарсан ажилтнууд, шалтгаантай нь",
    ),
    Entry("orders", "movement", "Хүний нөөцийн тушаалууд", "frmRepCommand", "Хугацаанд гарсан хүний нөөцийн тушаалууд"),
    Entry("discipline", "movement", "Ажилчдын сахилгын шийтгэл", "frmRepDiscipline", "Ногдуулсан сахилгын шийтгэлүүд"),
    Entry("awards", "movement", "Ажилчдын шагнал урамшуулал", "frmRepAward", "Олгосон шагнал, урамшуулал"),
    Entry(
        "annual-leave",
        "leave",
        "Ээлжийн амралтын тайлан",
        "frmVacReport",
        "Ажилтан бүрийн ээлжийн амралт: эрх, эдэлсэн, үлдсэн",
    ),
    Entry("leave-balance", "leave", "Чөлөөний тайлан", "frmEntitRep", "Чөлөөний төрөл бүрийн үлдэгдэл"),
    Entry("absences", "leave", "Амралт, чөлөөний тайлан", "frmHoliday", "Хугацаанд бүртгэгдсэн амралт, чөлөө"),
    Entry(
        "absence-totals",
        "leave",
        "Чөлөө, таслалт, хоцролтын тайлан",
        "frmAbsentRep",
        "Ажилтан бүрийн чөлөө, таслалт, хоцролтын нийлбэр",
    ),
    Entry(
        "away-on-date",
        "leave",
        "Чөлөөтэй буюу байхгүй байгаа ажилчдын жагсаалт",
        "frmLeaveEmps",
        "Тухайн өдөр ажил дээрээ байхгүй ажилтнууд",
    ),
    Entry("leave-requests", "leave", "Чөлөө хүссэн жагсаалт", "frmLeaveList", "Чөлөөний хүсэлтүүд, төлөвөөр нь"),
    Entry("training", "development", "Сургалтын тайлан", "frmTrainingRep", "Ажилтнуудын хамрагдсан сургалтууд"),
    Entry("skill-tasks", "development", "Ур чадварын даалгавар", "frmSkillWorkRep", "Ур чадварын даалгавар, хэлтсээр"),
    Entry(
        "health-checks",
        "development",
        "Эрүүл мэндийн үзлэгт хамрагдсан тайлан",
        "frmRepBody",
        "Эрүүл мэндийн үзлэгт хамрагдсан ажилтнууд",
    ),
    Entry(
        "performance",
        "development",
        "Нэмэгдэх гүйцэтгэлийн үнэлгээний тайлан",
        "frmAddedValRep",
        "Ажилтны гүйцэтгэлийн үнэлгээ улирлаар",
    ),
    Entry(
        "performance-summary",
        "development",
        "Ажилчдын гүйцэтгэлийн үнэлгээний нэгтгэл",
        "frmAddedValRep2",
        "Гүйцэтгэлийн үнэлгээний нэгтгэл",
    ),
    Entry("accidents", "safety", "Үйлдвэрийн ослын тайлан", "frmRepFacc1", "Хугацаанд гарсан үйлдвэрлэлийн осол"),
    Entry("poisoning", "safety", "Хурц хордлогын тайлан", "frmRepFacc2", "Хугацаанд гарсан хурц хордлого"),
    Entry("loans", "other", "Зээл олгосон тайлан", "frmLoanRep", "Ажилтнуудад олгосон зээл"),
    Entry("gifts-given", "other", "Хүүхдэд бэлэг олгосон жагсаалт", "frmGivenPresent", "Ажилтны хүүхдэд олгосон бэлэг"),
    Entry("gifts-due", "other", "Хүүхдэд бэлэг олгох", "frmChildPresent", "Энэ жил бэлэг авах хүүхдүүд"),
    Entry(
        "complaints",
        "other",
        "Үйлчлүүлэгчийн санал, гомдлын тайлан",
        "frmComplaintRep",
        "Үйлчлүүлэгчийн санал, гомдол",
    ),
)
