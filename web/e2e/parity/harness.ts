import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Page,
  type TestInfo,
} from "@playwright/test";
import pixelmatch from "pixelmatch";
import { PNG } from "pngjs";
import { mkdirSync, writeFileSync } from "node:fs";

export type Step = (page: Page) => Promise<void>;

// Both base URLs come from the environment. Django runs on its own port (the demo server may be 8001).
export const DJANGO_URL = process.env.DJANGO_URL ?? "http://127.0.0.1:8000";
export const WEB_URL = process.env.WEB_URL ?? "http://127.0.0.1:5173";

const VIEWPORTS = [
  { width: 1280, height: 800 },
  { width: 375, height: 812 },
] as const;
const THEMES = ["light", "dark"] as const;
type Theme = (typeof THEMES)[number];
type Viewport = (typeof VIEWPORTS)[number];

const DEFAULT_MAX_DIFF_PIXEL_RATIO = 0.01;
// pixelmatch per-pixel colour distance (0 to 1). Pixels below it count as equal.
const PIXEL_THRESHOLD = 0.1;

export type ParityOptions = {
  maxDiffPixelRatio?: number;
  // A CSS selector. When set, only that element is screenshotted (on both sides), not the whole page.
  clip?: string;
  // When true, each side signs in first (login helper, PARITY_USER / PARITY_PASSWORD) before the steps run.
  signIn?: boolean;
};

// Signs in on a login page: fills the form, submits, and waits until the page has left /login. Call it on a page
// that is already on the login page (Django's /login/ or the React /login route). The form ids are the same on both.
// `base` is the origin of that side, so the wait only ends on that origin.
export async function login(page: Page, base: string): Promise<void> {
  const username = process.env.PARITY_USER;
  const password = process.env.PARITY_PASSWORD;
  if (!username || !password) {
    throw new Error("Set PARITY_USER and PARITY_PASSWORD (a demo account) before running the parity specs.");
  }
  await page.waitForURL((url) => url.pathname.startsWith("/login"));
  await page.locator("#id_username").fill(username);
  await page.locator("#id_password").fill(password);
  // The React button stays disabled until the CSRF token arrives; click() waits for it.
  await page.locator("form button").click();
  await page.waitForURL((url) => url.origin === base && !url.pathname.startsWith("/login"));
}

// Call at the top level of a *.spec.ts file. It declares one test per viewport and theme.
// Each test runs the same steps on the Django page and on the React page, and compares
// the screenshots and the focused element id after every step.
export async function parity(
  name: string,
  djangoPath: string,
  webPath: string,
  steps: Step[],
  opts: ParityOptions = {},
): Promise<void> {
  const maxRatio = opts.maxDiffPixelRatio ?? DEFAULT_MAX_DIFF_PIXEL_RATIO;
  test.describe(name, () => {
    for (const viewport of VIEWPORTS) {
      for (const theme of THEMES) {
        test(`${viewport.width}px ${theme}`, async ({ browser }, testInfo) => {
          await runParity(browser, testInfo, djangoPath, webPath, steps, viewport, theme, { ...opts, maxDiffPixelRatio: maxRatio });
        });
      }
    }
  });
}

// Reads the computed transition of the first element that matches the selector.
export async function motionTokens(
  page: Page,
  selector: string,
): Promise<{ duration: string; easing: string }> {
  return page.locator(selector).first().evaluate((el) => {
    const style = getComputedStyle(el);
    return { duration: style.transitionDuration, easing: style.transitionTimingFunction };
  });
}

async function newSideContext(
  browser: Browser,
  viewport: Viewport,
  theme: Theme,
): Promise<BrowserContext> {
  const context = await browser.newContext({
    viewport,
    colorScheme: theme,
    reducedMotion: "no-preference",
  });
  // Both Django and the React page read localStorage "theme" before first paint.
  await context.addInitScript((value: string) => {
    try {
      localStorage.setItem("theme", value);
    } catch {
      // Storage blocked: the page falls back to the system setting (colorScheme above).
    }
  }, theme);
  return context;
}

async function runParity(
  browser: Browser,
  testInfo: TestInfo,
  djangoPath: string,
  webPath: string,
  steps: Step[],
  viewport: Viewport,
  theme: Theme,
  opts: ParityOptions & { maxDiffPixelRatio: number },
): Promise<void> {
  const maxRatio = opts.maxDiffPixelRatio;
  const clip = opts.clip;
  const djangoContext = await newSideContext(browser, viewport, theme);
  const webContext = await newSideContext(browser, viewport, theme);
  try {
    const djangoPage = await djangoContext.newPage();
    const webPage = await webContext.newPage();
    await djangoPage.goto(DJANGO_URL + djangoPath);
    await webPage.goto(WEB_URL + webPath);
    // Anonymous visits land on the login page (Django redirects, the React guard redirects). Sign in on both sides.
    if (opts.signIn) {
      await login(djangoPage, DJANGO_URL);
      await login(webPage, WEB_URL);
    }
    // The React page fetches its CSRF token after load; wait for it so both sides are settled.
    await djangoPage.waitForLoadState("networkidle");
    await webPage.waitForLoadState("networkidle");

    for (const [index, step] of steps.entries()) {
      await step(djangoPage);
      await step(webPage);
      await compare(testInfo, `step-${index + 1}`, djangoPage, webPage, maxRatio, clip);
    }
  } finally {
    await djangoContext.close();
    await webContext.close();
  }
}

async function activeId(page: Page): Promise<string> {
  return page.evaluate(() => document.activeElement?.id ?? "");
}

async function compare(
  testInfo: TestInfo,
  label: string,
  djangoPage: Page,
  webPage: Page,
  maxRatio: number,
  clip?: string,
): Promise<void> {
  // With a clip, only that element is shot (an element shot cannot be full page). Wait first until no request is
  // running on either side: the React loading bar (body[data-loading]) or an htmx request (.htmx-request), so the
  // 3px loading bar is never caught mid-flight.
  const shot = async (page: Page) => {
    // Idle twice, 300 ms apart: a refetch that starts on window focus can begin just after the first check.
    const idle = () =>
      page.waitForFunction(
        () => !document.body.hasAttribute("data-loading") && !document.querySelector(".htmx-request"),
        undefined,
        { timeout: 10_000 },
      );
    await idle();
    await page.waitForTimeout(300);
    await idle();
    return clip
      ? page.locator(clip).first().screenshot({ animations: "disabled", caret: "hide" })
      : page.screenshot({ fullPage: true, animations: "disabled", caret: "hide" });
  };
  const djangoShot = PNG.sync.read(await shot(djangoPage));
  const webShot = PNG.sync.read(await shot(webPage));
  const djangoFocus = await activeId(djangoPage);
  const webFocus = await activeId(webPage);

  const failures: string[] = [];
  let diffPng: PNG | null = null;
  let ratio = 0;

  if (djangoShot.width !== webShot.width || djangoShot.height !== webShot.height) {
    failures.push(
      `page size differs: django ${djangoShot.width}x${djangoShot.height}, web ${webShot.width}x${webShot.height}`,
    );
  } else {
    diffPng = new PNG({ width: djangoShot.width, height: djangoShot.height });
    const mismatched = pixelmatch(
      djangoShot.data,
      webShot.data,
      diffPng.data,
      djangoShot.width,
      djangoShot.height,
      { threshold: PIXEL_THRESHOLD },
    );
    ratio = mismatched / (djangoShot.width * djangoShot.height);
    if (ratio > maxRatio) {
      failures.push(`differing pixel ratio ${ratio.toFixed(5)} > ${maxRatio}`);
    }
  }

  if (djangoFocus !== webFocus) {
    failures.push(`focused element id differs: django "${djangoFocus}", web "${webFocus}"`);
  }

  if (failures.length === 0) return;

  // Keep the evidence on disk so the failure can be inspected.
  mkdirSync(testInfo.outputPath(), { recursive: true });
  const djangoFile = testInfo.outputPath(`${label}-django.png`);
  const webFile = testInfo.outputPath(`${label}-web.png`);
  writeFileSync(djangoFile, PNG.sync.write(djangoShot));
  writeFileSync(webFile, PNG.sync.write(webShot));
  let detail = `${label}: ${failures.join("; ")}. Screenshots: ${djangoFile} and ${webFile}`;
  if (diffPng) {
    const diffFile = testInfo.outputPath(`${label}-diff.png`);
    writeFileSync(diffFile, PNG.sync.write(diffPng));
    detail += `, diff: ${diffFile}`;
  }
  expect(failures.length, detail).toBe(0);
}
