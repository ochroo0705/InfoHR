import { DeviceFrame } from "./DeviceFrame";
import "./mock.css";
import { assistantMockLabels, assistantQa } from "./sampleData";

// A static copy of the AI assistant's chat (app/assistant): the user's question in a bubble, then the answer panel
// with its table. The question is always present in full; a later timeline may reveal it with clip-path, never by
// removing text. No request, no app components.
export function AssistantMock() {
  return (
    <DeviceFrame label={assistantMockLabels.frame}>
      <div className="mock-assistant">
        <div className="mock-assistant-turn mock-assistant-turn--user">
          <span className="mock-assistant-who">{assistantMockLabels.you}</span>
          <p data-anim="assistant-question" className="mock-assistant-bubble">
            {assistantQa.question}
          </p>
        </div>

        <div className="mock-assistant-turn">
          <span className="mock-assistant-who">{assistantMockLabels.name}</span>
          <div className="mock-assistant-answer">
            <p className="mock-assistant-caption">{assistantMockLabels.answer}</p>
            <table data-anim="assistant-table" className="mock-assistant-table">
              <thead>
                <tr>
                  {assistantQa.columns.map((column) => (
                    <th key={column} scope="col">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {assistantQa.rows.map((row, rowIndex) => (
                  <tr key={rowIndex} data-anim="assistant-row">
                    {row.map((cell, cellIndex) => (
                      <td key={cellIndex}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </DeviceFrame>
  );
}
