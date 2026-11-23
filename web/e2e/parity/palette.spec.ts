import { expect, test, type Browser, type Page } from "@playwright/test";
import { DJANGO_URL, WEB_URL, openPath } from "./harness";

// The Ctrl+K search panel («Хайх») on the Today page: Django (base.html #assistant-panel, palette.js) against the React
// shell (shell/palette, AssistantPanel + PaletteResults). Search half only, at 1280 px. The 375 px width is not run here.
//
// Known, expected differences (recorded, not failed on):
// - The Django panel has an «Асуух» (ask) row while the assistant is enabled (`[data-palette-ask]`). React has no such row
//   yet, so the comparison of result rows leaves those Django rows out.
// - The React panel has no assistant thread, «Шинэ яриа», send button or floating «Асуух» button (assistant is step 6).
//   Nothing here looks at them.
// - Django keeps its floating «Асуух» button (`[data-assistant-fab]`); React does not render it yet. Not used here.
//
// Each check runs the same steps on both sides, each side in its own browser context, signed in, on the Today page.

const VIEWPORT = { width: 1280, height: 800 };
const TODAY = "/employees/today/";

const PANEL = "[data-assistant-panel]";
const BOX = "[data-assistant-panel] [data-palette-input]";
const RESULTS = "[data-palette-results]";
// The top-bar «Хайх» button. Scoped to the header: Today also has a «Хайх» button in its body (data-palette-open).
const TOP_BUTTON = "header [data-palette-open]";
const GROUP_RECENT = "Сүүлд нээсэн";
const ACTION_LABEL = "Орон тоо нэмэх";

type Row = { label: string; group: string; ref: string | null };
type Employee = { pk: string; name: string };

// Signs in like harness.ts login(), but picks the submit button without the password toggle: the Django login page now
// has a password-toggle button that also matches `form button`, so the harness selector is ambiguous there.
async function signIn(page: Page, base: string): Promise<void> {
  const username = process.env.PARITY_USER;
  const password = process.env.PARITY_PASSWORD;
  if (!username || !password) {
    throw new Error("Set PARITY_USER and PARITY_PASSWORD (a demo account) before running the parity specs.");
  }
  await page.waitForURL((url) => url.pathname.startsWith("/login"));
  await page.locator("#id_username").fill(username);
  await page.locator("#id_password").fill(password);
  // The submit button: Django's #login-submit has no type attribute, React's is type="submit"; the password toggle is
  // type="button" on Django, so it is left out.
  await page.locator('form button:not([type="button"])').click();
  await page.waitForURL((url) => url.origin === base && !url.pathname.startsWith("/login"));
}

// Runs `run` on one side: a fresh context at 1280 px with motion allowed, signed in, then on `path`.
async function onSide<T>(browser: Browser, base: string, path: string, run: (page: Page) => Promise<T>): Promise<T> {
  const context = await browser.newContext({ viewport: VIEWPORT, colorScheme: "light", reducedMotion: "no-preference" });
  try {
    const page = await context.newPage();
    await page.goto(base + path);
    await signIn(page, base);
    await openPath(page, path);
    return await run(page);
  } finally {
    await context.close();
  }
}

async function both<T>(browser: Browser, path: string, run: (page: Page) => Promise<T>): Promise<{ django: T; web: T }> {
  const django = await onSide(browser, DJANGO_URL, path, run);
  const web = await onSide(browser, WEB_URL, path, run);
  return { django, web };
}

// The first employee of the Employees list (the list address redirects to the staff-list report). Read once from Django;
// both sides share one database, so the same person is searched on both.
let firstEmployeeCache: Promise<Employee> | null = null;
function firstEmployee(browser: Browser): Promise<Employee> {
  firstEmployeeCache ??= onSide(browser, DJANGO_URL, "/employees/", async (page) => {
    const found = await page.evaluate(() => {
      for (const a of Array.from(document.querySelectorAll<HTMLAnchorElement>("a[href]"))) {
        const m = /^\/employees\/(\d+)\/?$/.exec(a.getAttribute("href") ?? "");
        const name = (a.textContent ?? "").replace(/\s+/g, " ").trim();
        if (m && name) return { pk: m[1], name };
      }
      return null;
    });
    if (!found) throw new Error("No employee link found on the Django Employees list (/employees/).");
    return found;
  });
  return firstEmployeeCache;
}

// Opens the panel when it is closed. The top-bar button and Ctrl+K both toggle, so a panel that the page restored as
// open is left open.
async function ensureOpen(page: Page): Promise<void> {
  if (await page.locator(PANEL).isVisible()) return;
  await page.locator(TOP_BUTTON).first().click();
  await expect(page.locator(PANEL)).toBeVisible();
}

async function openWithShortcut(page: Page): Promise<void> {
  await expect(page.locator(PANEL)).toBeHidden();
  await page.keyboard.press("Control+KeyK");
  await expect(page.locator(PANEL)).toBeVisible();
}

// The result rows as the user sees them, in order: the label (all text of the row), its group title and its ref
// (p:<pk> for a person, s:<url> for a fixed page). Django's «Асуух» row is left out (known difference, see the header).
async function rowsOf(page: Page): Promise<Row[]> {
  return page.locator(RESULTS).evaluate((results) => {
    const norm = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim();
    return Array.from(results.querySelectorAll("[data-palette-item]"))
      .filter((el) => !el.hasAttribute("data-palette-ask"))
      .map((el) => ({
        label: norm(el.textContent),
        group: norm(el.parentElement?.querySelector(":scope > :first-child > span")?.textContent),
        ref: el.getAttribute("data-palette-ref"),
      }));
  });
}

// Moves the selection with the arrows until the person's row is selected, then steps down and back up (both arrows are
// exercised), and presses Enter. Returns the pathname the page went to.
async function openPersonByKeys(page: Page, pk: string): Promise<string> {
  const row = page.locator(`${RESULTS} [data-palette-item][data-palette-ref="p:${pk}"]`);
  await expect(row).toBeVisible();
  for (let i = 0; i < 40 && (await row.getAttribute("aria-selected")) !== "true"; i++) {
    await page.keyboard.press("ArrowDown");
  }
  await expect(row).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowUp");
  await expect(row).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Enter");
  await page.waitForURL(new RegExp(`/employees/${pk}/?$`));
  await page.waitForLoadState("networkidle");
  return new URL(page.url()).pathname.replace(/\/$/, "");
}

test.describe("palette at 1280 px", () => {
  // Each check signs in on both sides (two full logins and page loads), so it needs more than the 30 s default.
  test.setTimeout(180_000);

  test("the top-bar «Хайх» button opens the panel with the box focused", async ({ browser }) => {
    const opened = await both(browser, TODAY, async (page) => {
      await expect(page.locator(PANEL)).toBeHidden();
      await page.locator(TOP_BUTTON).first().click();
      await expect(page.locator(PANEL)).toBeVisible();
      return {
        visible: await page.locator(PANEL).isVisible(),
        boxFocused: await page.locator(BOX).evaluate((el) => el === document.activeElement),
      };
    });
    expect(opened.django).toEqual({ visible: true, boxFocused: true });
    expect(opened.web).toEqual({ visible: true, boxFocused: true });
  });

  test("Ctrl+K opens the panel with the box focused", async ({ browser }) => {
    const opened = await both(browser, TODAY, async (page) => {
      await openWithShortcut(page);
      return {
        visible: await page.locator(PANEL).isVisible(),
        boxFocused: await page.locator(BOX).evaluate((el) => el === document.activeElement),
      };
    });
    expect(opened.django).toEqual({ visible: true, boxFocused: true });
    expect(opened.web).toEqual({ visible: true, boxFocused: true });
  });

  test("typing «орон» gives the same result rows, with «Орон тоо нэмэх» under «Үйлдэл»", async ({ browser }) => {
    const { django, web } = await both(browser, TODAY, async (page) => {
      await ensureOpen(page);
      await page.locator(BOX).fill("орон");
      // The empty box's quick list also holds «Орон тоо нэмэх», so wait for a row only the «орон» answer has, and for the
      // empty list to be gone, before reading the rows.
      await expect(
        page.locator(`${RESULTS} [data-palette-item]`).filter({ hasText: "Жагсаалт · Орон байрны нөхцөл" }).first(),
      ).toBeVisible();
      await expect(page.locator(RESULTS).getByText("Өнөөдөр", { exact: true })).toHaveCount(0);
      return rowsOf(page);
    });
    const action = (rows: Row[]) => rows.find((r) => r.label === ACTION_LABEL);
    expect(action(django)?.group, "Django: the action row's group").toBe("Үйлдэл");
    expect(action(web)?.group, "React: the action row's group").toBe("Үйлдэл");
    expect(web.map((r) => r.label)).toEqual(django.map((r) => r.label));
    expect(web).toEqual(django);
  });

  test("a person's name: arrows and Enter open that employee's page", async ({ browser }) => {
    const employee = await firstEmployee(browser);
    const { django, web } = await both(browser, TODAY, async (page) => {
      await ensureOpen(page);
      await page.locator(BOX).fill(employee.name);
      return openPersonByKeys(page, employee.pk);
    });
    expect(web).toBe(django);
    expect(django).toMatch(new RegExp(`/employees/${employee.pk}$`));
  });

  test("«show all» row, when the query has more people than the first page", async ({ browser }) => {
    // Try a few common letters; the first one that shows the «show all» row on Django is used on both sides.
    const queries = ["а", "н", "о", "и"];
    const { django, web } = await both(browser, TODAY, async (page) => {
      await ensureOpen(page);
      const results = page.locator(RESULTS);
      let used: string | null = null;
      for (const q of queries) {
        await page.locator(BOX).fill(q);
        await expect(results.locator("[data-palette-item]").first()).toBeVisible();
        await page.waitForTimeout(400);
        if ((await results.locator("[data-palette-more]").count()) > 0) {
          used = q;
          break;
        }
      }
      if (used === null) return { query: null as string | null, people: -1, after: -1, panelOpen: null as boolean | null };
      const peopleBefore = (await rowsOf(page)).filter((r) => r.ref?.startsWith("p:")).length;
      await results.locator("[data-palette-more]").first().click();
      await expect
        .poll(async () => (await rowsOf(page)).filter((r) => r.ref?.startsWith("p:")).length)
        .toBeGreaterThan(peopleBefore);
      const peopleAfter = (await rowsOf(page)).filter((r) => r.ref?.startsWith("p:")).length;
      return { query: used, people: peopleBefore, after: peopleAfter, panelOpen: await page.locator(PANEL).isVisible() };
    });
    if (django.query === null && web.query === null) {
      test.info().annotations.push({
        type: "not exercised",
        description: "No tried query showed a «show all» row on either side (the row is absent, which matches).",
      });
      return;
    }
    expect(web.query, "the «show all» row appears on both sides for the same query").toBe(django.query);
    expect(web.people, "people shown before «show all»").toBe(django.people);
    expect(web.after, "people shown after «show all»").toBe(django.after);
    expect(web.panelOpen).toBe(true);
    expect(django.panelOpen).toBe(true);
  });

  test("an empty box shows the recents after one visit to an employee", async ({ browser }) => {
    const employee = await firstEmployee(browser);
    const { django, web } = await both(browser, TODAY, async (page) => {
      // The visit: a person opened from the panel is remembered (per user) and shows under «Сүүлд нээсэн».
      await ensureOpen(page);
      await page.locator(BOX).fill(employee.name);
      await openPersonByKeys(page, employee.pk);
      await openPath(page, TODAY);
      await ensureOpen(page);
      await expect(page.locator(BOX)).toHaveValue("");
      const recent = page.locator(`${RESULTS} [data-palette-item][data-palette-ref="p:${employee.pk}"]`);
      await expect(recent).toBeVisible();
      await expect(page.locator(RESULTS).getByText(GROUP_RECENT, { exact: true })).toBeVisible();
      return (await rowsOf(page)).filter((r) => r.group === GROUP_RECENT);
    });
    expect(web.map((r) => r.ref)).toEqual(django.map((r) => r.ref));
    expect(web.length).toBeGreaterThan(0);
    expect(django.some((r) => r.ref === `p:${employee.pk}`)).toBe(true);
  });

  test("Escape clears the typed text, a second Escape closes the panel", async ({ browser }) => {
    const { django, web } = await both(browser, TODAY, async (page) => {
      await ensureOpen(page);
      await page.locator(BOX).fill("орон");
      await page.keyboard.press("Escape");
      const cleared = await page.locator(BOX).inputValue();
      await expect(page.locator(PANEL)).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.locator(PANEL)).toBeHidden();
      return { cleared };
    });
    expect(django).toEqual({ cleared: "" });
    expect(web).toEqual({ cleared: "" });
  });
});
