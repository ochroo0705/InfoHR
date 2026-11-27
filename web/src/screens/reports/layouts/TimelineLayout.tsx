import type { components } from "../../../api/schema";
import { AppLink } from "../../../lib/AppLink";
import { TLink } from "../../../lib/viewTransition";
import { useBarTip } from "./useBarTip";

// The timeline (app/reports/templates/reports/layouts/timeline.html and _bar.html, UI_RULES §4b): one row per bar, the
// title on the left and the track on the right. The track scrolls sideways on a phone. Every position and percentage is
// the API's number, used verbatim. A group head is drawn only for a named group (the ungrouped list is one group with
// the label ""). Classes, Mongolian text and structure are copied from the templates. A bar takes keyboard focus so its
// tooltip (useBarTip) can be reached without a pointer.

type TimelineOut = components["schemas"]["ReportTimelineOut"];
type TimelineBarOut = components["schemas"]["ReportTimelineBarOut"];

export interface TimelineLayoutProps {
  timeline: TimelineOut;
}

const EMPTY_CLASS = "mt-4 py-6 text-center text-sm text-slate-400";
const NOTE_CLASS = "mt-1 text-sm text-slate-500";
const LINK_CLASS =
  "rounded-lg border border-slate-300 bg-surface px-3 py-1.5 text-slate-700 hover:bg-slate-50";
const ARROW_CLASS =
  "rounded-lg border border-slate-300 bg-surface px-3 py-1.5 text-slate-700 hover:bg-slate-50";
const DISABLED_CLASS =
  "rounded-lg border border-slate-200 px-3 py-1.5 text-slate-300";
const TODAY_LABEL = "Өнөөдөр";

// One year arrow: a link with its label, or at a bound (null from the API) a grey span with the label for screen
// readers only and aria-disabled.
function YearArrow({
  href,
  label,
  glyph,
}: {
  href: string | null;
  label: string;
  glyph: string;
}) {
  if (href === null) {
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

// The bar's title: a link when the row has an href, else plain text.
function BarTitle({ bar }: { bar: TimelineBarOut }) {
  if (bar.href === "") {
    return <>{bar.title}</>;
  }
  return (
    <AppLink to={bar.href} className="text-violet-700 hover:underline">
      {bar.title}
    </AppLink>
  );
}

export function TimelineLayout({ timeline }: TimelineLayoutProps) {
  const { bind, tip } = useBarTip();

  if (timeline.total === 0) {
    return <p className={EMPTY_CLASS}>Өгөгдөл олдсонгүй</p>;
  }

  const barCount = timeline.groups.reduce(
    (sum, group) => sum + group.bars.length,
    0,
  );
  const todayLeft =
    timeline.today_pct === null ? null : `${timeline.today_pct}%`;

  return (
    <>
      <div
        data-timeline-tools
        className="mt-4 flex flex-wrap items-center justify-end gap-2 text-sm"
      >
        {timeline.year !== null ? (
          <>
            <div className="flex shrink-0 items-center gap-1 text-sm">
              <YearArrow
                href={timeline.year_prev_href}
                label="Өмнөх жил"
                glyph="‹"
              />
              <span className="px-2 font-semibold text-slate-700">
                {timeline.year}
              </span>
              <YearArrow
                href={timeline.year_next_href}
                label="Дараах жил"
                glyph="›"
              />
            </div>
            <TLink to={timeline.all_href} className={LINK_CLASS}>
              Бүгд
            </TLink>
          </>
        ) : (
          <TLink
            to={timeline.enter_href}
            title="Нэг жилээр харах"
            className={LINK_CLASS}
          >
            Он
          </TLink>
        )}
      </div>

      <div className="mt-4 overflow-x-auto pb-2">
        <div className="space-y-2">
          {timeline.groups.map((group, groupIndex) => (
            <div key={`group-${groupIndex}`} className="space-y-2">
              {group.label !== "" ? (
                <div className="mt-2 flex items-center gap-3 text-sm font-semibold text-slate-900">
                  <div className="w-48 shrink-0 truncate">{`${group.label} · ${group.count}`}</div>
                </div>
              ) : null}
              {group.bars.map((bar, barIndex) => {
                const handlers = bind({ title: bar.tip_title, tip: bar.tip });
                const colour = bar.mark
                  ? `${bar.mark} ring-1 ring-inset`
                  : "bg-violet-500";
                return (
                  <div
                    key={`bar-${groupIndex}-${barIndex}`}
                    className="flex items-center gap-3 text-sm"
                  >
                    <div className="w-48 shrink-0 truncate">
                      <BarTitle bar={bar} />
                    </div>
                    <div className="relative h-7 min-w-[40rem] flex-1 rounded bg-slate-100">
                      {todayLeft !== null ? (
                        <div
                          aria-hidden="true"
                          data-today
                          className="absolute inset-y-0 w-px bg-violet-500"
                          style={{ left: todayLeft }}
                          title={TODAY_LABEL}
                        />
                      ) : null}
                      <div
                        data-bar
                        role="img"
                        tabIndex={0}
                        aria-label={bar.label}
                        className={`absolute inset-y-1 rounded ${colour}`}
                        style={{
                          left: `${bar.left_pct}%`,
                          width: `${bar.width_pct}%`,
                        }}
                        {...handlers}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          ))}

          {timeline.first !== "" ? (
            <>
              <div className="flex items-center gap-3 text-xs text-slate-500">
                <div className="w-48 shrink-0" />
                <div className="relative h-5 min-w-[40rem] flex-1 border-t border-slate-300">
                  {timeline.ticks.map((tick, tickIndex) => (
                    <span key={`tick-${tickIndex}`}>
                      <span
                        aria-hidden="true"
                        className="absolute -top-1 h-2 border-l border-slate-400"
                        style={{ left: `${tick.left_pct}%` }}
                      />
                      <span
                        className="absolute text-xs text-slate-500"
                        style={{ left: `${tick.left_pct}%` }}
                      >
                        {tick.label}
                      </span>
                    </span>
                  ))}
                  {todayLeft !== null ? (
                    <div
                      aria-hidden="true"
                      data-today
                      className="absolute inset-y-0 w-px bg-violet-500"
                      style={{ left: todayLeft }}
                      title={TODAY_LABEL}
                    />
                  ) : null}
                </div>
              </div>
              <div className="flex items-center gap-3 text-xs text-slate-500">
                <div className="w-48 shrink-0" />
                <div className="flex min-w-[40rem] flex-1 justify-between border-t border-slate-300 pt-1">
                  <span>{timeline.first}</span>
                  <span>{timeline.last}</span>
                </div>
              </div>
            </>
          ) : null}
        </div>
      </div>

      {barCount === 0 && timeline.off_axis === 0 ? (
        <p className={EMPTY_CLASS}>Өгөгдөл олдсонгүй</p>
      ) : null}
      {timeline.undated > 0 ? (
        <p className="mt-3 text-sm text-slate-500">
          Огноогүй: {timeline.undated}
        </p>
      ) : null}
      {timeline.off_axis > 0 ? (
        <p className={NOTE_CLASS}>Хүрээнээс гадуур: {timeline.off_axis}</p>
      ) : null}
      {timeline.clipped ? (
        <p className={NOTE_CLASS}>
          Хугацааны хүрээ {timeline.years} жилээр хязгаарлагдсан.
        </p>
      ) : null}
      {timeline.over_cap > 0 ? (
        <p className={NOTE_CLASS}>
          Эхний {timeline.cap}-г харууллаа. Шүүлтүүрээр нарийвчилна уу.
        </p>
      ) : null}
      {tip}
    </>
  );
}
