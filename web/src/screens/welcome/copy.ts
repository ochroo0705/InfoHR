// Every visible string on /welcome lives here, so English can follow later without hunting through the components.
// The Mongolian below is a first draft written by the builder; the user, as the native reader, corrects it.
export const copy = {
  brand: "MACS Human Capital",
  login: "Нэвтрэх",
  demoCta: "Демо хүсэх",
  nav: {
    label: "Үндсэн цэс",
  },
  hero: {
    eyebrow: "Хүний нөөцийн систем",
    titleLine1: "Хүний нөөцийн ажил",
    titleLine2: "нэг дор",
    lead: "Ажилтан, тушаал, чөлөө, тайлан. Тайван, хурдан.",
  },
  proof: {
    line: "MACS-ийн бүрэлдэхүүнд багтсан · MACS XE4-тэй зэрэгцэн ажиллана",
    counterLabel: "хүртэл ажилтантай байгууллагад зориулсан",
  },
  showcase: {
    steps: [
      {
        title: "Тушаалын бүртгэл",
        text: "Тушаалууд нэг дор жагсаж харагдана. Хэвлэхийн өмнө тушаалыг урьдчилан харна.",
      },
      {
        title: "Чөлөөний хуанли",
        text: "Чөлөөг багийн хуанлид харж, нэг дор хянана.",
      },
      {
        title: "Өнөөдөр",
        text: "Анхаарал шаардсан зүйлс нэг хэсэгт тодорхой харагдана.",
      },
      {
        title: "AI туслах",
        text: "Асуултаа энгийн үгээр бичнэ. Хариулт товч байдаг, зарим асуултад хүснэгтээр ирнэ.",
      },
    ],
  },
  more: {
    title: "Бусад боломжууд",
    cards: [
      {
        title: "Эрх, өөрийн үйлчилгээ",
        text: "Ажилтан өөрийн хуудсанд дэлгэрэнгүй мэдээлэл, чөлөөний үлдэгдэл, хүсэлтээ харна. Хязгаарлагдсан эрхтэй хэрэглэгч зөвхөн өөрт оноосон баг, салбар, хэлтсээ харна.",
      },
      {
        title: "Тайлан",
        text: "Тайланг шууд гаргаж, файлаар татаж авна.",
      },
      {
        title: "Үйлдлийн түүх",
        text: "Ажилтны өөрчлөлт, тохиргооны өөрчлөлтийг хэн, хэзээ хийснийг хадгална.",
      },
      {
        title: "Утасны харагдац",
        text: "Үндсэн хуудсууд утсан дээр ажиллана. Өргөн хүснэгт хөндлөн гүйлгэгдэнэ.",
      },
    ],
  },
  form: {
    title: "Демо хүсэх",
    labels: {
      email: "Имэйл",
      name: "Нэр",
      organisation: "Байгууллага",
      phone: "Утас",
      size: "Ажилтны тоо",
      note: "Нэмэлт мэдээлэл",
    },
    optionalPhone: "Утас заавал биш",
    requiredMark: "*",
    requiredNote: "* Заавал бөглөх талбар",
    sizeNone: "Сонгоно уу",
    sizeBands: ["1-10", "11-50", "51-200", "200+"],
    submit: "Хүсэлт илгээх",
    privacy: "Таны мэдээллийг зөвхөн демо холбогдох зорилгоор ашиглана.",
    thanksTitle: "Баярлалаа!",
    thanksText: "Таны хүсэлтийг хүлээн авлаа. Бид удахгүй холбогдоно.",
    errors: {
      emailRequired: "Имэйл хаягаа оруулна уу.",
      emailInvalid: "Имэйл хаяг буруу байна.",
      nameRequired: "Нэрээ оруулна уу.",
      organisationRequired: "Байгууллагын нэрээ оруулна уу.",
      tooLong: "Хэт урт байна.",
      submitFailed: "Хүсэлт илгээхэд алдаа гарлаа. Дахин оролдоно уу.",
    },
  },
  footer: {
    company: "Инфосистемс ХХК",
    phone: "+976 7012 6399",
    email: "contact@infosystems.mn",
    hours: "Даваа - Баасан 09:00 - 18:00",
  },
} as const;
