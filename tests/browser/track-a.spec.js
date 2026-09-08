import { test, expect } from "@playwright/test";

test("advice, reports, downloads and publication schedule work together", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("button", { name: /Research|Advice/ }).first().click();
  await page.getByRole("button", { name: "Analyze", exact: true }).click();
  await expect(page.getByRole("heading", { name: /HOLD.*BNB/ })).toBeVisible();
  await page.getByRole("button", { name: "Reports", exact: true }).click();
  await page.getByRole("button", { name: "Daily current" }).click();
  await page.getByRole("button", { name: "View", exact: true }).first().click();
  await expect(page.getByText("Coverage: partial")).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "JSON", exact: true }).click();
  expect((await download).suggestedFilename()).toBe("portfolio-report.json");
  await page.getByRole("button", { name: "Schedule daily", exact: true }).click();
  await expect(page.getByText("daily · Enabled")).toBeVisible();
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(page.getByText("daily · Paused")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Reports", exact: true }).click();
  await expect(page.getByText("daily · Paused")).toBeVisible();
  expect(errors).toEqual([]);
});
