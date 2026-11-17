// The theme choice: Цайвар (light) and Бараан (dark) are saved in this browser under localStorage "theme"; Автомат
// (auto) saves nothing and follows the computer's setting, live. Port of the switch in app/static/js/nav.js and of the
// pre-paint script at the top of base.html and web/index.html. Those must agree with this file: anything in storage
// other than "light" or "dark" means auto. Every storage call is wrapped, because a blocked storage must not break
// the page.

export type Choice = "light" | "dark" | "auto";

const KEY = "theme";
const SYSTEM_DARK = "(prefers-color-scheme: dark)";

function systemDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(SYSTEM_DARK).matches;
}

export function getChoice(): Choice {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // Storage blocked: the choice reads as auto, as with nothing saved.
  }
  return "auto";
}

function paint(choice: Choice): void {
  document.documentElement.dataset.theme = choice === "auto" ? (systemDark() ? "dark" : "light") : choice;
}

// Sets <html data-theme> from the saved choice.
export function apply(): void {
  paint(getChoice());
}

export function setChoice(choice: Choice): void {
  try {
    if (choice === "auto") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, choice);
  } catch {
    // Storage blocked: the choice lasts until the page changes.
  }
  paint(choice);
}

// Re-applies the theme when the computer's setting changes, but only while the choice is auto. Returns the stop
// function.
export function watchSystem(): () => void {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(SYSTEM_DARK);
  const onChange = () => {
    if (getChoice() === "auto") apply();
  };
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
