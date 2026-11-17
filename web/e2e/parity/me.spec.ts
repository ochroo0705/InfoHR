import { expect, test } from "@playwright/test";
import { bothSides, openPath, parity, type Step } from "./harness";

// My page («Миний хуудас»): Django employees/me.html against MePage. Same path on both sides. The demo user is `hr`,
// who has an employee record (seed_demo links the `hr` login to Оюунчимэг), so no PARITY_ME_* variables are needed.
const PATH = "/me/";

const openMe: Step = (page) => openPath(page, PATH);

// Full-page screenshots: light and dark, 1280 px and 375 px (the harness runs all four).
parity("me", PATH, PATH, [openMe], { signIn: true });

test.describe("me steps", () => {
  test.use({ reducedMotion: "no-preference" });

  test("the section headings are the same text list on both sides", async ({ browser }) => {
    const sides = await bothSides(browser, PATH, async (page) => {
      const headings = await page.locator("main h2").allTextContents();
      return headings.map((text) => text.replace(/\s+/g, " ").trim());
    });
    expect(sides.web).toEqual(sides.django);
    // The headings that me.html always renders, whatever the data.
    expect(sides.django).toEqual(
      expect.arrayContaining(["Ээлжийн амралт", "Миний хүсэлтүүд", "Энэ оны бүртгэгдсэн чөлөө"]),
    );
  });
});
