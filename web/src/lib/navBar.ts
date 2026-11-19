// The top loading bar on a page switch. A route change shows the new screen first and its data request starts a moment
// later, so the data-driven bar (LoadingBar: body[data-loading]) would begin after the page has already changed. This
// starts it at the click, as body[data-nav]; it ends when the screen's requests finish (LoadingBar) or after a short
// time when there are none (cached data). motion.css draws the bar from either attribute.
const SAFETY_MS = 800;
let timer = 0;

export function startNavBar(): void {
  document.body.dataset.nav = "";
  window.clearTimeout(timer);
  timer = window.setTimeout(endNavBar, SAFETY_MS);
}

export function endNavBar(): void {
  window.clearTimeout(timer);
  delete document.body.dataset.nav;
}
