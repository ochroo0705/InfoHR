import type { components } from "../../../api/schema";
import { AppLink } from "../../../lib/AppLink";
import { TLink } from "../../../lib/viewTransition";
import { CardExtras } from "./CardItem";

// The board (app/reports/templates/reports/layouts/board.html, UI_RULES §4b): one lane per category, scrolling sideways on
// a phone. Lane counts and figures cover every filtered row; the cards only the first `board.cap` rows (the cap note says
// so). Cards are read-only here: no drag between lanes.

type BoardOut = components["schemas"]["ReportBoardOut"];
type LaneOut = components["schemas"]["ReportLaneOut"];
type CardOut = LaneOut["cards"][number];

const STRETCHED_LINK =
  "text-violet-700 hover:underline after:absolute after:inset-0 after:content-['']";

export interface BoardLayoutProps {
  board: BoardOut;
}

export function BoardLayout({ board }: BoardLayoutProps) {
  if (board.total === 0) {
    return (
      <p className="mt-4 py-6 text-center text-sm text-slate-400">
        Өгөгдөл олдсонгүй
      </p>
    );
  }
  const showFigure = board.value_label !== "";
  return (
    <>
      {showFigure ? (
        <p className="mt-4 text-sm text-slate-500">Утга: {board.value_label}</p>
      ) : null}
      <div className="mt-4 flex items-start gap-3 overflow-x-auto pb-2">
        {board.lanes.map((lane, index) => (
          <Lane key={index} lane={lane} showFigure={showFigure} />
        ))}
      </div>
      {board.shown < board.total ? (
        <p className="mt-3 text-sm text-slate-500">
          Эхний {board.cap}-г харууллаа. Шүүлтүүрээр нарийвчилна уу.
        </p>
      ) : null}
    </>
  );
}

function Lane({ lane, showFigure }: { lane: LaneOut; showFigure: boolean }) {
  const heading = `${lane.label} · ${lane.count}${showFigure ? ` · ${lane.figure}` : ""}`;
  return (
    <section
      aria-label={lane.label}
      className="min-w-[16rem] w-64 shrink-0 rounded-xl border border-slate-200 bg-slate-50 p-2"
    >
      <h2 className="mb-2 px-1 text-sm font-semibold text-slate-900">
        {lane.href ? (
          <TLink
            to={lane.href}
            className="text-violet-700 hover:underline"
            title="Эдгээр мөрийг хүснэгтээр харах"
          >
            {heading}
          </TLink>
        ) : (
          heading
        )}
      </h2>
      <ul className="space-y-2">
        {lane.cards.map((item, index) => (
          <BoardCard key={index} item={item} />
        ))}
        {lane.cards.length === 0 ? (
          <li className="px-1 text-sm text-slate-400">…</li>
        ) : null}
      </ul>
    </section>
  );
}

// A card of a board lane (board.html): a row with a title, subtitle and extra lines, without the photo of the cards layout.
function BoardCard({ item }: { item: CardOut }) {
  const classes = [
    "relative rounded-lg border border-slate-200 bg-surface p-3 text-sm",
    item.href ? "hover:border-violet-300 hover:bg-slate-50" : "",
    item.mark,
  ];
  return (
    <li className={classes.filter(Boolean).join(" ")}>
      <p className="line-clamp-2 font-medium text-slate-900">
        {item.href ? (
          <AppLink to={item.href} className={STRETCHED_LINK}>
            {item.title}
          </AppLink>
        ) : (
          item.title
        )}
      </p>
      {item.subtitle ? (
        <p className="mt-1 line-clamp-2 text-xs text-slate-500">
          {item.subtitle}
        </p>
      ) : null}
      <CardExtras
        extras={item.extras}
        className="mt-1 text-xs text-slate-600"
      />
    </li>
  );
}
