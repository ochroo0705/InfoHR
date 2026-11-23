// Invented sample data for the /welcome mockups. Names are initial + dot + surname; no real staff appear here.
// Every visible string in the Orders mockup lives in this file, so English can follow later.

export interface OrderRow {
  no: string;
  person: string;
  type: string;
}

export const orderRows: OrderRow[] = [
  { no: "0142", person: "Б. Саруул", type: "Чөлөө" },
  { no: "0143", person: "Д. Тэмүүлэн", type: "Томилгоо" },
  { no: "0144", person: "Н. Оюунаа", type: "Ээлжийн амралт" },
  { no: "0145", person: "Т. Мөнхбаяр", type: "Сургалт" },
  { no: "0146", person: "Ц. Энхжин", type: "Шилжүүлэг" },
];

// Index into orderRows of the row shown as selected in the register.
export const selectedOrderIndex = 1;

// Labels of the Orders mockup: the frame name, the register heading and the preview panel.
export const ordersMockLabels = {
  frame: "Тушаалын бүртгэлийн дэлгэц",
  title: "Тушаалын бүртгэл",
  newButton: "+ Шинэ",
  head: {
    no: "№",
    person: "Ажилтан",
    type: "Төрөл",
  },
  previewTitle: "Урьдчилан харах",
  previewOrderPrefix: "Тушаал №",
} as const;

// One leave bar per person in a 21-day window. startDay is a 0-based day index; startDay + days <= 21.
// kind: "annual" draws the leave-sky bar, "other" draws the caution-amber bar (another leave type).
export const leaveBars: { person: string; startDay: number; days: number; kind: "annual" | "other" }[] = [
  { person: "Б. Саруул", startDay: 1, days: 4, kind: "annual" },
  { person: "Д. Тэмүүлэн", startDay: 3, days: 2, kind: "other" },
  { person: "Н. Оюунаа", startDay: 8, days: 5, kind: "annual" },
  { person: "Т. Мөнхбаяр", startDay: 12, days: 3, kind: "other" },
  { person: "Ц. Энхжин", startDay: 15, days: 4, kind: "annual" },
  { person: "Л. Баярмаа", startDay: 18, days: 3, kind: "annual" },
];

// Labels of the Leave mockup. The 21 days start on a Monday, so day indexes 5, 6, 12, 13, 19 and 20 are weekends.
export const leaveMockLabels = {
  frame: "Чөлөөний хуанли",
  title: "Ирэх 3 долоо хоног",
  weekdays: ["Д", "М", "Л", "П", "Б", "Б", "Н"],
  kinds: {
    annual: "Ээлжийн амралт",
    other: "Өвчний чөлөө",
  },
} as const;

export const attentionCards: { title: string; count: number }[] = [
  { title: "Батлагдаагүй тушаал", count: 3 },
  { title: "Дуусах гэрээ", count: 5 },
  { title: "Хүлээгдэж буй чөлөө", count: 2 },
  { title: "Шинэ ажилтны бүрдүүлэлт", count: 4 },
];

// Invented people who are away today (shown as chips in the "away today" strip).
export const awayToday: string[] = ["О. Номин", "Э. Болд", "С. Ариунаа", "Г. Төмөр"];

// Labels of the Today mockup: the frame name, the heading above the cards and the "away today" strip.
export const todayMockLabels = {
  frame: "Өнөөдрийн хуудас",
  title: "Анхаарах",
  awayTitle: "Өнөөдөр чөлөөтэй",
} as const;

export const assistantQa: { question: string; columns: string[]; rows: string[][] } = {
  question: "Энэ сард чөлөө авсан ажилтнууд?",
  columns: ["Ажилтан", "Төрөл", "Хоног"],
  rows: [
    ["Б. Саруул", "Ээлжийн амралт", "4"],
    ["Д. Тэмүүлэн", "Өвчний чөлөө", "2"],
    ["Н. Оюунаа", "Ээлжийн амралт", "5"],
    ["Т. Мөнхбаяр", "Хүүхдийн чөлөө", "3"],
  ],
};

// Labels of the AI assistant mockup: the frame name, the assistant's name and the caption above its table.
export const assistantMockLabels = {
  frame: "AI туслах",
  name: "Туслах",
  you: "Та",
  answer: "Хүснэгтээр харуулав",
} as const;
