import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { DJANGO_URL, openPath, parity, type Step } from "./harness";

// Employee page writes (step 3b): each step opens /employees/<pk>/, makes one edit or opens one pop-up, and compares the
// two sides. Nothing is saved (parity does not write), so the edits stay in the page and each step is its own parity()
// test, starting from a fresh page with no earlier edit in it.
//
// Employees, found by name in beforeAll (the pk is read at run time, as in employee.spec.ts):
// - «Болд» (seed_demo.py, login `bold`): the header, the identity section, the language list, the relatives list and the
//   salary pop-up.
// - The create-login step needs an employee with no login at run time (the header shows «Нэвтрэх эрх үүсгэх» only then).
//   The demo data changes (a login can be created by an earlier run), so it is not a fixed name: beforeAll takes the
//   first staff-list row whose Django page has that button. See findNoLoginPk.
//
// Selectors that exist on both sides: `#header` (the header card), `#header input[name="work_phone"]`, `#save-bar` (the
// save bar; the React SaveBar has the same id), `#sec-identity` and `#sec-identity-form` (identity section and its form),
// `#sec-language` and `#list-language` (inline list), `#sec-relative` (pop-up list), `#tab-salary`, `details[data-pgroup]`.
// The pop-up overlay is `.fixed.inset-0.z-50` (Django `_modal.html` and friends; React `widgets/Modal`). The `z-50` part
// tells it apart from Django's hidden `#activity-backdrop` (`fixed inset-0 ... z-30`), which comes first in the DOM.
//
// Notes on the plan:
// - «Гэр бүл» is NOT a pop-up list: both sides edit it in its own rows (`_section_family.html` uses `_inline_list.html`).
//   The pop-up list of Болд's relatives is «Хамаатан садан» (`_section_relative.html`, `sec-relative`), so step 4 uses it.
// - «Гадаад хэл» sits in the group «Боловсрол, туршлага» (data-pgroup="edu"), which is closed by default, so step 3
//   opens that group first.
// - «Үндсэн мэдээлэл» (data-pgroup="basic") is open by default; the helper only opens it if it is closed.
// - The salary pop-up needs `view_salary`, which the HR role does not have (access.py, roles.py). With the HR parity
//   account `#tab-salary` is absent on both sides, so step 5 skips (see its comment).

const EMPLOYEE_NAME = "Болд";
const CREATE_LOGIN = "Нэвтрэх эрх үүсгэх";
const STAFF_LIST = "/reports/staff-list/";
// Signed-in home for both sides; each step opens its employee page itself.
const LANDING = "/employees/today/";

const PHONE = "7700-0001";
const TEXT = "Туршилт";
const ADD = "+ нэмэх";
const MODAL = ".fixed.inset-0.z-50";

let bold = 0;
// null when no employee in the staff list has the create-login button (the create-login step is then skipped).
let noLogin: number | null = null;

test.beforeAll(async () => {
  const session = await signedInDjango();
  try {
    bold = (await findEmployeePks(session, [EMPLOYEE_NAME]))[EMPLOYEE_NAME];
    noLogin = await findNoLoginPk(session);
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

// Reads the staff-list report for each name. The row that names the employee holds the link to its page.
async function findEmployeePks(session: DjangoSession, names: string[]): Promise<Record<string, number>> {
  const found: Record<string, number> = {};
  for (const name of names) {
    const report = await session.api.get(`${STAFF_LIST}?q=${encodeURIComponent(name)}`);
    found[name] = pkForName(await report.text(), name);
  }
  return found;
}

// Walks the staff-list rows in order and fetches each employee's Django page, stopping at the first one that shows the
// «Нэвтрэх эрх үүсгэх» button (an employee with no login). Returns null when no row has it.
async function findNoLoginPk(session: DjangoSession): Promise<number | null> {
  const report = await (await session.api.get(STAFF_LIST)).text();
  const pks: number[] = [];
  for (const row of report.split(/<tr[\s>]/)) {
    const match = row.match(/href="\/employees\/(\d+)\/"/);
    if (match && !pks.includes(Number(match[1]))) pks.push(Number(match[1]));
  }
  for (const pk of pks) {
    const detail = await (await session.api.get(`/employees/${pk}/`)).text();
    if (detail.includes(CREATE_LOGIN)) return pk;
  }
  return null;
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

// Opens the page of «Болд» / «Тэмүүлэн». The pk is read when the step runs, not when this module loads.
const openBold: Step = (page) => openPath(page, `/employees/${bold}/`);

// Expands a personal group (data-pgroup) unless it is already open, as employee.spec.ts does.
async function openPersonalGroup(page: Page, key: string): Promise<void> {
  const group = page.locator(`details[data-pgroup="${key}"]`);
  await expect(group).toHaveCount(1);
  if (!(await group.evaluate((el) => (el as HTMLDetailsElement).open))) {
    await group.locator("summary").first().click();
  }
  await expect.poll(() => group.evaluate((el) => (el as HTMLDetailsElement).open)).toBe(true);
}

// Step 1, header edit: type a new work phone in the header box, then wait for the save bar. The box is blurred after
// typing so the focused element is the same on both sides (the harness compares the focused id; the focus after a
// typed edit is not what this step checks).
const headerEdit: Step = async (page) => {
  await openBold(page);
  const phone = page.locator('#header input[name="work_phone"]');
  await expect(phone).toHaveCount(1);
  await phone.fill(PHONE);
  await phone.blur();
  await expect(page.locator("#save-bar")).toBeVisible();
};

// Step 2, personal section edit: expand «Үндсэн мэдээлэл», type into the first text box of the identity section, then
// wait for its strip («Хадгалаагүй өөрчлөлт байна», «Болих», «Хадгалах»). Blurred after typing, as in step 1.
const identityEdit: Step = async (page) => {
  await openBold(page);
  await openPersonalGroup(page, "basic");
  const box = page.locator('#sec-identity-form input[type="text"]').first();
  await expect(box).toHaveCount(1);
  await box.fill(TEXT);
  await box.blur();
  await expect(page.locator("#sec-identity").getByText("Хадгалаагүй өөрчлөлт байна")).toBeVisible();
};

// Step 3, inline list row open: expand «Боловсрол, туршлага», click «+ нэмэх» of «Гадаад хэл» and wait for the open row.
const languageRowOpen: Step = async (page) => {
  await openBold(page);
  await openPersonalGroup(page, "edu");
  await page.locator("#sec-language").getByRole("button", { name: ADD, exact: true }).click();
  await expect(page.locator("#list-language").locator('input:not([type="hidden"]), select').first()).toBeVisible();
  // Blur the typing box so its dropdown closes before the screenshot. select.js (Django) flips the dropdown above or
  // below the box by the scroll position at the moment it opens, a timing artefact; React places it below. The dropdown
  // itself is covered by widgets.spec.ts. The row is compared without it.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await expect(page.locator("#list-language .sel-popup, #list-language .sel-list")).toHaveCount(0);
};

// Step 4, pop-up list add: click «+ нэмэх» of «Хамаатан садан» (a pop-up list; see the notes above) and wait for the
// pop-up.
// At 375px the Django pop-up is 8px taller than React's, because Django's pop-up branch box takes the page form's soft
// look (the page and the pop-up both have id="id_branch"; a Django duplicate id). React is correct and this is not
// replicated. Skipped at 375px only; see EXPECTED_DIFFS.md for the computed heights. 1280px still runs.
const relativeAdd: Step = async (page) => {
  if (page.viewportSize()?.width === 375) {
    test.skip(true, "Django duplicate id=\"id_branch\" makes its pop-up 8px taller at 375px (EXPECTED_DIFFS.md, relative add pop-up).");
  }
  await openBold(page);
  await openPersonalGroup(page, "basic");
  await page.locator("#sec-relative").getByRole("button", { name: ADD, exact: true }).click();
  await expect(page.locator(MODAL)).toBeVisible();
};

// Step 5, correct salary pop-up: click the first «Засвар» of the salary history and wait for the pop-up.
// Skipped (not failed) when the Django side has no «Засвар» button for this employee: the parity account cannot see the
// salary tab (HR role, no view_salary), or the demo record is not correctable. Both sides show the same, so the React
// side is only checked when Django has the button.
const salaryCorrect: Step = async (page) => {
  await openBold(page);
  const correct = page.locator("#tab-salary").getByRole("button", { name: "Засвар", exact: true }).first();
  if (page.url().startsWith(DJANGO_URL) && (await correct.count()) === 0) {
    test.skip(true, "No «Засвар» button on the Django salary tab for Болд (parity account without view_salary, or no correctable record).");
  }
  await correct.click();
  await expect(page.locator(MODAL)).toBeVisible();
};

// Step 6, create login pop-up: click «Нэвтрэх эрх үүсгэх» in the header of «Тэмүүлэн» (no login) and wait for the form.
// The form is not submitted.
const loginCreate: Step = async (page) => {
  if (noLogin === null) {
    test.skip(true, "No employee in the staff list has the «Нэвтрэх эрх үүсгэх» button (every demo employee already has a login).");
  }
  await openPath(page, `/employees/${noLogin}/`);
  await page.locator("#header").getByRole("button", { name: CREATE_LOGIN, exact: true }).click();
  await expect(page.locator(MODAL)).toBeVisible();
};

// Full page. The activity line is masked: it shows a time-relative label that differs between runs.
parity("employee header edit", LANDING, LANDING, [headerEdit], {
  signIn: true,
  mask: ["#activity-latest"],
});

// The identity section with its strip. Clipped to the section, which holds the strip.
parity("employee identity edit", LANDING, LANDING, [identityEdit], {
  signIn: true,
  clip: "#sec-identity",
});

// The language list with its open row.
parity("employee language row open", LANDING, LANDING, [languageRowOpen], {
  signIn: true,
  clip: "#sec-language",
});

// The relatives pop-up, opened from «+ нэмэх».
parity("employee relative add pop-up", LANDING, LANDING, [relativeAdd], {
  signIn: true,
  clip: MODAL,
});

// The salary correction pop-up, opened from the first «Засвар».
parity("employee salary correct pop-up", LANDING, LANDING, [salaryCorrect], {
  signIn: true,
  clip: MODAL,
});

// The create-login pop-up, step 1 (the form only; not submitted).
parity("employee create login pop-up", LANDING, LANDING, [loginCreate], {
  signIn: true,
  clip: MODAL,
});
