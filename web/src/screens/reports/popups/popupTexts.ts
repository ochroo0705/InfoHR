// Every Mongolian text of the columns, rules and format pop-ups and the saved-view pop-up. Copied verbatim from the
// Django templates (_columns_modal.html, _rules_modal.html, _format_modal.html, _view_modal.html) and their inline
// scripts, from app/reports/forms.py (the view labels) and app/reports/views.py (the view titles).

export const COLUMNS_TEXT = {
  title: "Багана сонгох",
  group: "Бүлэглэх",
  noGroup: "Бүлэглэхгүй",
  apply: "Хэрэглэх",
  cancel: "Болих",
  loadFailed: "Мэдээлэл ачаалж чадсангүй.",
} as const;

export const RULES_TEXT = {
  title: "Шүүлтүүр",
  intro: "Нөхцөл бүр нэг багана, нэг харьцуулалт, нэг утгаас бүрдэнэ. Бүх нөхцөл биелсэн мөр харагдана.",
  advanced: "Нарийвчилсан",
  apply: "Хэрэглэх",
  cancel: "Болих",
  groupLabel: "Бүлэг:",
  rootLabel: "Бүх нөхцөл:",
  groupOpAll: "Бүгд биелсэн",
  groupOpAny: "Аль нэг нь биелсэн",
  groupOpAria: "Бүлгийн нөхцөл",
  dropGroup: "Бүлгийг устгах",
  dropGroupConfirm: "Бүлгийг бүх нөхцөлтэй нь хасах уу?",
  dropGroupOk: "Хасах",
  advancedOffConfirm: "Бүх нөхцөл нэгэн зэрэг биелсэн байх болно. Үргэлжлүүлэх үү?",
  advancedOffOk: "Үргэлжлүүлэх",
  addRule: "+ Нөхцөл нэмэх",
  addGroup: "+ Бүлэг нэмэх",
  removeRule: "Нөхцөл устгах",
  column: "Багана",
  operator: "Харьцуулалт",
  from: "Доод утга",
  to: "Дээд утга",
  value: "Утга",
  days: "хоног",
  tooLong: "Утга хэт урт байна. Нэг утга 100 тэмдэгтээс ихгүй байх ёстой.",
  ruleTooLong: "Нөхцөл хэт урт байна. Утгыг богиносгоно уу.",
} as const;

export const FORMAT_TEXT = {
  title: "Хэлбэр",
  intro: "Нийт дүн, түгжих багана, өнгөөр ялгах. Бусад шүүлтүүр хэвээр үлдэнэ.",
  totals: "Нийт дүн",
  totalsHint: "Харагдаж буй багана бүрт дүн нэмж болно. «—» бол дүн харагдахгүй.",
  noTotalColumns: "Харагдаж буй багана алга.",
  noAggregate: "—",
  pin: "Түгжих багана",
  pinHint: "Хүснэгтийг хажуу тийш гүйлгэхэд эхний хэдэн багана хэвээр үлдэх вэ.",
  marks: "Өнгөөр ялгах",
  marksHint: "Утга дүрэмд таарвал бүтэн мөр өнгөтэй харагдана. Хамгийн ихдээ 5 дүрэм.",
  addMark: "+ Өнгө нэмэх",
  noMarks: "Өнгөний дүрэм алга.",
  colour: "Өнгө",
  removeMark: "Дүрэм устгах",
  apply: "Хэрэглэх",
  cancel: "Болих",
  tooLong: "Утга хэт урт байна. Нэг утга 100 тэмдэгтээс ихгүй байх ёстой.",
  marksTooLong: "Өнгөний дүрэм хэт урт байна. Утгыг богиносгоно уу.",
} as const;

export const VIEW_TEXT = {
  newTitle: "Харагдац хадгалах",
  editTitle: "Харагдац засах",
  name: "Нэр",
  visibility: "Хэнд харагдах",
  shared: "Хамтын",
  private: "Хувийн",
  isDefault: "Нээхэд үндсэн харагдац болгох",
  save: "Хадгалах",
  cancel: "Болих",
  delete: "Устгах",
  deleteConfirm: "Энэ харагдацыг устгах уу?",
} as const;
