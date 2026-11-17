import { expect, test } from "@playwright/test";
import { bothSides, openPath, parity, type Step } from "./harness";

// Company figures («Компанийн байдал»): Django employees/company.html against CompanyPage, at /employees/company/.
// Same path on both sides; the demo user is `hr`.
const PATH = "/employees/company/";

// The date beside the title (Django: the span after h1, React: the same span). It differs only at midnight.
const DATE_MASKS = ["h1 + span.ml-auto"];

const openCompany: Step = (page) => openPath(page, PATH);

// Full-page screenshots: light and dark, 1280 px and 375 px (the harness runs all four).
parity("company page", PATH, PATH, [openCompany], { signIn: true, mask: DATE_MASKS });

test.describe("company steps", () => {
  test.use({ reducedMotion: "no-preference" });

  test("the title and the section headings are the same text list on both sides", async ({ browser }) => {
    const sides = await bothSides(browser, PATH, async (page) => {
      const headings = await page.locator("main h1, main h2").allTextContents();
      return headings.map((text) => text.replace(/\s+/g, " ").trim());
    });
    expect(sides.web).toEqual(sides.django);
    // The title that company.html always renders, whatever the data.
    expect(sides.django).toEqual(expect.arrayContaining(["Компанийн байдал"]));
  });
});
