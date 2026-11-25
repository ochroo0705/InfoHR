import { expect, test, type Page } from "@playwright/test";
import { openPath, parity, type Step } from "./harness";

// Reports, step 5a, held-out check: reports that no 5a task names, to show that a registry report needs no React change.
// Same address on both sides; run as `hr`; read only. Chosen to use other filter controls (employee, leave type, period,
// change kind, department), a person report with money, and a grouped report with data.
//   /reports/leave-balance/        filters as_of, department, leave_type, employee
//   /reports/household-income/     person report, group options, money columns (salary-gated ones are not shown to hr)
//   /reports/movements/            filters branch, department, change, period
//   /reports/orders/               filters order_type, department, period
//   /reports/staff-list/?group=department   grouped with 14 groups and 193 rows
// Known differences: EXPECTED_DIFFS.md «Step 5a (reports)».

test.setTimeout(60_000);

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

const ADDRESSES: [string, string][] = [
  ["leave balance", "/reports/leave-balance/"],
  ["household income", "/reports/household-income/"],
  ["movements", "/reports/movements/"],
  ["orders", "/reports/orders/"],
  ["staff list grouped by department", "/reports/staff-list/?group=department"],
];

for (const [name, path] of ADDRESSES) {
  parity(`reports held-out: ${name}`, path, path, [visit(path)], { signIn: true });
}
