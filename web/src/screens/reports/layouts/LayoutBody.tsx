import type { ReportLayoutPageOut } from "../../../api/reports";
import { BoardLayout } from "./BoardLayout";
import { CalendarLayout } from "./CalendarLayout";
import { CardsLayout } from "./CardsLayout";
import { ChartLayout } from "./ChartLayout";
import { PivotLayout } from "./PivotLayout";
import { TimelineLayout } from "./TimelineLayout";

// The layout body under the filter bar: a switch on the page's kind (the closed set below), each kind mounting its own
// payload. A kind the page does not know, or a page whose payload is missing, is not drawn here: ReportPage shows the link
// to the Django page instead, so a layout added on the server later never blanks the page.

// True when the page can be drawn here: its kind is one of the six and its payload is present.
export function hasLayoutBody(page: ReportLayoutPageOut): boolean {
  switch (page.kind) {
    case "cards":
      return Boolean(page.cards);
    case "board":
      return Boolean(page.board);
    case "calendar":
      return Boolean(page.calendar);
    case "timeline":
      return Boolean(page.timeline);
    case "chart":
      return Boolean(page.chart);
    case "pivot":
      return Boolean(page.pivot);
    default:
      return false;
  }
}

export interface LayoutBodyProps {
  reportKey: string;
  page: ReportLayoutPageOut;
  query: string; // the address query, as the page holds it (the cards and the calendar read it)
  dataUpdatedAt: number; // the seed of the cards' batches, as the table's rows use it
  onChange: (nextQuery: string) => void; // the calendar's month picker navigates through it
}

export function LayoutBody({ reportKey, page, query, dataUpdatedAt, onChange }: LayoutBodyProps) {
  switch (page.kind) {
    case "cards":
      return page.cards ? (
        <CardsLayout
          reportKey={reportKey}
          query={query}
          first={page.cards}
          total={page.count}
          dataUpdatedAt={dataUpdatedAt}
        />
      ) : null;
    case "board":
      return page.board ? <BoardLayout board={page.board} /> : null;
    case "calendar":
      return page.calendar ? <CalendarLayout calendar={page.calendar} query={query} onChange={onChange} /> : null;
    case "timeline":
      return page.timeline ? <TimelineLayout timeline={page.timeline} /> : null;
    case "chart":
      return page.chart ? <ChartLayout chart={page.chart} /> : null;
    case "pivot":
      return page.pivot ? <PivotLayout pivot={page.pivot} /> : null;
    default:
      return null;
  }
}
