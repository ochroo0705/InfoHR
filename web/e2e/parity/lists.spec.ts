import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Lists screens (step 4b): /lists/ (index and search), /lists/<slug>/ (one list, its add and edit pop-up) and /lists/meaning/.
// Django lists/index.html, list.html, meaning.html, _entry_form.html against ListsIndexPage, ListPage, EntryFormModal and
// MeaningPage. Same path on both sides; run as `hr` (holds lists.manage_lists). Read-only: the pop-ups are opened and closed,
// nothing is saved (the demo DB is shared; writes are covered by the API and Vitest tests).
//
// Known differences are in EXPECTED_DIFFS.md, section «Step 4b (lists)».

test.setTimeout(60_000);

const MODAL = ".fixed.inset-0.z-50";

// Waits until the page has its heading and the network is quiet.
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("h1").first()).toBeVisible();
}

function visit(path: string): Step {
  return async (page) => {
    await openPath(page, path);
    await settle(page);
  };
}

// Step: the «Нэмэх» button opens the add pop-up.
const openAdd: Step = async (page) => {
  await page.getByRole("button", { name: "Нэмэх" }).first().click();
  await expect(page.locator(MODAL)).toBeVisible();
  await page.waitForLoadState("networkidle");
};

// Step: a click on the first row opens the edit pop-up (skips when the list is empty).
const openEdit: Step = async (page) => {
  const row = page.locator("tbody tr").first();
  if ((await row.locator("td").count()) === 0 || (await row.innerText()).includes("бүртгэгдээгүй")) {
    test.skip(true, "The list is empty, so there is no row to open.");
    return;
  }
  await row.locator("td").first().click();
  await expect(page.locator(MODAL)).toBeVisible();
  await page.waitForLoadState("networkidle");
};

const INDEX = "/lists/";
const SEARCH_LIST = "/lists/?q=%D0%B1%D0%B0%D0%BD%D0%BA"; // «банк»: matches a list name
const SEARCH_ENTRY = "/lists/?q=%D0%93%D1%8D%D1%80%D0%BB%D1%8D%D1%81%D1%8D%D0%BD"; // «Гэрлэсэн»: matches an entry
const SEARCH_NONE = "/lists/?q=zzzzzz";
const BANK = "/lists/bank/";
const SIZES = "/lists/sizes/";
const DISTRICT = "/lists/district/";
const MEANING = "/lists/meaning/";

parity("lists: index", INDEX, INDEX, [visit(INDEX)], { signIn: true });
parity("lists: search by list name", SEARCH_LIST, SEARCH_LIST, [visit(SEARCH_LIST)], { signIn: true });
parity("lists: search by entry name", SEARCH_ENTRY, SEARCH_ENTRY, [visit(SEARCH_ENTRY)], { signIn: true });
parity("lists: search finds nothing", SEARCH_NONE, SEARCH_NONE, [visit(SEARCH_NONE)], { signIn: true });
parity("lists: one list", BANK, BANK, [visit(BANK)], { signIn: true });
parity("lists: list with choice columns", SIZES, SIZES, [visit(SIZES)], { signIn: true });
parity("lists: list with a parent", DISTRICT, DISTRICT, [visit(DISTRICT)], { signIn: true });
parity("lists: add pop-up", BANK, BANK, [visit(BANK), openAdd], { signIn: true });
parity("lists: add pop-up with a parent select", DISTRICT, DISTRICT, [visit(DISTRICT), openAdd], { signIn: true });
parity("lists: edit pop-up", BANK, BANK, [visit(BANK), openEdit], { signIn: true });
parity("lists: meaning page", MEANING, MEANING, [visit(MEANING)], { signIn: true });
