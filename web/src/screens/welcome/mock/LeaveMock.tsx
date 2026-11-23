import { DeviceFrame } from "./DeviceFrame";
import "./mock.css";
import { leaveBars, leaveMockLabels } from "./sampleData";

// A static copy of the leave calendar (app/leave/templates/leave/calendar.html) with invented people. It has no
// request and no app components. Each bar sits on a 21-day track:
//   left  = startDay / 21 * 100   (percent of the track from its left edge)
//   width = days / 21 * 100        (percent of the track each leave day takes)
// Weekend days (day index 5, 6, 12, 13, 19, 20 of a Monday-first window) are shaded as background cells.
const DAY_COUNT = 21;
const dayIndexes = Array.from({ length: DAY_COUNT }, (_, index) => index);

function isWeekend(index: number): boolean {
  return index % 7 === 5 || index % 7 === 6;
}

export function LeaveMock() {
  return (
    <DeviceFrame label={leaveMockLabels.frame}>
      <div className="mock-leave">
        <div className="mock-leave-title">{leaveMockLabels.title}</div>

        <div className="mock-leave-row mock-leave-row--head" aria-hidden="true">
          <span className="mock-leave-name" />
          <div className="mock-leave-days">
            {dayIndexes.map((index) => (
              <span
                key={index}
                className={isWeekend(index) ? "mock-leave-day mock-leave-day--weekend" : "mock-leave-day"}
              >
                {leaveMockLabels.weekdays[index % 7]}
              </span>
            ))}
          </div>
        </div>

        {leaveBars.map((bar) => (
          <div key={bar.person} className="mock-leave-row">
            <span className="mock-leave-name">{bar.person}</span>
            <div className="mock-leave-track">
              <div className="mock-leave-cells" aria-hidden="true">
                {dayIndexes.map((index) => (
                  <span
                    key={index}
                    className={isWeekend(index) ? "mock-leave-cell mock-leave-cell--weekend" : "mock-leave-cell"}
                  />
                ))}
              </div>
              <span
                data-anim="leave-bar"
                className={`mock-leave-bar mock-leave-bar--${bar.kind}`}
                style={{
                  left: `${(bar.startDay / DAY_COUNT) * 100}%`,
                  width: `${(bar.days / DAY_COUNT) * 100}%`,
                }}
              />
            </div>
          </div>
        ))}

        <div className="mock-leave-legend" aria-hidden="true">
          <span className="mock-leave-key">
            <span className="mock-leave-swatch mock-leave-swatch--annual" />
            {leaveMockLabels.kinds.annual}
          </span>
          <span className="mock-leave-key">
            <span className="mock-leave-swatch mock-leave-swatch--other" />
            {leaveMockLabels.kinds.other}
          </span>
        </div>
      </div>
    </DeviceFrame>
  );
}
