import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const BLOCKING_IMPACTS = new Set(["critical", "serious"]);

test("analyzer route has no blocking WCAG accessibility violations", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("dialog", { name: "Administrator tools" }),
  ).toBeVisible();

  const audit = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  const blockingViolations = audit.violations.filter(({ impact }) =>
    impact === null ? false : BLOCKING_IMPACTS.has(impact),
  );

  expect(
    blockingViolations,
    JSON.stringify(blockingViolations, null, 2),
  ).toEqual([]);
});
