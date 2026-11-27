import { useEffect, useState } from "react";
import type { components } from "../../../api/schema";
import { AppLink } from "../../../lib/AppLink";
import { TLink } from "../../../lib/viewTransition";
import { DatePicker } from "../../../widgets/DatePicker";
import { set } from "../filterAddress";

// The calendar (app/reports/templates/reports/layouts/calendar.html, _week.html, _entry.html, UI_RULES §4b): a Monday-first
// month grid, or one week of seven days, from 640 px up; below that the same entries as a day list. Classes, Mongolian
// text and structure are copied from the templates. Every link is an in-app address from the API (AppLink, as the table
// cells). The month jump sets `lmonth` in the address (filterAddress.set) and hands the new address to onChange; every
// other part of `query` stays as typed. The arrows and «Өнөөдөр» are links; at a bound (href "") the arrow is a grey span.

type CalendarOut = components["schemas"]["ReportCalendarOut"];
type DayOut = components["schemas"]["ReportDayOut"];
type EntryOut = components["schemas"]["ReportEntryOut"];

export interface CalendarLayoutProps {
  calendar: CalendarOut;
  query: string; // the current address query (with or without its leading "?")
  onChange: (nextQuery: string) => void;
}

const WEEKDAYS = ["Да", "Мя", "Лх", "Пү", "Ба", "Бя", "Ня"];
const EMPTY_CLASS = "mt-4 py-6 text-center text-sm text-slate-400";
const TOOLS_CLASS =
  "flex min-w-0 max-w-full flex-wrap items-center justify-end gap-2";
const GROUP_CLASS = "flex max-w-full flex-wrap items-center gap-1 text-sm";
const LINK_CLASS =
  "rounded-lg border border-slate-300 bg-surface px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50";
const ARROW_CLASS =
  "rounded-lg border border-slate-300 bg-surface px-3 py-1.5 text-slate-700 hover:bg-slate-50";
const DISABLED_CLASS =
  "rounded-lg border border-slate-200 px-3 py-1.5 text-slate-300";
const CURRENT_CLASS =
  "rounded-lg border border-violet-600 px-3 py-1.5 font-semibold text-violet-700";
const WEEKDAY_CLASS =
  "px-1 py-1 text-center text-xs font-medium text-slate-500";
const MORE_CLASS = "mt-1 text-xs text-slate-500";
const SUB_EMPTY_TEXT = "Энэ сард оруулга алга";

// One entry as a chip (_entry.html): the title is a link only when the row has an href; the title attribute is the
// title with the note after a middle dot. The colour is the first passing mark, else the violet default.
function Entry({ item }: { item: EntryOut }) {
  const tip = item.note ? `${item.title} · ${item.note}` : item.title;
  const colour = item.mark ? item.mark : "bg-violet-100 text-violet-800";
  return (
    <li
      className={`truncate rounded px-1.5 py-0.5 text-xs ${colour}`}
      title={tip}
    >
      {item.href ? (
        <AppLink to={item.href} className="hover:underline">
          {item.title}
        </AppLink>
      ) : (
        item.title
      )}
    </li>
  );
}

// The «+N» of a day: a link to more_href in month mode, plain text in week mode or when there is no link.
function More({ day, linked }: { day: DayOut; linked: boolean }) {
  if (linked && day.more_href !== "") {
    return (
      <p className={MORE_CLASS}>
        <TLink to={day.more_href} className="hover:underline">
          +{day.more}
        </TLink>
      </p>
    );
  }
  return <p className={MORE_CLASS}>+{day.more}</p>;
}

// One arrow: a link with its label, or at a bound a grey span with the label for screen readers only.
function Arrow({
  href,
  label,
  glyph,
}: {
  href: string;
  label: string;
  glyph: string;
}) {
  if (href === "") {
    return (
      <span aria-disabled="true" className={DISABLED_CLASS}>
        <span className="sr-only">{label}</span>
        <span aria-hidden="true">{glyph}</span>
      </span>
    );
  }
  return (
    <TLink to={href} aria-label={label} className={ARROW_CLASS}>
      {glyph}
    </TLink>
  );
}

// A complete «YYYY-MM» inside the month input's limits (1900-01 to 2100-12). Partial or empty text is not a month.
const MONTH_VALUE = /^(\d{4})-(\d{2})$/;

function isNavigableMonth(value: string): boolean {
  const match = MONTH_VALUE.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  return year >= 1900 && year <= 2100 && month >= 1 && month <= 12;
}

export function CalendarLayout({
  calendar,
  query,
  onChange,
}: CalendarLayoutProps) {
  // The month box's text. The DatePicker is controlled, so the typed text lives here; it follows the address when the
  // page moves to another month.
  const [draft, setDraft] = useState(calendar.month_value);
  useEffect(() => {
    setDraft(calendar.month_value);
  }, [calendar.month_value]);

  if (calendar.total === 0) {
    return <p className={EMPTY_CLASS}>Өгөгдөл олдсонгүй</p>;
  }

  const isMonth = calendar.mode === "month";
  const days: DayOut[] = isMonth ? calendar.weeks.flat() : calendar.days;
  // Django's busy_days: in month mode only the days of the shown month (the grey days of the grid have no list entry).
  const busy = days.filter(
    (day) =>
      (!isMonth || day.in_month) && (day.entries.length > 0 || day.more > 0),
  );
  const prevLabel = isMonth ? "Өмнөх сар" : "Өмнөх долоо хоног";
  const nextLabel = isMonth ? "Дараах сар" : "Дараах долоо хоног";
  const emptyText = isMonth ? SUB_EMPTY_TEXT : "Энэ долоо хоногт оруулга алга";

  // The picker reports every typed character, so only a complete, valid month navigates, and only once per value.
  const onPickMonth = (value: string) => {
    setDraft(value);
    if (isNavigableMonth(value) && value !== calendar.month_value) {
      onChange(set(query, "lmonth", value));
    }
  };

  return (
    <>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-slate-900">
          {calendar.heading}
        </h2>
        <div data-calendar-tools className={TOOLS_CLASS}>
          <div className={GROUP_CLASS} role="group" aria-label="Харагдац">
            {isMonth ? (
              <>
                <span aria-current="true" className={CURRENT_CLASS}>
                  Сар
                </span>
                <TLink to={calendar.switch_href} className={LINK_CLASS}>
                  7 хоног
                </TLink>
              </>
            ) : (
              <>
                <TLink to={calendar.switch_href} className={LINK_CLASS}>
                  Сар
                </TLink>
                <span aria-current="true" className={CURRENT_CLASS}>
                  7 хоног
                </span>
              </>
            )}
          </div>
          <div className={GROUP_CLASS}>
            <Arrow href={calendar.prev_href} label={prevLabel} glyph="‹" />
            <Arrow href={calendar.next_href} label={nextLabel} glyph="›" />
            <TLink to={calendar.today_href} className={LINK_CLASS}>
              Өнөөдөр
            </TLink>
          </div>
          {isMonth ? (
            <form
              data-month-form
              // Enter in the month box would submit the page's GET form and reload it; the change already navigates.
              onSubmit={(event) => event.preventDefault()}
              className={GROUP_CLASS}
            >
              <DatePicker
                name="lmonth"
                mode="month"
                min="1900-01"
                max="2100-12"
                ariaLabel="Сар сонгох"
                value={draft}
                onChange={onPickMonth}
                className="max-w-full rounded-lg border border-slate-300 bg-surface px-2 py-1.5 text-sm"
              />
            </form>
          ) : null}
        </div>
      </div>

      <div className="hidden sm:grid grid-cols-7 gap-1 mt-4">
        {WEEKDAYS.map((name) => (
          <div key={name} className={WEEKDAY_CLASS}>
            {name}
          </div>
        ))}
        {days.map((day) => (
          <div
            key={day.iso}
            data-day={day.iso}
            data-today={day.is_today ? "" : undefined}
            className={
              (isMonth ? "min-h-20" : "min-h-32") +
              " rounded-lg border border-slate-200 p-1.5" +
              (isMonth && !day.in_month ? " bg-slate-50" : " bg-surface") +
              (day.is_today ? " ring-2 ring-violet-600" : "")
            }
          >
            <p
              className={
                "text-xs font-medium " +
                (isMonth && !day.in_month ? "text-slate-400" : "text-slate-700")
              }
            >
              {day.number}
            </p>
            <ul className="mt-1 space-y-1">
              {day.entries.map((item, index) => (
                <Entry key={`${day.iso}|${item.title}|${index}`} item={item} />
              ))}
            </ul>
            {day.more > 0 ? <More day={day} linked={isMonth} /> : null}
          </div>
        ))}
      </div>

      <div className="sm:hidden mt-4 space-y-3">
        {busy.map((day) => (
          <section
            key={day.iso}
            data-list-day={day.iso}
            data-today={day.is_today ? "" : undefined}
            className={
              "rounded-xl border border-slate-200 bg-surface p-3" +
              (day.is_today ? " ring-2 ring-violet-600" : "")
            }
          >
            <h3 className="text-sm font-semibold text-slate-900">{day.iso}</h3>
            <ul className="mt-2 space-y-1">
              {day.entries.map((item, index) => (
                <Entry key={`${day.iso}|${item.title}|${index}`} item={item} />
              ))}
            </ul>
            {day.more > 0 ? <p className={MORE_CLASS}>+{day.more}</p> : null}
          </section>
        ))}
        {busy.length === 0 ? <p className={EMPTY_CLASS}>{emptyText}</p> : null}
      </div>

      {calendar.undated > 0 ? (
        <p className="mt-3 text-sm text-slate-500">
          Огноогүй: {calendar.undated}
        </p>
      ) : null}
    </>
  );
}
