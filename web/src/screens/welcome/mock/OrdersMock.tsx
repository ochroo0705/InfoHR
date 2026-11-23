import { DeviceFrame } from "./DeviceFrame";
import "./mock.css";
import { orderRows, ordersMockLabels, selectedOrderIndex } from "./sampleData";

// A static copy of the Orders register (web/src/screens/orders) with invented rows. It does not import the app's
// components and makes no request. Colours are the app's own: navy, seal red, header and selected-row greys.
export function OrdersMock() {
  const selected = orderRows[selectedOrderIndex];

  return (
    <DeviceFrame label={ordersMockLabels.frame}>
      <div className="mock-orders">
        <div className="mock-orders-register">
          <div className="mock-orders-head">
            <span className="mock-orders-title">{ordersMockLabels.title}</span>
            <span className="mock-orders-new">{ordersMockLabels.newButton}</span>
          </div>
          <div className="mock-orders-row mock-orders-row--header">
            <span>{ordersMockLabels.head.no}</span>
            <span>{ordersMockLabels.head.person}</span>
            <span>{ordersMockLabels.head.type}</span>
          </div>
          {orderRows.map((row) => (
            <div
              key={row.no}
              data-anim="order-row"
              className={row.no === selected.no ? "mock-orders-row mock-orders-row--selected" : "mock-orders-row"}
            >
              <span>{row.no}</span>
              <span>{row.person}</span>
              <span>{row.type}</span>
            </div>
          ))}
        </div>

        <aside className="mock-orders-preview" data-anim="order-preview" aria-hidden="true">
          <div className="mock-orders-preview-head">
            <span>{ordersMockLabels.previewTitle}</span>
          </div>
          <div className="mock-orders-sheet">
            <span className="mock-orders-sheet-title">
              {ordersMockLabels.previewOrderPrefix} {selected.no}
            </span>
            <span className="mock-orders-line" />
            <span className="mock-orders-line mock-orders-line--short" />
            <span className="mock-orders-line" />
            <span className="mock-orders-seal" />
          </div>
        </aside>
      </div>
    </DeviceFrame>
  );
}
