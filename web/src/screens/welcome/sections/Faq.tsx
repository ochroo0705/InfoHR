import { copy } from "../copy";
import "./faq.css";

// FAQ: native <details> items, so it works with the keyboard and without script. Light tone, no motion.
export function Faq() {
  return (
    <section id="faq" data-tone="light" className="w-faq" aria-labelledby="faq-title">
      <div className="w-container">
        <h2 className="w-faq-title" id="faq-title">
          {copy.faq.title}
        </h2>
        <div className="w-faq-list">
          {copy.faq.items.map((item) => (
            <details key={item.q} className="w-faq-item">
              <summary className="w-faq-q">{item.q}</summary>
              <p className="w-faq-a">{item.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
