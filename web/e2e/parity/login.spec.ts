import { expect, test, type Page } from "@playwright/test";
import { DJANGO_URL, WEB_URL, motionTokens, parity, type Step } from "./harness";

// Same text as app/templates/registration/login.html and web/src/routes/LoginPage.tsx.
const WRONG_CREDENTIALS = "Нэвтрэх нэр эсвэл нууц үг буруу байна.";
const LOGIN_BUTTON = "form button";

const focusUsername: Step = async (page: Page) => {
  await page.locator("#id_username").focus();
};

const typeWrong: Step = async (page: Page) => {
  await page.locator("#id_username").fill("parity_nobody");
  await page.locator("#id_password").fill("wrong");
};

const submit: Step = async (page: Page) => {
  // The React button stays disabled until the CSRF token arrives; click() waits for it.
  await page.locator(LOGIN_BUTTON).click();
  // The error line, whichever text it carries: repeated runs can trip the login throttle, and then both
  // versions show the lock message instead of WRONG_CREDENTIALS. Same element either way.
  await expect(page.locator("form p.text-red-600")).toBeVisible();
};

parity("login", "/login/", "/login", [focusUsername, typeWrong, submit]);

test.describe("login motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("login button transition is 0s under reduced motion, on both pages", async ({ page }) => {
    // Django's login button has no transition class, so the check is that both versions
    // report the same tokens, and that the React one is 0s.
    await page.goto(WEB_URL + "/login");
    await page.waitForLoadState("networkidle");
    const web = await motionTokens(page, LOGIN_BUTTON);
    expect(web.duration).toBe("0s");

    await page.goto(DJANGO_URL + "/login/");
    await page.waitForLoadState("networkidle");
    const django = await motionTokens(page, LOGIN_BUTTON);
    expect(django).toEqual(web);
  });
});
