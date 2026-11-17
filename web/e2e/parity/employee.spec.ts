import { expect, request, test, type Browser, type Page } from "@playwright/test";
import { DJANGO_URL, WEB_URL, bothSides, login, openPath, parity, type Step } from "./harness";

// Employee page («Ажилтны хэсэг»): Django employees/detail.html against EmployeePage, at /employees/<pk>/. The demo user
// is `hr`. The pk is not hard-coded: beforeAll finds the employee by name through an authenticated request to the
// staff-list report (/reports/staff-list/?q=<name>), and every step reads that pk when it runs.
//
// Which seeded employee: Болд (seed_demo's `bold` login). He has the family rows (a father, Дорждэрэм, and two children,
// in _demo_scenarios.py _children_and_gifts) and a dated change in his job history (a salary change from 2026-01-01,
// seed_demo.py). NO seeded employee has a photo: seed_demo and _demo_scenarios never write emp_photo (only the UI
// writes it, through records.set_photo), so the photo part of the page is the letter fallback on both sides. Тэмүүлэн
// has the job changes (a promotion with a position change, two department corrections) but no family rows, so Болд is
// the closer match.
const EMPLOYEE_NAME = "Болд";
const STAFF_LIST = "/reports/staff-list/";
// Signed-in home for the Django side and for the React side; the employee page is opened by the first step.
const LANDING = "/employees/today/";

// The rail (aside) and the narrow section bar (nav), both labelled «Ажилтны хэсгүүд» on both sides.
const RAIL = "aside#emp-rail";
const TAB_BAR = 'nav[aria-label="Ажилтны хэсгүүд"]';
// The «Түүх» header button: the button that holds the activity count (both sides).
const ACTIVITY_BUTTON = "button:has(#activity-count)";
// Tailwind lg breakpoint: the rail shows at and above this width, the tab bar below it.
const LG_WIDTH = 1024;

let employeePk = 0;

test.beforeAll(async () => {
  employeePk = await findEmployeePk(EMPLOYEE_NAME);
});

// Signs in to Django with the login form (the same fields the harness fills), then reads the staff-list report for the
// name. The row that names the employee holds the link to its page.
async function findEmployeePk(name: string): Promise<number> {
  const username = process.env.PARITY_USER;
  const password = process.env.PARITY_PASSWORD;
  if (!username || !password) {
    throw new Error("Set PARITY_USER and PARITY_PASSWORD (a demo account) before running the parity specs.");
  }
  const api = await request.newContext({ baseURL: DJANGO_URL });
  try {
    const loginPage = await api.get("/login/");
    const token = (await loginPage.text()).match(/name="csrfmiddlewaretoken" value="([^"]+)"/)?.[1];
    if (!token) throw new Error("No CSRF token on Django /login/.");
    const signedIn = await api.post("/login/", { form: { username, password, csrfmiddlewaretoken: token } });
    if (new URL(signedIn.url()).pathname.startsWith("/login")) {
      throw new Error("Sign-in to Django failed for the parity account (check PARITY_USER / PARITY_PASSWORD).");
    }
    const report = await api.get(`${STAFF_LIST}?q=${encodeURIComponent(name)}`);
    return pkForName(await report.text(), name);
  } finally {
    await api.dispose();
  }
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

// Opens the employee page. Runs on both sides, so the path is the same; the origin comes from the page.
const openEmployee: Step = (page) => openPath(page, `/employees/${employeePk}/`);

// Opens the employee page, then the «Түүх» drawer by its header button, and waits until the drawer has slid in.
const openEmployeeDrawer: Step = async (page: Page) => {
  await openEmployee(page);
  await page.locator(ACTIVITY_BUTTON).first().click();
  const drawer = page.locator("#activity-drawer");
  await expect(drawer).toHaveAttribute("aria-hidden", "false");
  // The drawer slides in over 200 ms; wait until it is on screen before the screenshot.
  await expect
    .poll(() => drawer.evaluate((el) => el.getBoundingClientRect().left < window.innerWidth - 1))
    .toBe(true);
};

// Opens the employee page, then the «Хувийн» group «Боловсрол» (data-pgroup="edu"), unless it is already open.
const openEmployeePersonalGroup: Step = async (page: Page) => {
  await openEmployee(page);
  const group = page.locator('details[data-pgroup="edu"]');
  await expect(group).toHaveCount(1);
  if (!(await group.evaluate((el) => (el as HTMLDetailsElement).open))) {
    await group.locator("summary").first().click();
  }
  await expect.poll(() => group.evaluate((el) => (el as HTMLDetailsElement).open)).toBe(true);
};

// Full-page screenshots: light and dark, 1280 px and 375 px (the harness runs all four).
parity("employee page", LANDING, LANDING, [openEmployee], { signIn: true });

// The «Түүх» drawer, clipped to the drawer element (the harness clip applies to every step, so the drawer is the only step).
parity("employee activity drawer", LANDING, LANDING, [openEmployeeDrawer], {
  signIn: true,
  clip: "#activity-drawer",
});

// The personal group «Боловсрол» expanded, clipped to the personal section that holds it.
parity("employee personal group", LANDING, LANDING, [openEmployeePersonalGroup], {
  signIn: true,
  clip: "#tab-personal",
});

// Visibility of the rail and of the narrow section bar at one width, on one side. Its own context, because bothSides
// always uses the default viewport.
async function railAndBar(browser: Browser, base: string, width: number): Promise<{ rail: boolean; bar: boolean }> {
  const context = await browser.newContext({
    viewport: { width, height: 812 },
    reducedMotion: "no-preference",
  });
  try {
    const page = await context.newPage();
    await page.goto(base + LANDING);
    await login(page, base);
    await openPath(page, `/employees/${employeePk}/`);
    return {
      rail: await page.locator(RAIL).isVisible(),
      bar: await page.locator(TAB_BAR).isVisible(),
    };
  } finally {
    await context.close();
  }
}

const clean = (text: string) => text.replace(/\s+/g, " ").trim();

test.describe("employee steps", () => {
  test.use({ reducedMotion: "no-preference" });

  test("at phone width the section bar shows and the rail does not; at desktop width the reverse, the same on both sides", async ({
    browser,
  }) => {
    for (const width of [375, 1280]) {
      const django = await railAndBar(browser, DJANGO_URL, width);
      const web = await railAndBar(browser, WEB_URL, width);
      expect(web, `visibility at ${width}px`).toEqual(django);
      const expected = width < LG_WIDTH ? { rail: false, bar: true } : { rail: true, bar: false };
      expect(django, `visibility at ${width}px`).toEqual(expected);
    }
  });

  test("the section headings, rail links and activity count are the same text on both sides", async ({ browser }) => {
    const path = `/employees/${employeePk}/`;
    const sides = await bothSides(browser, path, async (page) => {
      const headings = (await page.locator("main h2").allTextContents()).map(clean);
      const rail = (await page.locator(`${RAIL} a.rtab`).allTextContents()).map(clean);
      const activity = clean(await page.locator("#activity-count").innerText());
      return { headings, rail, activity };
    });
    expect(sides.web.headings).toEqual(sides.django.headings);
    expect(sides.web.rail).toEqual(sides.django.rail);
    expect(sides.web.activity).toEqual(sides.django.activity);
    // The work section is always there; the rail's first link goes to it.
    expect(sides.django.headings).toEqual(expect.arrayContaining(["Ажил"]));
    expect(sides.django.rail).toEqual(expect.arrayContaining(["Ажил"]));
  });
});
