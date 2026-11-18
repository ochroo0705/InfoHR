import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { rejectSubmission, sendBack, type HireDuplicateOut, type HireReviewOut } from "../../api/hire";
import { AppLink } from "../../lib/AppLink";

// The self-form review section of the add-employee page (`employees/selfform/_review_panel.html`). The classes, the
// Mongolian texts and the element order are copied from that template. The server sends the review and the duplicate
// (the rules are in Python); React only draws them.
//
// The two decision boxes («Буцаах» and «Татгалзах») sit inside the hire form on the add-employee page (Task 13), so they
// must never block that form's native validation: they carry no `required` attribute (`aria-required` and the star in
// the label say it instead). Each button calls the API (`sendBack` / `rejectSubmission`) with the trimmed text. An empty
// box (after trimming) makes no request: the box is focused and the server's own message is shown under it, cleared
// when the user types. A refusal (ok false) shows its first message under the box and does not navigate. Success calls
// `onDone(redirect)` once. Buttons are `type="button"`, so nothing submits the hire form.

const GENERIC_FAILURE = "Сервертэй холбогдож чадсангүй. Дахин оролдоно уу.";
// The server's texts (app/employees/views_selfform.py `_NOTE_NEEDED` / `_REASON_NEEDED`).
const NOTE_NEEDED = "Засах шалтгаанаа бичнэ үү.";
const REASON_NEEDED = "Татгалзсан шалтгаанаа бичнэ үү.";

export type ReviewPanelProps = {
  review: HireReviewOut;
  // The duplicate-register warning, or null when the register number is not taken.
  duplicate: HireDuplicateOut | null;
  // The pk of the self-form submission HR decides on.
  submissionId: number;
  // Called once after a successful decision with the page to open next (the Django self-forms list).
  onDone: (redirect: string) => void;
};

type Decision = "send" | "reject";

function DuplicateWarning({ duplicate }: { duplicate: HireDuplicateOut }) {
  return (
    <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-900">
      {duplicate.visible && duplicate.employee_pk !== null ? (
        <>
          Энэ регистрийн дугаар{" "}
          <AppLink to={`/employees/${duplicate.employee_pk}/`} className="text-violet-700 hover:underline">
            {duplicate.employee_name}
          </AppLink>
          -д аль хэдийн харьяалагдсан байна.
        </>
      ) : (
        "Энэ регистрийн дугаартай ажилтан бүртгэлтэй байна."
      )}{" "}
      Энэ дугаараар шинэ ажилтан хадгалах боломжгүй. Дугаар буруу оруулсан бол дээрх талбарт зөв дугаараа бичнэ үү.
      Бусад тохиолдолд маягтыг буцаах эсвэл татгалзах.
    </div>
  );
}

// One list of «label: value» rows, or the empty line.
function PairList({ rows }: { rows: string[][] }) {
  if (rows.length === 0) {
    return <p className="mt-1 text-slate-500">бүртгэгдээгүй</p>;
  }
  return (
    <ul className="mt-1 space-y-0.5 rounded-lg bg-surface p-2">
      {rows.map(([label, value], i) => (
        <li key={i}>
          <span className="text-slate-500">{label}:</span> {value}
        </li>
      ))}
    </ul>
  );
}

export function ReviewPanel({ review, duplicate, submissionId, onDone }: ReviewPanelProps) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [noteError, setNoteError] = useState<string | null>(null);
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [finished, setFinished] = useState(false);

  const noteBox = useRef<HTMLInputElement>(null);
  const reasonBox = useRef<HTMLInputElement>(null);

  // A ref guard as well as the state: two clicks in the same tick must send one request.
  const busy = useRef(false);
  const done = useRef(false);

  // Set false on unmount: a request still pending then must not update state or call onDone.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function decide(kind: Decision) {
    if (busy.current || done.current) return;
    const box = kind === "send" ? noteBox.current : reasonBox.current;
    const text = (kind === "send" ? note : reason).trim();
    const setError = kind === "send" ? setNoteError : setReasonError;

    if (text === "") {
      // No request. The server's wording under the box, and the box focused.
      setError(kind === "send" ? NOTE_NEEDED : REASON_NEEDED);
      box?.focus();
      return;
    }

    busy.current = true;
    setError(null);
    setPending(true);
    try {
      const result =
        kind === "send"
          ? await sendBack(queryClient, submissionId, text)
          : await rejectSubmission(queryClient, submissionId, text);
      if (!mounted.current) return;
      if (!result.ok) {
        setError(result.form_errors[0] ?? GENERIC_FAILURE);
        return;
      }
      done.current = true;
      setFinished(true);
      onDone(result.redirect);
    } catch {
      if (mounted.current) setError(GENERIC_FAILURE);
    } finally {
      busy.current = false;
      if (mounted.current) setPending(false);
    }
  }

  // Enter in a box submits its own decision and does not submit the surrounding hire form.
  function onEnter(kind: Decision) {
    return (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      void decide(kind);
    };
  }

  const locked = pending || finished;

  return (
    <section
      className="rounded-xl border border-violet-300 bg-violet-50 p-4 text-sm text-slate-900"
      aria-labelledby="selfform-review-title"
    >
      <h2 id="selfform-review-title" className="font-medium text-violet-900">
        Ажилтны өөрөө бөглөсөн анкет
      </h2>
      <p className="mt-1 text-xs text-slate-500">
        Илгээсэн: {review.submitted_at}. Доорх утгыг хэсгүүдэд урьдчилан бөглөсөн; өөрчилж болно. Ажилтны анхны хариулт
        өөрчлөгдөхгүй хадгалагдана.
      </p>

      {duplicate ? <DuplicateWarning duplicate={duplicate} /> : null}

      {review.has_photo ? <p className="mt-3">Ажилтан зураг илгээсэн: хадгалахад хавсарна</p> : null}

      <h3 className="mt-4 font-medium text-slate-800">Боловсрол</h3>
      {review.education.length === 0 ? (
        <p className="mt-1 text-slate-500">бүртгэгдээгүй</p>
      ) : (
        review.education.map((row, i) => <PairList key={i} rows={row} />)
      )}

      <h3 className="mt-4 font-medium text-slate-800">Гэр бүл</h3>
      {review.family.length === 0 ? (
        <p className="mt-1 text-slate-500">бүртгэгдээгүй</p>
      ) : (
        review.family.map((row, i) => <PairList key={i} rows={row} />)
      )}

      <h3 className="mt-4 font-medium text-slate-800">Яаралтай үед холбогдох</h3>
      <PairList rows={review.contact} />

      {review.hr_note ? (
        <p className="mt-4">
          <span className="text-slate-500">HR тэмдэглэл:</span> {review.hr_note}
        </p>
      ) : null}

      {/* Controls for HR's decision. They sit in the hire form (Task 13): no `required`, buttons are type="button". */}
      <div className="mt-5 border-t border-violet-200 pt-4">
        <h3 className="font-medium text-slate-800">Анкетын шийдвэр</h3>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <label className="min-w-64 flex-1">
            <span className="block text-xs text-slate-600">Тайлбар *</span>
            <input
              ref={noteBox}
              type="text"
              name="note"
              aria-required="true"
              maxLength={500}
              value={note}
              onChange={(event) => {
                setNote(event.target.value);
                setNoteError(null);
              }}
              onKeyDown={onEnter("send")}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
            {noteError ? (
              <span role="alert" className="text-xs text-red-600">
                {noteError}
              </span>
            ) : null}
          </label>
          <button
            type="button"
            disabled={locked}
            onClick={() => void decide("send")}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm"
          >
            Буцаах
          </button>
        </div>
        <p className="mt-1 text-xs text-slate-500">
          Буцаахад ажилтан маягтаа засаж дахин илгээнэ. Тайлбарыг ажилтан харна.
        </p>

        <details className="mt-4">
          <summary className="select-none cursor-pointer rounded px-2 py-1 text-red-600 hover:bg-red-50">
            Татгалзах
          </summary>
          <div className="mt-2 rounded-lg border border-red-200 bg-red-50 p-3">
            <label className="block">
              <span className="block text-xs text-slate-600">Шалтгаан *</span>
              <input
                ref={reasonBox}
                type="text"
                name="reason"
                aria-required="true"
                maxLength={500}
                value={reason}
                onChange={(event) => {
                  setReason(event.target.value);
                  setReasonError(null);
                }}
                onKeyDown={onEnter("reject")}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              {reasonError ? (
                <span role="alert" className="text-xs text-red-600">
                  {reasonError}
                </span>
              ) : null}
            </label>
            <p className="mt-2 text-xs text-slate-500">
              Татгалзсан анкетыг дахин нээх боломжгүй. Шалтгаан анкетад хадгалагдана.
            </p>
            <button
              type="button"
              disabled={locked}
              onClick={() => void decide("reject")}
              className="mt-3 rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700"
            >
              Тийм, татгалзах
            </button>
          </div>
        </details>
      </div>
    </section>
  );
}
