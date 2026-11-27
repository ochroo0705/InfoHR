import { useEffect, useId, useRef, useState, type CSSProperties, type MouseEvent } from "react";
import { useReportingLine, type ReportingPersonOut } from "../../api/employee";
import { photoSrc, photoSrcSet } from "../../lib/photo";
import { DatePicker } from "../../widgets/DatePicker";
import { normalise } from "../../widgets/dateLogic";
import { RL_TEXT, orDash, showLabel, staggerMs, untilLabel } from "./reportingText";

// Avatar background tones for a person without a photo. Chosen by pk, so one person keeps one colour.
// Each one gives white text at least 4.5:1.
const AVATAR_TONES = ["bg-violet-700", "bg-emerald-700", "bg-amber-700", "bg-slate-600"];

function Avatar({ person }: { person: ReportingPersonOut }) {
  if (person.photo_url) {
    return (
      <img
        src={photoSrc(person.photo_url)}
        srcSet={photoSrcSet(person.photo_srcset)}
        alt=""
        width={36}
        height={36}
        className="h-9 w-9 flex-none rounded-full object-cover"
      />
    );
  }
  const tone = AVATAR_TONES[Math.abs(person.pk) % AVATAR_TONES.length];
  return (
    <span
      aria-hidden="true"
      className={`flex h-9 w-9 flex-none items-center justify-center rounded-full text-xs font-semibold text-white ${tone}`}
    >
      {person.given_initial}
    </span>
  );
}

// The contact card of one person: department, phone and email as plain text. It stays mounted and unfolds like the
// hidden stack; while closed it is inert, so it is out of the tab order and the accessibility tree.
function PersonCard({ person, id, open }: { person: ReportingPersonOut; id: string; open: boolean }) {
  const rows = [
    { label: RL_TEXT.department, value: person.department },
    { label: RL_TEXT.phone, value: person.work_phone },
    { label: RL_TEXT.email, value: person.email },
  ];
  return (
    <div
      id={id}
      role="group"
      aria-label={person.full_name}
      data-rl-card={person.pk}
      data-open={open || undefined}
      inert={!open}
      className="rl-card"
    >
      <div>
        <dl className="rl-card-panel border-slate-300 bg-white dark:border-slate-600 dark:bg-slate-800">
          {rows.map((row) => (
            <div key={row.label} className="rl-card-row">
              <dt className="text-slate-600 dark:text-slate-300">{row.label}</dt>
              <dd className="text-slate-800 dark:text-slate-100">{orDash(row.value)}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}

// One manager (or the employee) as a button: avatar, name, position and the «until» date when set. A press toggles
// its contact card. A box inside the collapsed (inert) stack cannot be pressed.
function PersonBox({
  person,
  me = false,
  open,
  cardId,
  onToggle,
}: {
  person: ReportingPersonOut;
  me?: boolean;
  open: boolean;
  cardId: string;
  onToggle: (pk: number) => void;
}) {
  const palette = me
    ? "border-violet-300 bg-violet-50 dark:border-violet-700 dark:bg-violet-950"
    : "border-slate-300 bg-white dark:border-slate-600 dark:bg-slate-800";
  const until = untilLabel(person.until);
  function handleClick(event: MouseEvent<HTMLButtonElement>) {
    if (event.currentTarget.closest("[inert]") !== null) return;
    onToggle(person.pk);
  }
  return (
    <>
      <button
        type="button"
        data-rl-box={person.pk}
        aria-expanded={open}
        aria-controls={cardId}
        onClick={handleClick}
        className={`rl-box ${me ? "rl-box-me" : ""} ${palette}`}
      >
        <Avatar person={person} />
        <span className="block min-w-0 flex-1 text-left">
          <span className="block truncate text-sm font-semibold leading-tight text-slate-800 dark:text-slate-100">
            {person.full_name}
          </span>
          <span className="block truncate text-xs text-slate-600 dark:text-slate-300">{orDash(person.position)}</span>
          {until !== "" && <span className="block truncate text-xs text-slate-600 dark:text-slate-300">{until}</span>}
        </span>
      </button>
      <PersonCard person={person} id={cardId} open={open} />
    </>
  );
}

// The reporting line of one employee: the chain of managers above them (collapsed by default), the direct manager
// and the employee. `levels` is the direct manager first.
export function ReportingLine({ pk }: { pk: number }) {
  // `day` is the text in the date box ("" = today). `chainDay` is the day whose chain is asked for: only a whole
  // date or "" is sent, so a half-typed date does not reach the API.
  const [day, setDay] = useState("");
  const [chainDay, setChainDay] = useState("");
  const query = useReportingLine(pk, chainDay);
  const [open, setOpen] = useState(false);
  // The pk of the person whose contact card is open, or null. Only one card is open at a time.
  const [openPk, setOpenPk] = useState<number | null>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const upId = useId();
  const cardBaseId = useId();
  const dayId = useId();
  const data = query.data;
  const levels = data?.levels ?? [];
  // The hidden levels, farthest first in the DOM. The nearest hidden level (levels[1]) has stagger step 0.
  const upper = levels
    .slice(1)
    .map((person, i) => ({ person, step: i }))
    .reverse();

  // Escape and a press outside the open card (and its box) close it. The listeners exist only while a card is open.
  useEffect(() => {
    if (openPk === null) return;
    const root = sectionRef.current;
    const boxOf = () => root?.querySelector<HTMLElement>(`[data-rl-box="${openPk}"]`);
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpenPk(null);
      boxOf()?.focus();
    };
    const onPress = (event: Event) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      const card = root?.querySelector(`[data-rl-card="${openPk}"]`);
      if (boxOf()?.contains(target) || card?.contains(target)) return;
      setOpenPk(null);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPress);
    document.addEventListener("mousedown", onPress);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPress);
      document.removeEventListener("mousedown", onPress);
    };
  }, [openPk]);

  function toggleCard(pk: number) {
    setOpenPk((current) => (current === pk ? null : pk));
  }

  // A change of day closes an open card; the stack's open state is left as it is.
  function changeDay(next: string) {
    setDay(next);
    if (next === "" || normalise(next) === next) setChainDay(next);
    setOpenPk(null);
  }

  const cardId = (pk: number) => `${cardBaseId}-${pk}`;

  return (
    <section
      ref={sectionRef}
      aria-label={RL_TEXT.heading}
      aria-busy={query.isPending || query.isPlaceholderData}
      className="min-w-0"
    >
      <h3 className="mb-2 text-sm font-semibold text-slate-800 dark:text-slate-100">{RL_TEXT.heading}</h3>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label htmlFor={dayId} className="text-sm text-slate-600 dark:text-slate-300">
          {RL_TEXT.date}
        </label>
        <DatePicker
          id={dayId}
          name="reporting-day"
          value={day}
          onChange={changeDay}
          ariaLabel={RL_TEXT.date}
          className="w-40 rounded-lg border border-slate-300 bg-white py-1.5 pl-3 pr-9 text-sm text-slate-800 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
        />
      </div>

      {query.isPending && <div aria-hidden="true" className="h-4 w-56 max-w-full animate-pulse rounded bg-slate-200 dark:bg-slate-700" />}

      {query.isError && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {RL_TEXT.loadError}
        </p>
      )}

      {data && levels.length === 0 && <p className="text-sm text-slate-600 dark:text-slate-300">{RL_TEXT.none}</p>}

      {data && levels.length > 0 && (
        <div className="rl-tree">
          {upper.length > 0 && (
            <div id={upId} className="rl-up" data-open={open || undefined} inert={!open}>
              <div>
                {upper.map(({ person, step }) => (
                  <div
                    key={person.pk}
                    className="rl-item"
                    style={{ "--rl-delay": `${staggerMs(step)}ms` } as CSSProperties}
                  >
                    <PersonBox
                      person={person}
                      open={openPk === person.pk}
                      cardId={cardId(person.pk)}
                      onToggle={toggleCard}
                    />
                    <span aria-hidden="true" className="rl-stem bg-slate-300 dark:bg-slate-600" />
                  </div>
                ))}
              </div>
            </div>
          )}

          <PersonBox person={levels[0]} open={openPk === levels[0].pk} cardId={cardId(levels[0].pk)} onToggle={toggleCard} />
          <span aria-hidden="true" className="rl-stem rl-stem-on bg-slate-300 dark:bg-slate-600" />
          <PersonBox
            person={data.employee}
            me
            open={openPk === data.employee.pk}
            cardId={cardId(data.employee.pk)}
            onToggle={toggleCard}
          />

          {upper.length > 0 && (
            <div className="rl-ctl">
              <button
                type="button"
                className="rl-toggle border-slate-300 bg-white text-violet-700 hover:border-violet-500 hover:bg-violet-50 dark:border-slate-600 dark:bg-slate-800 dark:text-violet-300 dark:hover:bg-slate-700"
                aria-expanded={open}
                aria-controls={upId}
                onClick={() => {
                  // Collapsing the stack also closes a card open in it, so no open card is left inside the inert stack.
                  if (open) setOpenPk(null);
                  setOpen(!open);
                }}
              >
                <svg aria-hidden="true" viewBox="0 0 12 12" className="rl-chev" focusable="false">
                  <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span>{open ? RL_TEXT.hide : showLabel(upper.length)}</span>
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
