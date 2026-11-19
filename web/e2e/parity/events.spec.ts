import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { DJANGO_URL, openPath, parity, type Step } from "./harness";

// Event and order pop-ups (step 3d-1). Each scenario opens one pop-up on the Django employee page and on the React page for
// the same demo employee, and compares the two (screenshot of the pop-up, after each step). Nothing is saved: the steps
// open a form, change its kind (which only reloads the form), or close it with «Болих». No step presses «Хадгалах», sends
// a file, or submits an order.
//
// Overlay: `.fixed.inset-0.z-50` (Django `_modal.html`, `_event_form.html`, `_order_history.html`; React widgets/Modal), the
// same selector employee-edit.spec.ts uses. The pop-up scenarios run at 1280 px only (light and dark): the 375 px runs fail
// suite-wide for a reason unrelated to these pop-ups (a header height gap). The Django assistant button (`[data-assistant-fab]`,
// z-40) sits under the overlay on Django only, so it is hidden on both sides, as employee.spec.ts does.
//
// Employees, found at run time (the pks are not hard-coded; beforeAll reads the staff-list report and each employee's Django
// page, as employee.spec.ts and employee-edit.spec.ts do):
// - «Болд» (seed_demo, login `bold`): the event menu «Өөрчлөлт бүртгэх ▾» (transfer, leave start). The menu is built for an
//   active employee (events.AVAILABLE), and Болд has no open change, so the menu is the one a normal HR user sees.
// - The event cancel needs a change that still waits for its signed order, with «Цуцлах» in «Гарын үсэг хүлээж буй өөрчлөлт».
//   _demo_scenarios.py records «Ганзориг»'s promotion for 10 days ahead with its order registered and no scan, so it waits.
//   beforeAll checks Ганзориг first; if his page has no such button, it scans the other employees.
// - The order pop-ups (edit, history, upload) open from a row of «Бусад тушаал» (WorkOrders.tsx, `_orders.html`). That table only
//   lists orders that no change row claims and that do not wait for a change (detail_page.py: order_rows, change_rows and
//   `_awaiting`). I could not confirm from the seed code that the demo data has such a row, so beforeAll scans the employees for
//   one: an editable row (`cursor-pointer`: pending or registered), a row with «Файл хавсаргах» (registered only), and any row
//   with a «Түүх» item. A scenario whose row the scan did not find is skipped with a reason.
//
// Known differences (EXPECTED_DIFFS.md, «events and orders»): the React event form does not draw the order block's heading
// «Тушаал · …» (`_order_fields.html` has it), so every change form with an order block differs by that heading's height. The
// two transfer scenarios show it. They are expected to fail until the heading is ported; they are not accepted.

const MODAL = ".fixed.inset-0.z-50";
const STAFF_LIST = "/reports/staff-list/";
// Signed-in home for both sides; each scenario opens its employee page itself.
const LANDING = "/employees/today/";
const ASSISTANT_FAB_HIDDEN = "[data-assistant-fab]{visibility:hidden !important}";
const DESKTOP = [{ width: 1280, height: 800 }];

// The event menu of the header (Header.tsx / _header.html) and its two items used here. The labels are the EventType
// labels and events.PLACEMENT_LABEL, the same text on both sides.
const EVENT_MENU = "Өөрчлөлт бүртгэх ▾";
const TRANSFER_ITEM = "Албан тушаал, байршил өөрчлөх";
const LEAVE_START_ITEM = "Урт чөлөө эхлэх";
// The kind select of the placement pop-up: the option «Дэвшүүлэх» is EventType.PROMOTION.
const PROMOTION_KIND = "Дэвшүүлэх";

const WAITING_HEADING = "Гарын үсэг хүлээж буй өөрчлөлт</h3>";
const CANCEL = "Цуцлах";

type OrderRow = { pk: number; orderId: number };
type Found = {
  bold: number;
  // An employee whose waiting table has a «Цуцлах» button, and that row's label (the promotion's «Дэвшүүлэх» for Ганзориг).
  waiting: { pk: number; label: string } | null;
  // A «Бусад тушаал» row that can be edited (pending or registered).
  edit: OrderRow | null;
  // A «Бусад тушаал» row with «Файл хавсаргах» (registered).
  upload: OrderRow | null;
  // Any «Бусад тушаал» row (it always has the «Түүх» item).
  history: OrderRow | null;
};

let found: Found = { bold: 0, waiting: null, edit: null, upload: null, history: null };

test.beforeAll(async () => {
  test.setTimeout(300_000); // the scan fetches an employee page per staff-list row
  const session = await signedInDjango();
  try {
    const report = await (await session.api.get(`${STAFF_LIST}?q=Болд`)).text();
    found.bold = pkForName(report, "Болд");
    // Ганзориг first, then every other employee in staff-list order, until each kind of row is found.
    const pks = [await optionalPk(session, "Ганзориг"), ...(await allPks(session))].filter(
      (pk, index, all): pk is number => pk !== null && all.indexOf(pk) === index,
    );
    for (const pk of pks) {
      const html = await (await session.api.get(`/employees/${pk}/`)).text();
      scanEmployee(html, pk);
      if (found.waiting && found.edit && found.upload && found.history) break;
    }
  } finally {
    await session.api.dispose();
  }
});

type DjangoSession = { api: APIRequestContext };

// Signs in to Django with the login form (the same fields the harness fills) on an API context that keeps the session
// cookie. The caller disposes `api`.
async function signedInDjango(): Promise<DjangoSession> {
  const username = process.env.PARITY_USER;
  const password = process.env.PARITY_PASSWORD;
  if (!username || !password) {
    throw new Error("Set PARITY_USER and PARITY_PASSWORD (a demo account) before running the parity specs.");
  }
  const api = await request.newContext({ baseURL: DJANGO_URL });
  const loginPage = await api.get("/login/");
  const token = (await loginPage.text()).match(/name="csrfmiddlewaretoken" value="([^"]+)"/)?.[1];
  if (!token) {
    await api.dispose();
    throw new Error("No CSRF token on Django /login/.");
  }
  const signedIn = await api.post("/login/", { form: { username, password, csrfmiddlewaretoken: token } });
  if (new URL(signedIn.url()).pathname.startsWith("/login")) {
    await api.dispose();
    throw new Error("Sign-in to Django failed for the parity account (check PARITY_USER / PARITY_PASSWORD).");
  }
  return { api };
}

// Each <tr> of the report is one employee. Take the first row that names the employee and its link to /employees/<pk>/.
function pkForName(html: string, name: string): number {
  for (const row of html.split(/<tr[\s>]/)) {
    if (!row.includes(name)) continue;
    const match = row.match(/href="\/employees\/(\d+)\/"/);
    if (match) return Number(match[1]);
  }
  throw new Error(`No staff-list row names "${name}" with a link to /employees/<pk>/ (is the demo data seeded?).`);
}

async function optionalPk(session: DjangoSession, name: string): Promise<number | null> {
  try {
    return pkForName(await (await session.api.get(`${STAFF_LIST}?q=${encodeURIComponent(name)}`)).text(), name);
  } catch {
    return null;
  }
}

// Every employee pk on the staff list, in order, without repeats.
async function allPks(session: DjangoSession): Promise<number[]> {
  const report = await (await session.api.get(STAFF_LIST)).text();
  const pks: number[] = [];
  for (const row of report.split(/<tr[\s>]/)) {
    const match = row.match(/href="\/employees\/(\d+)\/"/);
    if (match && !pks.includes(Number(match[1]))) pks.push(Number(match[1]));
  }
  return pks;
}

// Reads one employee's Django page for the three kinds of order row and for the waiting table. The rows are the `<tr>`
// chunks that open with `id="order-N"` (only `_orders.html` draws that id), so the chunk holds the row's own «Үйлдэл» menu.
function scanEmployee(html: string, pk: number): void {
  const at = html.indexOf(WAITING_HEADING);
  if (at >= 0 && found.waiting === null) {
    const table = html.slice(at, html.indexOf("</table>", at));
    if (table.includes(CANCEL)) {
      const label = table.match(/<td>([^<]+)<\/td>/)?.[1]?.trim() ?? "";
      if (label) found.waiting = { pk, label };
    }
  }
  for (const row of html.split(/<tr[\s>]/)) {
    const match = row.match(/^\s*id="order-(\d+)"\s+class="([^"]*)"/);
    if (!match) continue;
    const ref = { pk, orderId: Number(match[1]) };
    if (found.history === null && row.includes("Түүх")) found.history = ref;
    if (found.edit === null && match[2].includes("cursor-pointer")) found.edit = ref;
    if (found.upload === null && row.includes("Файл хавсаргах")) found.upload = ref;
  }
}

// Opens the employee page and hides the assistant button (Django only; see the header comment).
async function openEmployee(page: Page, pk: number): Promise<void> {
  await openPath(page, `/employees/${pk}/`);
  await page.addStyleTag({ content: ASSISTANT_FAB_HIDDEN });
}

// Opens the header event menu and picks one item; waits until the form is on screen.
async function openFromEventMenu(page: Page, item: string): Promise<void> {
  await openEmployee(page, found.bold);
  await page.locator("summary", { hasText: EVENT_MENU }).click();
  await page.getByRole("button", { name: item, exact: true }).click();
  await expect(page.locator(MODAL)).toBeVisible();
  await expect(page.locator(`${MODAL} form`)).toBeVisible();
}

// Step: the transfer form («Албан тушаал, байршил өөрчлөх») from the header menu. Shows the order block.
const openTransfer: Step = (page) => openFromEventMenu(page, TRANSFER_ITEM);

// Step: the leave-start form («Урт чөлөө эхлэх») from the header menu. No order block (the form has no kind select).
const openLeaveStart: Step = (page) => openFromEventMenu(page, LEAVE_START_ITEM);

// Step: on the open transfer form, the kind select goes from «Шилжүүлэх» to «Дэвшүүлэх» (a placement kind). Django reloads
// the form over htmx on the change; React reloads it through the API. Only the kind changes; nothing is saved.
const pickPromotionKind: Step = async (page) => {
  const kind = page.locator(`${MODAL} select[name="kind"]`);
  await kind.selectOption({ label: PROMOTION_KIND });
  await expect(kind.locator("option:checked")).toHaveText(PROMOTION_KIND);
  await expect(page.locator(`${MODAL} form`)).toBeVisible();
};

// Step: «Болих» on the open form (nothing typed, so no confirm). The pop-up must be gone from the page on both sides.
const closeWithCancel: Step = async (page) => {
  await page.locator(MODAL).getByRole("button", { name: "Болих", exact: true }).click();
  await expect(page.locator(MODAL)).toHaveCount(0);
};

// Step: a click on an order row (its date cell, not the «Үйлдэл» menu) opens the order edit pop-up. Skipped when the scan
// found no editable row.
const openOrderEdit: Step = async (page) => {
  const pick = found.edit;
  if (pick === null) {
    test.skip(true, "No employee in the staff list has an editable order row («Бусад тушаал», pending or registered).");
    return;
  }
  await openEmployee(page, pick.pk);
  await page.locator(`#order-${pick.orderId}`).locator("td").first().click();
  await expect(page.locator(MODAL)).toBeVisible();
  await expect(page.locator(`${MODAL} form`)).toBeVisible();
};

// Opens the «Үйлдэл ▾» menu of an order row and picks one of its items. Waits until the menu has closed, so the menu
// does not sit under the pop-up in the screenshot (React's menu closes with an exit; Django's closes at once).
async function openFromRowMenu(page: Page, pick: OrderRow, item: string): Promise<void> {
  await openEmployee(page, pick.pk);
  const row = page.locator(`#order-${pick.orderId}`);
  await row.locator("summary").click();
  await row.getByRole("button", { name: item, exact: true }).click();
  await expect(row.locator("details")).not.toHaveAttribute("open");
  await expect(page.locator(MODAL)).toBeVisible();
}

// Step: «Үйлдэл ▾» → «Түүх» on an order row: the order history pop-up (read only). Skipped when no row was found.
const openOrderHistory: Step = async (page) => {
  const pick = found.history;
  if (pick === null) {
    test.skip(true, "No employee in the staff list has an order row («Бусад тушаал») to open the history of.");
    return;
  }
  await openFromRowMenu(page, pick, "Түүх");
};

// Step: «Үйлдэл ▾» → «Файл хавсаргах» on a registered order row: the upload pop-up (the form is not submitted). Skipped
// when no registered row was found.
const openOrderUpload: Step = async (page) => {
  const pick = found.upload;
  if (pick === null) {
    test.skip(true, "No employee in the staff list has a registered order row with «Файл хавсаргах» (registered only).");
    return;
  }
  await openFromRowMenu(page, pick, "Файл хавсаргах");
};

// Step: «Цуцлах» on the waiting row of a change («Гарын үсэг хүлээж буй өөрчлөлт»): the event cancel pop-up. The row is
// found by its label, which the scan read from the Django page. Skipped when no waiting row was found.
const openEventCancel: Step = async (page) => {
  const pick = found.waiting;
  if (pick === null) {
    test.skip(true, "No employee in the staff list has a waiting change with «Цуцлах» (no change waits for its signed order).");
    return;
  }
  await openEmployee(page, pick.pk);
  const row = page
    .getByRole("row")
    .filter({ hasText: pick.label, has: page.getByRole("button", { name: CANCEL, exact: true }) });
  await row.getByRole("button", { name: CANCEL, exact: true }).first().click();
  await expect(page.locator(MODAL)).toBeVisible();
  await expect(page.locator(`${MODAL} form`)).toBeVisible();
};

// Event form, from the header menu. The transfer form has the order block (the known heading gap, see the header).
parity("event form: transfer from the header menu", LANDING, LANDING, [openTransfer], {
  signIn: true,
  clip: MODAL,
  viewports: DESKTOP,
});

// The same form after its kind is changed to a placement kind («Дэвшүүлэх»): the form is reloaded, not saved.
parity("event form: transfer, kind changed to promotion", LANDING, LANDING, [openTransfer, pickPromotionKind], {
  signIn: true,
  clip: MODAL,
  viewports: DESKTOP,
});

// A non-placement kind: leave start, from the header menu.
parity("event form: leave start from the header menu", LANDING, LANDING, [openLeaveStart], {
  signIn: true,
  clip: MODAL,
  viewports: DESKTOP,
});

// Opening and closing with «Болих»: the whole page is compared (the pop-up is gone at the end). The activity line is masked
// (it shows a time-relative label that differs between runs, as employee.spec.ts masks it).
parity("event form: Болих closes with nothing saved", LANDING, LANDING, [openTransfer, closeWithCancel], {
  signIn: true,
  mask: ["#activity-latest"],
  viewports: DESKTOP,
});

// Order pop-ups from «Бусад тушаал» rows.
parity("order edit pop-up from an order row", LANDING, LANDING, [openOrderEdit], {
  signIn: true,
  clip: MODAL,
  viewports: DESKTOP,
});

parity("order history pop-up from the Үйлдэл menu", LANDING, LANDING, [openOrderHistory], {
  signIn: true,
  clip: MODAL,
  viewports: DESKTOP,
});

parity("order upload pop-up from the Үйлдэл menu", LANDING, LANDING, [openOrderUpload], {
  signIn: true,
  clip: MODAL,
  viewports: DESKTOP,
});

// The event cancel pop-up from a waiting change row.
parity("event cancel pop-up from a waiting row", LANDING, LANDING, [openEventCancel], {
  signIn: true,
  clip: MODAL,
  viewports: DESKTOP,
});
