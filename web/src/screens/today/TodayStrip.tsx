import type { TodayOut } from "../../api/today";
import { AwayStrip } from "./AwayStrip";
import { Upcoming30 } from "./Upcoming30";

// The two-column row under the tiles: the away strip and «Ойрын 30 хоног» (`_today_strip.html`).
export function TodayStrip({ data }: { data: TodayOut }) {
  return (
    <div className="mb-5 grid gap-5 lg:grid-cols-[3fr_2fr]">
      <AwayStrip strip={data.strip} />
      <Upcoming30 upcoming={data.upcoming} showLeave={data.strip.show_leave} />
    </div>
  );
}
