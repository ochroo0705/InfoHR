import { expect, request, test, type Page } from "@playwright/test";
import { DJANGO_URL, openPath, parity, type Step } from "./harness";

// Order detail pop-up of the employee page (step 3d-2): Django `_order_detail.html` against OrderDetailModal, and the two
// pop-ups its footer opens, the order cancel («Тушаал цуцлах») and the on-screen signing («Гарын үсэг зурах»). Nothing is
// submitted: each scenario only opens the pop-up and compares it.
//
// The detail opens from a clickable row of «Ажлын түүх» (`tr.cursor-pointer`: a history row that has an order). Болд (the
// seed_demo `bold` login) has a hire order, so his first clickable history row is used. The pk is read from the
// staff-list report, as events.spec.ts and employee.spec.ts do.
//
// Which footer buttons exist depends on the order (state, scan, rights of the `hr` user), so the cancel and sign scenarios
// are skipped with a reason when Болд's page shows no such button. The «Бусад тушаал» rows added by seed_demo
// (`_demo_scenarios._other_orders`: two older hire orders Д/101 and Д/102) are not detail rows: a click on them opens the edit
// pop-up, which events.spec.ts covers.
//
// Known difference to expect: the close button reads «Хаах» on the React side and «Хаах (Esc)» on Django.

const MODAL = ".fixed.inset-0.z-50";
const STAFF_LIST = "/reports/staff-list/";
const LANDING = "/employees/today/";
const ASSISTANT_FAB_HIDDEN = "[data-assistant-fab]{visibility:hidden !important}";
const DESKTOP = [{ width: 1280, height: 800 }];
const HISTORY_ROW = "tr.cursor-pointer";
const CANCEL_ORDER = "Тушаал цуцлах";
const SIGN = "Гарын үсэг зурах";

let boldPk = 0;

test.beforeAll(async () => {
  boldPk = await findPk("Болд");
});

// Signs in to Django with the login form, then reads the staff-list report: the row that names the employee holds the link.
async function findPk(name: string): Promise<number> {
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
    const report = await (await api.get(`${STAFF_LIST}?q=${encodeURIComponent(name)}`)).text();
    for (const row of report.split(/<tr[\s>]/)) {
      if (!row.includes(name)) continue;
      const match = row.match(/href="\/employees\/(\d+)\/"/);
      if (match) return Number(match[1]);
    }
    throw new Error(`No staff-list row names "${name}" (is the demo data seeded?).`);
  } finally {
    await api.dispose();
  }
}

// Opens Болд's page and hides the assistant button (Django only; it is not part of the compared screen).
async function openBold(page: Page): Promise<void> {
  await openPath(page, `/employees/${boldPk}/`);
  await page.addStyleTag({ content: ASSISTANT_FAB_HIDDEN });
}

// Step: a click on the first clickable history row opens the order detail pop-up.
const openDetail: Step = async (page) => {
  await openBold(page);
  const rows = page.locator(HISTORY_ROW);
  if ((await rows.count()) === 0) {
    test.skip(true, "Болд's work history has no clickable row (no change row with an order).");
    return;
  }
  await rows.first().click();
  await expect(page.locator(MODAL)).toBeVisible();
  await expect(page.locator(`${MODAL} h3`).first()).toBeVisible();
};

// Opens the detail of the first clickable history row, then a footer button by its title. Skipped when that order has no
// such button (the footer depends on the order's state and the user's rights).
function openFromFooter(title: string, what: string): Step {
  return async (page) => {
    await openDetail(page);
    const button = page.locator(`${MODAL} [title="${title}"], ${MODAL} button:has-text("${title}")`).first();
    if ((await button.count()) === 0) {
      test.skip(true, `The first history row's order has no «${title}» button (${what}).`);
      return;
    }
    await button.click();
    await expect(page.locator(`${MODAL} form`)).toBeVisible();
  };
}

const openCancelOrder = openFromFooter(CANCEL_ORDER, "it is cancelled, or the user may not cancel it");
const openSign = openFromFooter(SIGN, "it is signed already, cancelled, or the user has no salary right");

parity("order detail pop-up from a history row", LANDING, LANDING, [openDetail], {
  signIn: true,
  clip: MODAL,
  viewports: DESKTOP,
});

parity("order cancel pop-up from the detail footer", LANDING, LANDING, [openCancelOrder], {
  signIn: true,
  clip: MODAL,
  viewports: DESKTOP,
});

parity("order sign pop-up from the detail footer", LANDING, LANDING, [openSign], {
  signIn: true,
  clip: MODAL,
  viewports: DESKTOP,
});
