import { DeviceFrame } from "./DeviceFrame";
import "./mock.css";
import { attentionCards, awayToday, todayMockLabels } from "./sampleData";

// A static copy of the Today page's attention cards (web/src/screens/today/AttentionBox) with invented counts.
// The cards use the caution colours of the Анхаарах box: a warn-brass left edge on a caution tint, count in caution ink.
// The "away today" strip lists people on leave in the leave-sky chip style. No request, no app components.
export function TodayMock() {
  return (
    <DeviceFrame label={todayMockLabels.frame}>
      <div className="mock-today">
        <div className="mock-today-title">{todayMockLabels.title}</div>

        <div className="mock-today-cards">
          {attentionCards.map((card) => (
            <div key={card.title} data-anim="today-card" className="mock-today-card">
              <span className="mock-today-count">{card.count}</span>
              <span className="mock-today-label">{card.title}</span>
            </div>
          ))}
        </div>

        <div className="mock-today-away">
          <span className="mock-today-away-label">{todayMockLabels.awayTitle}</span>
          <div className="mock-today-chips">
            {awayToday.map((name) => (
              <span key={name} className="mock-today-chip">
                {name}
              </span>
            ))}
          </div>
        </div>
      </div>
    </DeviceFrame>
  );
}
