import { copy } from "./copy";

// Slim bar on the dark tone. The brand is text, not a link, so it does not send the visitor to the app root.
export function TopBar() {
  return (
    <header className="w-topbar" data-tone="dark">
      <div className="w-container w-topbar-inner">
        <span className="w-brand">{copy.brand}</span>
        <nav className="w-topbar-nav" aria-label={copy.nav.label}>
          <a className="w-link" href="/login">
            {copy.login}
          </a>
          <a className="w-button" href="#demo">
            {copy.demoCta}
          </a>
        </nav>
      </div>
    </header>
  );
}
