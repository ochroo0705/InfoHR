import { copy } from "../copy";
import "./fit.css";

// "Who it is for" and "how it fits with MACS": static copy, no script and no motion. Dark tone.
export function Fit() {
  return (
    <section id="fit" data-tone="dark" className="w-fit-section">
      <div className="w-container">
        <h2 className="w-fit-title">{copy.fit.title}</h2>
        <ul className="w-fit-sizes">
          {copy.fit.sizes.map((item) => (
            <li key={item.title} className="w-fit-size">
              <h3 className="w-fit-size-title">{item.title}</h3>
              <p className="w-fit-text">{item.text}</p>
            </li>
          ))}
        </ul>
        <div className="w-fit-macs">
          <h3 className="w-fit-macs-title">{copy.fit.macsTitle}</h3>
          <div className="w-fit-macs-body">
            {copy.fit.macsParagraphs.map((paragraph) => (
              <p key={paragraph} className="w-fit-text">
                {paragraph}
              </p>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
