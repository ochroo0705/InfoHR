import { copy } from "./copy";

// Light tone. The phone link strips the spaces so it dials correctly on a phone.
export function Footer() {
  return (
    <footer className="w-footer" data-tone="light">
      <div className="w-container w-footer-inner">
        <p className="w-footer-company">{copy.footer.company}</p>
        <ul className="w-footer-contacts">
          <li>
            <a className="w-footer-link" href={`tel:${copy.footer.phone.replace(/\s/g, "")}`}>
              {copy.footer.phone}
            </a>
          </li>
          <li>
            <a className="w-footer-link" href={`mailto:${copy.footer.email}`}>
              {copy.footer.email}
            </a>
          </li>
          <li className="w-footer-hours">{copy.footer.hours}</li>
        </ul>
      </div>
    </footer>
  );
}
