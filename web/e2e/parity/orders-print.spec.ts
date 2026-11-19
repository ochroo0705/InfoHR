import type { Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Order register print page at /employees/orders/print/ (step 3d-3): Django `orders_print.html` against OrdersPrintPage.tsx
// (its CSS is ordersPrint.css, every rule under `.orders-print`). Both sides use the same path. signIn is on, so each side
// first lands on its own home page; the `visit` step then opens the print page on that side.
//
// Both pages are standalone: no app shell, no header, the page itself is the screen (the React route lives outside AppShell,
// as the Django page is outside base.html's content). The print page reads the same filters as the register, from the address.
//
// Compared: the screen render (1280 and 375, light and dark, from the harness defaults), the same render with `?state=signed`,
// and the print media render (`emulateMedia({ media: "print" })` on both sides, as a step, so the screenshots are taken under
// print rules: the `.noprint` button hides, the table borders and the page margin apply).
//
// Async rows: the React print page loads its rows in one query, so `visit` waits for the network to be idle and for the first
// table row to be on screen.
//
// Masks: the header line of the page shows today's date (`.top > div:last-child`, on both sides), so it is masked in every
// scenario. The date is the only volatile text on the page.
//
// Known differences: none recorded yet. Record any the first run shows in EXPECTED_DIFFS.md, section «order print».

const PRINT = "/employees/orders/print/";
// Today's date, the second item of the header line (`.top`). It changes between runs, so it is painted over on both sides.
const DATE_MASK = [".top > div:last-child"];

// Opens the print page on this side and waits until the table has rows (an empty result still has a row: «Тушаал олдсонгүй»).
function visit(path: string): Step {
  return async (page: Page) => {
    await openPath(page, path);
    await page.waitForLoadState("networkidle");
    await page.locator("table tbody tr").first().waitFor();
  };
}

// Step: switch the page to print media. Playwright keeps the emulation for the rest of the test on this page, so the
// screenshots taken after this step show the print layout.
const printMedia: Step = (page) => page.emulateMedia({ media: "print" });

// Screen render of the print page, unfiltered.
parity("order print page: screen", PRINT, PRINT, [visit(PRINT)], {
  signIn: true,
  mask: DATE_MASK,
});

// The same page with a filter in the address: only signed orders.
parity("order print page: screen, state signed", PRINT, PRINT, [visit(`${PRINT}?state=signed`)], {
  signIn: true,
  mask: DATE_MASK,
});

// The print media render: first the screen (step 1), then the same page under print rules (step 2). The step compares
// both, so a change in the print styles shows up on its own step.
parity("order print page: print media", PRINT, PRINT, [visit(PRINT), printMedia], {
  signIn: true,
  mask: DATE_MASK,
});
