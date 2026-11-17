import { useRef, useState, type FormEvent } from "react";
import { Button } from "../components/ui/button";
import { confirm } from "../widgets/confirm";
import { Modal } from "../widgets/Modal";
import { DatePicker } from "../widgets/DatePicker";
import { MoneyInput } from "../widgets/MoneyInput";
import { Select, type SelectOption } from "../widgets/Select";
import { ScrollHost } from "../widgets/Scrollbar";
import { useMnValidation } from "../widgets/validationMn";
import { useMeta } from "../shell/useMeta";

const FIVE: SelectOption[] = ["Хүний нөөц", "Санхүү", "Худалдаа", "Үйлдвэрлэл", "Маркетинг"].map((label, i) => ({
  value: String(i + 1),
  label,
}));
const TWELVE: SelectOption[] = Array.from({ length: 12 }, (_, i) => ({ value: String(i + 1), label: `${i + 1}-р сар` }));

// Development only: App.tsx registers /__widgets when import.meta.env.DEV. It shows the pop-up shell and the confirm
// dialog in their states, so they can be checked by eye without a real screen.
export default function WidgetsPage() {
  const meta = useMeta();
  const canAddLists = meta.data?.user?.perms.includes("lists.manage_lists") ?? false;
  const [plainOpen, setPlainOpen] = useState(false);
  const [dirtyOpen, setDirtyOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [answer, setAnswer] = useState<string>("");
  const [dept, setDept] = useState("");
  const [month, setMonth] = useState("");
  const [position, setPosition] = useState("");
  const [addedText, setAddedText] = useState("");
  const [birth, setBirth] = useState("");
  const [reportMonth, setReportMonth] = useState("");
  const [hired, setHired] = useState("");
  const [salary, setSalary] = useState("");
  const [demoName, setDemoName] = useState("");
  const [demoAge, setDemoAge] = useState("");
  const [demoSaved, setDemoSaved] = useState("");
  const [modalDate, setModalDate] = useState("");
  const demoForm = useRef<HTMLFormElement>(null);
  useMnValidation(demoForm);

  const saveDemo = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setDemoSaved(`Нэр: ${demoName}, нас: ${demoAge || "—"}`);
  };

  const ask = async (message: string, opts?: Parameters<typeof confirm>[1]) => {
    const yes = await confirm(message, opts);
    setAnswer(yes ? "Тийм" : "Болих");
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-6">
      <h1 className="text-lg font-semibold">Widgets (dev)</h1>

      <section className="space-y-3">
        <h2 className="sec-title">Modal</h2>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setPlainOpen(true)}>Цэвэр pop-up нээх</Button>
          <Button onClick={() => setDirtyOpen(true)}>Бичсэн pop-up нээх</Button>
        </div>
        <Modal open={plainOpen} title="Цэвэр pop-up" onClose={() => setPlainOpen(false)}>
          <p className="text-sm text-slate-600">Юу ч бичээгүй бол ✕, Esc, гаднаас дарахад шууд хаагдана.</p>
          <div className="mt-3 space-y-1">
            <label htmlFor="widgets-modal-date" className="block text-sm">
              Огноо (pop-up дотор)
            </label>
            <DatePicker id="widgets-modal-date" name="modal_date" value={modalDate} onChange={setModalDate} />
          </div>
        </Modal>
        <Modal
          open={dirtyOpen}
          dirty={typed !== ""}
          title="Бичсэн pop-up"
          onClose={() => {
            setDirtyOpen(false);
            setTyped("");
          }}
        >
          <label className="block text-sm">
            Нэр
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            />
          </label>
          <p className="mt-2 text-xs text-slate-500">Текст бичсэн бол ✕, Esc эсвэл гаднаас дарахад асууна.</p>
        </Modal>
      </section>

      <section className="space-y-3">
        <h2 className="sec-title">Select</h2>
        <div className="grid max-w-3xl gap-4 sm:grid-cols-3">
          <div className="space-y-1">
            <label htmlFor="widgets-dept" className="block text-sm">
              5 сонголт (жагсаалт)
            </label>
            <Select id="widgets-dept" name="dept" value={dept} onChange={setDept} options={FIVE} required />
          </div>
          <div className="space-y-1">
            <label htmlFor="widgets-month" className="block text-sm">
              12 сонголт (хайлттай)
            </label>
            <Select id="widgets-month" name="month" value={month} onChange={setMonth} options={TWELVE} />
          </div>
          <div className="space-y-1">
            <label htmlFor="widgets-position" className="block text-sm">
              Нэмэх хайрцагтай
            </label>
            <Select
              id="widgets-position"
              name="position"
              value={position}
              onChange={setPosition}
              options={FIVE}
              addUrl="/widgets/add-demo"
              canAdd={canAddLists}
              addModal
              onAddModal={(text) => setAddedText(text)}
            />
          </div>
        </div>
        <p className="text-sm text-slate-600">Нэмэх дарсан нэр: {addedText || "—"}</p>
      </section>

      <section className="space-y-3">
        <h2 className="sec-title">DatePicker</h2>
        <div className="grid max-w-3xl gap-4 sm:grid-cols-3">
          <div className="space-y-1">
            <label htmlFor="widgets-birth" className="block text-sm">
              Өдөр
            </label>
            <DatePicker id="widgets-birth" name="birth" value={birth} onChange={setBirth} />
          </div>
          <div className="space-y-1">
            <label htmlFor="widgets-report-month" className="block text-sm">
              Сар
            </label>
            <DatePicker
              id="widgets-report-month"
              name="report_month"
              mode="month"
              value={reportMonth}
              onChange={setReportMonth}
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="widgets-hired" className="block text-sm">
              Хугацаа (2026 он)
            </label>
            <DatePicker
              id="widgets-hired"
              name="hired"
              min="2026-01-01"
              max="2026-12-31"
              value={hired}
              onChange={setHired}
            />
          </div>
        </div>
        <p className="text-sm text-slate-600">
          Өдөр: {birth || "—"} · Сар: {reportMonth || "—"} · Хугацаа: {hired || "—"}
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="sec-title">MoneyInput</h2>
        <div className="max-w-xs space-y-1">
          <label htmlFor="widgets-salary" className="block text-sm">
            Цалин (₮)
          </label>
          <MoneyInput id="widgets-salary" name="salary" value={salary} onChange={setSalary} />
        </div>
        <p className="text-sm text-slate-600">Утга: {salary || "—"}</p>
      </section>

      <section className="space-y-3">
        <h2 className="sec-title">Mongolian validation</h2>
        <form ref={demoForm} onSubmit={saveDemo} className="grid max-w-xs gap-3">
          <div className="space-y-1">
            <label htmlFor="widgets-demo-name" className="block text-sm">
              Нэр (заавал)
            </label>
            <input
              id="widgets-demo-name"
              name="demo_name"
              required
              value={demoName}
              onChange={(e) => setDemoName(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="widgets-demo-age" className="block text-sm">
              Нас (тоо)
            </label>
            <input
              id="widgets-demo-age"
              name="demo_age"
              type="number"
              value={demoAge}
              onChange={(e) => setDemoAge(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <Button type="submit">Хадгалах</Button>
          </div>
        </form>
        <p className="text-sm text-slate-600">Хадгалсан: {demoSaved || "—"}</p>
      </section>

      <section className="space-y-3">
        <h2 className="sec-title">ScrollHost</h2>
        <div data-testid="widgets-scrollhost" className="max-w-md">
          <ScrollHost className="h-[200px] overflow-auto rounded-lg border border-slate-300 p-3 text-sm">
            {Array.from({ length: 30 }, (_, i) => (
              <p key={i} className="leading-6">
                Мөр {i + 1}
              </p>
            ))}
          </ScrollHost>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="sec-title">Confirm</h2>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => void ask("Хадгалах уу?")}>Энгийн асуулт</Button>
        </div>
        <p className="text-sm text-slate-600">Сүүлийн хариулт: {answer || "—"}</p>
      </section>
    </div>
  );
}
