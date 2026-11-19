import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Order register at /employees/orders/ (step 3d-3): Django `orders.html` with its row partials `_order_register_rows.html` and
// `_order_register_items.html`, against OrdersPage.tsx (RegisterFilters.tsx, RegisterTable.tsx). Both sides use the same path.
// signIn is on, so each side first lands on its own home page; the `visit` step then opens the register on that side.
//
// Compared, after each step: the whole register page for each filter (default, sort, search, state, year), the sort head
// click («Дугаар»), and the order detail pop-up opened by a click on a register row that has an order. The register only
// reads data; the pop-up is opened and compared, never saved or submitted.
//
// Async rows: the React register loads its rows over the API, so every step waits for the network to be idle and for the
// first table row to be on screen (`settle`). The harness also waits for the loading markers before each screenshot.
//
// Demo data (seed_demo `_demo_scenarios._other_orders`): Болд's hire orders are Д/101 (registered, dated about 4000 days before
// the seed) and Д/102 (signed, about 4500 days before). When the seed runs in late 2026 they fall in 2015 and 2014, so
// `?year=2015` shows Д/101. If the seed was run on another day the year may differ; the select then shows «Бүх он» on both
// sides, which is still a valid comparison, but the scenario no longer checks a filtered list.
//
// A legacy (MACS) row is never clicked: it navigates to the employee page (`onclick` / `opens=employee`), which the
// employee specs cover. The row click here is only on a row with an order (`opens=detail`), which opens the pop-up.
//
// Known differences: none recorded yet. Record any the first run shows in EXPECTED_DIFFS.md, section «order register».
//
// Masks: the register shows no today's date (its dates are the orders' own dates, which do not change), so nothing is
// masked here. The print page masks its date (orders-print.spec.ts).

const MODAL = ".fixed.inset-0.z-50";

// Each parity test signs in on both sides and opens the register on both: with a pop-up step it needs more than the 30 s default.
test.setTimeout(60_000);
const REGISTER = "/employees/orders/";
// The seeded hire order of Болд with a registered state, and the year of the seeded orders (see the header).
const REGISTERED_ORDER = "Д/101";
const DEMO_YEAR = "2015";
// The search text: the order number prefix that matches the seeded orders. URL-encoded in the address.
const SEARCH_TEXT = "Д/";
// The number column head. Both sides draw it as a link inside `thead th`.
const NUMBER_HEAD = "Дугаар";

// Opens the register on this side (the harness signed in and landed on the home page) and waits until the table has rows.
// The empty-state row («Тушаал олдсонгүй») is a row too, so the wait holds for an empty result as well.
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("tbody tr").first()).toBeVisible();
}

function visit(path: string): Step {
  return async (page) => {
    await openPath(page, path);
    await settle(page);
  };
}

// Step: a click on the number head. Both sides sort by number, and the table is redrawn (htmx on Django, the API on React).
const clickNumberHead: Step = async (page) => {
  await page.locator("thead th a", { hasText: NUMBER_HEAD }).first().click();
  await settle(page);
};

// Step: a click on a register row that carries the order named by `orderNumber`. The row's own cell opens the pop-up
// (Django's `hx-get` on the `<tr>`; React's `opens=detail`). Skipped with a reason when the row is not on screen.
function openRegisterRow(orderNumber: string): Step {
  return async (page) => {
    const row = page.locator("tbody tr", { hasText: orderNumber }).first();
    if ((await row.count()) === 0) {
      test.skip(true, `The register has no row with «${orderNumber}» (the demo data is not seeded, or the filter hides it).`);
      return;
    }
    await row.click();
    await expect(page.locator(MODAL)).toBeVisible();
    await expect(page.locator(`${MODAL} h3`).first()).toBeVisible();
  };
}

// The address of a register filter. Built with encodeURIComponent so the Cyrillic text and the slash are sent as the
// browser would send them from the search box.
const searchPath = `${REGISTER}?q=${encodeURIComponent(SEARCH_TEXT)}`;

// Default register: the newest first, no filter.
parity("order register: default", REGISTER, REGISTER, [visit(REGISTER)], {
  signIn: true,
});

// The number sort, in the address (the same as clicking the head, but as a fresh load).
parity("order register: sorted by number", REGISTER, REGISTER, [visit(`${REGISTER}?sort=number`)], {
  signIn: true,
});

// The search text «Д/» matches the seeded order numbers.
parity("order register: search", REGISTER, REGISTER, [visit(searchPath)], {
  signIn: true,
});

// Filter by state: signed orders only, then registered orders only (the state chip and the row set both differ).
parity("order register: state signed", REGISTER, REGISTER, [visit(`${REGISTER}?state=signed`)], {
  signIn: true,
});

parity("order register: state registered", REGISTER, REGISTER, [visit(`${REGISTER}?state=registered`)], {
  signIn: true,
});

// The year filter. The option is the year of the seeded orders (see the header about the year).
parity("order register: year", REGISTER, REGISTER, [visit(`${REGISTER}?year=${DEMO_YEAR}`)], {
  signIn: true,
});

// Sorting by a click on the head, on the register as opened (not from the address): both sides change the sort in place
// and push the new address to history.
parity("order register: click the number head", REGISTER, REGISTER, [visit(REGISTER), clickNumberHead], {
  signIn: true,
});

// The order detail pop-up from a row. The whole page is compared with the pop-up open (a `clip` on the overlay hangs the
// harness's element screenshot on this page, so none is used). The step opens the row only; nothing in the pop-up is submitted.
// The seeded orders are old, so they sit at the end of the newest-first list, beyond the first batch of 60: the visit
// searches for the order number, which brings its row into the first batch on both sides.
// The search text is «101», not «Д/101»: the slash would be double-encoded by the login redirect (`?next=`) both sides do first.
const popupPath = `${REGISTER}?q=101`;
parity("order register: detail pop-up from a row", popupPath, popupPath, [visit(popupPath), openRegisterRow(REGISTERED_ORDER)], {
  signIn: true,
});
