import { useHires, useUpcoming, type TodayOut, type UpcomingListOut } from "../../api/today";
import { AppLink } from "../../lib/AppLink";
import { CountLine } from "./CountLine";
import { NAME_LINK_CLASS, NameRows, type NameRow } from "./NameRows";

type Upcoming = TodayOut["upcoming"];

function upcomingRows(items: UpcomingListOut["items"]): NameRow[] {
  return items.map((u) => ({
    id: u.id,
    left: (
      <>
        {u.kind === "birthday" ? "Төрсөн өдөр" : `${u.years} жилийн ой`} ·{" "}
        <AppLink to={`/employees/${u.id}/`} className={NAME_LINK_CLASS}>
          {u.full_name}
        </AppLink>
      </>
    ),
    right: u.on,
  }));
}

// The «Ойрын 30 хоног» panel of the Today page (`_today_strip.html`, the upcoming part).
// It spans both columns when the away strip is hidden.
export function Upcoming30({ upcoming, showLeave }: { upcoming: Upcoming; showLeave: boolean }) {
  const holidays = upcoming.holidays;
  const extra = holidays.length - 3;

  return (
    <section
      className={`card-soft p-4${showLeave ? "" : " lg:col-span-2"}`}
      data-upcoming=""
      aria-labelledby="upcoming-title"
    >
      <h2 id="upcoming-title" className="sec-title mb-2">
        Ойрын 30 хоног
      </h2>
      <div className="divide-y divide-slate-100 text-sm">
        {holidays.length > 0 ? (
          <div data-holidays="" className="py-1.5 text-slate-700">
            Баяр ёслол: {holidays.slice(0, 3).map((h) => `${h.day} ${h.name}`).join(" · ")}
            {extra > 0 ? ` +${extra}` : ""}
          </div>
        ) : null}
        {typeof upcoming.open_vacancies === "number" ? (
          <div data-vacancies="">
            <AppLink
              to="/recruitment/"
              className="flex w-full items-center rounded py-1.5 text-violet-700 hover:bg-slate-50"
            >
              {`Нээлттэй ажлын байр ${upcoming.open_vacancies} →`}
            </AppLink>
          </div>
        ) : null}
        {upcoming.checklist ? (
          <div data-checklist-summary="" className="py-1.5 text-slate-700">
            Бүрдүүлэлт: {upcoming.checklist.open} нээлттэй ·{" "}
            <span className={upcoming.checklist.overdue > 0 ? "text-red-700" : undefined}>
              {upcoming.checklist.overdue} хоцорсон
            </span>
          </div>
        ) : null}
        {upcoming.show_birthdays ? (
          <CountLine
            label="Төрсөн өдөр"
            count={upcoming.birthdays}
            id="upcoming-birthday"
            query={(open) => useUpcoming("birthday", open)}
          >
            {(list) => (
              <NameRows rows={upcomingRows(list.items)} empty="Ойрын 30 хоногт төрсөн өдөр алга." />
            )}
          </CountLine>
        ) : null}
        <CountLine
          label="Ажилласан жилийн ой"
          count={upcoming.anniversaries}
          id="upcoming-anniversary"
          query={(open) => useUpcoming("anniversary", open)}
        >
          {(list) => (
            <NameRows rows={upcomingRows(list.items)} empty="Ойрын 30 хоногт ажилд орсны ой алга." />
          )}
        </CountLine>
        <CountLine
          label="Сүүлийн 30 хоногт шинээр орсон"
          count={upcoming.new_hires}
          id="upcoming-hires"
          query={(open) => useHires(open)}
        >
          {(hires) => (
            <NameRows
              rows={hires.map((r) => ({
                id: r.id,
                left: (
                  <AppLink to={`/employees/${r.id}/`} className={NAME_LINK_CLASS}>
                    {r.full_name}
                  </AppLink>
                ),
                right: r.hired,
              }))}
              empty="Сүүлийн 30 хоногт шинээр орсон ажилтан алга."
              emptyClass="text-sm text-slate-500"
            />
          )}
        </CountLine>
      </div>
    </section>
  );
}
