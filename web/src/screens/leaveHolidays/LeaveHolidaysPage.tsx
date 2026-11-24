import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import {
  useHolidayAction,
  useLeaveHolidays,
  type HolidayActionIn,
  type LeaveWriteResultOut,
} from "../../api/leaveSetup";
import type { ApiFailure } from "../../api/mutate";
import { Forbidden } from "../../routes/ErrorPage";
import { BOXED } from "../../widgets/FormFields";
import { DatePicker } from "../../widgets/DatePicker";
import { SAVE_FAILED_TEXT } from "../employee/PageForm";

// Port of app/leave/templates/leave/holidays.html at /leave/holidays/: the public holidays of one year. Classes, Mongolian
// text and the element order are copied from the template. The year is in the address (?year=); a junk year is this year
// on the server. The page keeps the default (narrow) width, as the Django page does. Each write answers with its own
// refusal text, which shows in the red box; a refused add keeps the typed date and name.
const TITLE = "Баярын өдрүүд";
const PAGE_TITLE_SUFFIX = " · MACS Human Capital";
const LOAD_FAILED = "Мэдээлэл ачаалж чадсангүй.";
const LEAD =
  "Бямба, ням гараг үргэлж амралтын өдөр. Цагаан сар зэрэг хөдөлгөөнт баяр, Засгийн газраас нэмж зарласан амралтын өдрийг гараар нэмнэ.";

// The outcome of one write: ok, or the message the red box shows.
type Outcome = { ok: true } | { ok: false; message: string };

// A refused answer's text: the service's own text, then the form and field messages.
function messageOf(result: LeaveWriteResultOut): string {
  const fieldMessages = Object.values(result.field_errors).flat();
  return [result.error, ...result.form_errors, ...fieldMessages].filter(Boolean).join(" ") || SAVE_FAILED_TEXT;
}

export function LeaveHolidaysPage() {
  const [search] = useSearchParams();
  const query = useLeaveHolidays(search.get("year") ?? undefined);
  const action = useHolidayAction();
  const data = query.data;
  const [error, setError] = useState<string | null>(null);
  const [date, setDate] = useState("");
  const [name, setName] = useState("");
  const [pending, setPending] = useState(false);
  // A ref, not state: a second click in the same tick sends nothing.
  const busy = useRef(false);

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = TITLE + PAGE_TITLE_SUFFIX;
    return () => {
      document.title = previous;
    };
  }, []);

  // A user without the right is refused on the first request: the forbidden screen, as the other pages.
  if ((query.error as { status?: number } | null)?.status === 403) return <Forbidden />;
  if (data === undefined) {
    return query.isError ? (
      <p role="alert" className="text-sm text-red-600">
        {LOAD_FAILED}
      </p>
    ) : null;
  }

  // Sends one holiday write. Null when a write is already running (a second click sends nothing).
  const send = async (input: HolidayActionIn): Promise<Outcome | null> => {
    if (busy.current) return null;
    busy.current = true;
    setPending(true);
    try {
      const result = await action.mutateAsync(input);
      return result.ok ? { ok: true } : { ok: false, message: messageOf(result) };
    } catch (failure) {
      const messages = (failure as Partial<ApiFailure>).formErrors ?? [];
      return { ok: false, message: messages.join(" ") || SAVE_FAILED_TEXT };
    } finally {
      busy.current = false;
      setPending(false);
    }
  };

  const addHoliday = async (event: FormEvent) => {
    event.preventDefault();
    const outcome = await send({ action: "add", year: data.year, date, name });
    if (outcome === null) return;
    if (outcome.ok) {
      setDate("");
      setName("");
      setError(null);
    } else {
      setError(outcome.message);
    }
  };

  const prefill = async () => {
    const outcome = await send({ action: "prefill", year: data.year });
    if (outcome === null) return;
    setError(outcome.ok ? null : outcome.message);
  };

  const deleteHoliday = async (day: string) => {
    const outcome = await send({ action: "delete", year: data.year, date: day });
    if (outcome === null) return;
    setError(outcome.ok ? null : outcome.message);
  };

  return (
    <div>
      <div className="flex items-center gap-3">
        <h1 className="mr-auto text-xl font-semibold">{`${TITLE} — ${data.year}`}</h1>
        <Link
          to={`?year=${data.year - 1}`}
          replace
          className="rounded border border-slate-300 px-3 py-1 text-sm"
        >
          {`← ${data.year - 1}`}
        </Link>
        <Link
          to={`?year=${data.year + 1}`}
          replace
          className="rounded border border-slate-300 px-3 py-1 text-sm"
        >
          {`${data.year + 1} →`}
        </Link>
      </div>
      <p className="mt-2 text-sm text-slate-500">{LEAD}</p>
      {error !== null ? <p className="mt-3 rounded bg-red-50 p-2 text-sm text-red-700">{error}</p> : null}

      <div className="mt-4">
        <button
          type="button"
          disabled={pending}
          onClick={() => void prefill()}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
        >
          {`Тогтмол баярыг бөглөх (${data.fixed_count})`}
        </button>
      </div>

      <form className="mt-3 flex gap-2 text-sm" onSubmit={(event) => void addHoliday(event)}>
        <DatePicker
          name="date"
          value={date}
          onChange={setDate}
          ariaLabel="Огноо"
          className={BOXED}
        />
        <input
          type="text"
          name="name"
          placeholder="Нэр"
          aria-label="Нэр"
          value={name}
          onChange={(event) => setName(event.target.value)}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={pending}
          className="rounded-lg bg-violet-600 px-3 py-2 text-white hover:bg-violet-700"
        >
          Нэмэх
        </button>
      </form>

      <table className="mt-4 w-full text-sm">
        <tbody>
          {data.holidays.map((holiday) => (
            <tr key={holiday.date} className="border-t border-slate-100">
              <td className="py-2">{holiday.date}</td>
              <td>{holiday.name}</td>
              <td className="text-right">
                <button
                  type="button"
                  disabled={pending}
                  onClick={() => void deleteHoliday(holiday.date)}
                  className="text-red-600"
                >
                  Устгах
                </button>
              </td>
            </tr>
          ))}
          {data.holidays.length === 0 ? (
            <tr>
              <td colSpan={3} className="py-6 text-center text-slate-500">
                {data.empty_text}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
