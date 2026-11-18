import { expect, test, type Page } from "@playwright/test";
import { DJANGO_URL, WEB_URL, bothSides, login, openPath, parity, type Step } from "./harness";

// Add employee page (step 3c): Django `/employees/new/` (`employees/add.html`) and React `/employees/new/` (`screens/hire`)
// side by side. Read-only checks first: the empty form and each tab, then the register check line. The write flow at the
// end creates a real employee in the shared demo database, so it runs only with PARITY_WRITES=1 and only on the React side.
//
// Selectors that exist on both sides: `[data-tab-btn="<key>"]` (the tab buttons; keys basic, personal, salary, login),
// `section[data-tab="<key>"]` (the tab panels), `input[name="register_no"]` (the register box), `#register-check` (the
// check line span; the link inside it is the match), `#add-form` (the form), `Ажилтан үүсгэх` (the submit button).
//
// The register number for the check comes from PARITY_REGISTER_NO. Unset, it is the first employee of the demo seed:
// `app/employees/management/commands/seed_demo.py`, the first PEOPLE entry (login "director"), reg="УБ78052314".
// The check line shows only for an employee the parity account may see (`access.visible_employees`). If that account
// cannot see the director, the check fails on both sides with an empty line: set PARITY_REGISTER_NO to another seed
// register (for example Болд, reg="УЕ92041509", the employee the other specs use).

const HIRE = "/employees/new/";
// The tab keys of the page (the same on both sides).
const BASIC = "basic";
const PERSONAL = "personal";
const SALARY = "salary";
const LOGIN = "login";
// Phone-width, tablet and desktop widths. The harness default (1280, 375) has no tablet width.
const VIEWPORTS = [
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1280, height: 800 },
];

const SEEDED_REGISTER = "УЕ92041509"; // Болд (seed_demo.py): verified visible to the parity account `hr`
const REGISTER_LINE = "Энэ регистрийн дугаартай ажилтан аль хэдийн бүртгэлтэй";

// Opens the add page on this side (the signed-in page is the home page after sign-in; each step opens the page itself).
const openHire: Step = (page) => openPath(page, HIRE);

// Step: the page as it opens, on the «Үндсэн» tab (its panel shows). Nothing is clicked.
const emptyForm: Step = async (page) => {
  await openHire(page);
  await expect(page.locator(`section[data-tab="${BASIC}"]`)).toBeVisible();
};

// Step: open the page and click one tab button, then wait for its panel.
function clickTab(key: string): Step {
  return async (page) => {
    await openHire(page);
    await page.locator(`[data-tab-btn="${key}"]`).click();
    await expect(page.locator(`section[data-tab="${key}"]`)).toBeVisible();
  };
}

// Step «Цалин, даатгал»: skipped (not failed) when the Django page has no salary tab. The tab is there only with the salary
// right (`si is not None` in add.html); the HR parity account does not have it (see employee-edit.spec.ts, step 5).
const clickSalaryTab: Step = async (page) => {
  await openHire(page);
  const tab = page.locator(`[data-tab-btn="${SALARY}"]`);
  if (page.url().startsWith(DJANGO_URL) && (await tab.count()) === 0) {
    test.skip(true, "No «Цалин, даатгал» tab on the Django add page for the parity account (no salary right).");
  }
  await tab.click();
  await expect(page.locator(`section[data-tab="${SALARY}"]`)).toBeVisible();
};

// Read-only parity: the same page, screenshot compared after each step, at three widths and both themes.
parity("hire empty form", HIRE, HIRE, [emptyForm], { signIn: true, viewports: VIEWPORTS });
parity("hire personal tab", HIRE, HIRE, [clickTab(PERSONAL)], { signIn: true, viewports: VIEWPORTS });
parity("hire salary tab", HIRE, HIRE, [clickSalaryTab], { signIn: true, viewports: VIEWPORTS });
parity("hire login tab", HIRE, HIRE, [clickTab(LOGIN)], { signIn: true, viewports: VIEWPORTS });

// Types the register number into the register box and waits for the check line. Returns the line's text and the text of
// its link, with whitespace collapsed, so the two sides can be compared as plain strings.
async function registerCheck(page: Page, number: string): Promise<{ text: string; link: string }> {
  const box = page.locator('input[name="register_no"]');
  await expect(box).toHaveCount(1);
  await box.fill(number);
  // Find the line by its text, not by the #register-check id (React keeps the span; see the Django quirk below).
  const line = page.locator("span.text-xs.text-red-600", { hasText: REGISTER_LINE });
  // The check waits 400 ms after the last change, then the answer arrives.
  await expect(line.locator("a")).toBeVisible();
  const text = ((await line.textContent()) ?? "").replace(/\s+/g, " ").trim();
  const link = ((await line.locator("a").textContent()) ?? "").replace(/\s+/g, " ").trim();
  return { text, link };
}

// React side only. The Django page's live check never shows its line: the register box inherits hx-select="main" and
// hx-swap="outerHTML" from #add-form, the answer is a fragment with no <main>, so htmx swaps the #register-check span
// for nothing (verified in a browser: the request answers 200 with the right line, and the page shows nothing). That is
// an old Django bug, recorded in EXPECTED_DIFFS.md (step 3c); the React line is the intended behaviour.
test("hire register check: React shows the existing employee's line and link", async ({ browser }) => {
  const number = process.env.PARITY_REGISTER_NO || SEEDED_REGISTER;
  const context = await browser.newContext({ reducedMotion: "no-preference" });
  try {
    const page = await context.newPage();
    await page.goto(WEB_URL + HIRE);
    await login(page, WEB_URL);
    await openPath(page, HIRE);
    const web = await registerCheck(page, number);
    expect(web.text).toContain(REGISTER_LINE);
    expect(web.link.length, "the link names the employee").toBeGreaterThan(0);
  } finally {
    await context.close();
  }
});

// Write flow (React only). Creates one employee with a clearly fake name and a unique register number. Nothing is deleted.
// Gated: set PARITY_WRITES=1 after the user has said yes to writing to the shared demo database.
const DATE_PLACEHOLDER = "ЖЖЖЖ-СС-ӨӨ"; // the DatePicker's text box placeholder (screens/hire uses widgets/DatePicker)
const STAMP = String(Date.now());
const FAMILY = "Тест";
const GIVEN = `Parity${STAMP.slice(-6)}`;
const REGISTER = `ТП${STAMP.slice(-8)}`; // two Cyrillic letters and eight digits (validators.REGISTER_NO)
const PHONE = `99${STAMP.slice(-6)}`;
const DEFAULT_DATE = "2026-11-01";
const DATES: Record<string, string> = { birth_date: "1990-05-12" };

function textFor(name: string | null): string {
  switch (name) {
    case "family_name":
      return FAMILY;
    case "given_name":
      return GIVEN;
    case "register_no":
      return REGISTER;
    case "work_phone":
      return PHONE;
    default:
      return "Туршилт";
  }
}

// Fills every empty required control of the form, in page order: a typing select (combobox) gets its first real option,
// a native select its first non-empty option, a date box a date, a text box a value by its name.
async function fillRequired(page: Page): Promise<void> {
  const controls = page.locator("#add-form [required]");
  const count = await controls.count();
  for (let i = 0; i < count; i++) {
    const control = controls.nth(i);
    // A native select that the picker widget hides is filled through its visible typing box; waiting for it would hang.
    if (!(await control.isVisible())) continue;
    const info = await control.evaluate((el) => ({
      tag: el.tagName,
      role: el.getAttribute("role"),
      type: el.getAttribute("type"),
      name: el.getAttribute("name"),
      placeholder: el.getAttribute("placeholder"),
      // A date box sits in a label with the calendar button (accessible name «Хуанли нээх»).
      isDate: !!el.closest("label")?.querySelector('[aria-label*="Хуанли"], [title*="Хуанли"]'),
      value: (el as HTMLInputElement | HTMLSelectElement).value ?? "",
    }));
    if (info.value !== "" || info.type === "file") continue;
    if (info.role === "combobox") {
      await control.click();
      // The list is a portal on document.body; the blank choice is drawn as "—".
      await page.locator('[role="listbox"] [role="option"]').filter({ hasNotText: "—" }).first().click();
    } else if (info.tag === "SELECT") {
      const first = await control.evaluate(
        (el) => Array.from((el as HTMLSelectElement).options).find((o) => o.value !== "")?.value ?? "",
      );
      await control.selectOption(first);
    } else if (info.type === "checkbox") {
      await control.check();
    } else if (info.isDate || info.placeholder === DATE_PLACEHOLDER) {
      await control.fill(DATES[info.name ?? ""] ?? DEFAULT_DATE);
      await control.blur(); // the DatePicker reads the typed value on blur
    } else if (info.type === "number") {
      await control.fill("1");
    } else {
      await control.fill(textFor(info.name));
    }
  }
}

test.describe("hire write flow (React only)", () => {
  test.skip(process.env.PARITY_WRITES !== "1", "Writes to the shared demo database: set PARITY_WRITES=1 after the user says yes.");

  test("creates a test employee and lands on its page", async ({ browser }) => {
    test.setTimeout(120_000); // many picker clicks one after another: the 30 s default is too short
    const context = await browser.newContext({ reducedMotion: "no-preference" });
    try {
      const page = await context.newPage();
      await page.goto(WEB_URL + HIRE);
      await login(page, WEB_URL);
      await openPath(page, HIRE);

      // Errors from this page only: the sign-in before it is not counted.
      const errors: string[] = [];
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(message.text());
      });
      page.on("pageerror", (error) => errors.push(error.message));

      // Each tab is visited first: a hidden panel's controls cannot be filled (Playwright waits for them to be visible).
      for (const key of [BASIC, PERSONAL, SALARY, LOGIN]) {
        const tab = page.locator(`[data-tab-btn="${key}"]`);
        if ((await tab.count()) === 0) continue; // no salary tab without the salary right
        await tab.click();
        await expect(page.locator(`section[data-tab="${key}"]`)).toBeVisible();
        await fillRequired(page);
      }
      await page.getByRole("button", { name: "Ажилтан үүсгэх", exact: true }).click();

      // On success the React page moves to the new employee's page (`redirect` from the hire API). When it does not,
      // fail with the messages the page shows, so the cause is in the report.
      const moved = await page
        .waitForURL(/\/employees\/\d+\/$/, { timeout: 15_000 })
        .then(() => true)
        .catch(() => false);
      if (!moved) {
        const shown = await page.evaluate(() =>
          Array.from(document.querySelectorAll("#add-form .field-error, #add-form .text-red-700, main > p.bg-red-50")).map((el) => {
            const label = el.closest("label");
            const box = label?.querySelector("input, select, textarea") as HTMLInputElement | null;
            return `${(el.textContent ?? "").trim()} | ${box ? `${box.name}="${box.value}"` : "no box"}`;
          }),
        );
        const invalid = await page.evaluate(() =>
          Array.from(document.querySelectorAll("#add-form :invalid")).map((el) => {
            const box = el as HTMLInputElement;
            return `${el.tagName}[name=${box.name}] value="${box.value}" visible=${!!(el as HTMLElement).offsetParent}`;
          }),
        );
        throw new Error(
          `The hire did not move to the new employee page. Messages on the page: ${JSON.stringify(shown)}. ` +
            `Controls the browser still calls invalid: ${JSON.stringify(invalid)}`,
        );
      }
      await expect(page).toHaveURL(/\/employees\/\d+\/$/);
      await expect(page.getByRole("heading", { level: 1 }).first()).toContainText(GIVEN);
      expect(errors, "console errors on the React add page").toEqual([]);
    } finally {
      await context.close();
    }
  });
});
