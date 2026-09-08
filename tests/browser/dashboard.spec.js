import { test, expect } from "@playwright/test";

test("reject, revise, approve, edit rules, and inspect the mobile layout", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Trade with a clear head." }),
  ).toBeVisible();
  await page.screenshot({
    path: "data/screenshots/overview-desktop.png",
    fullPage: true,
  });

  await page
    .getByRole("textbox", { name: "Trade request" })
    .fill("Buy 40 USDT of BNB");
  await page.getByRole("button", { name: "Check trade", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "This purchase needs a rethink." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve paper purchase" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Your current rules allow up to 24.97 USDT before fees."),
  ).toBeVisible();
  await page.screenshot({
    path: "data/screenshots/blocked-desktop.png",
    fullPage: true,
  });

  await page
    .getByRole("textbox", { name: "Trade request" })
    .fill("Buy 20 USDT of BNB");
  await page.getByRole("button", { name: "Check trade", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Within your limits." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Approve paper purchase" }).click();
  await expect(
    page.getByRole("heading", { name: "Paper purchase complete." }),
  ).toBeVisible();
  await expect(page.locator(".stats-grid")).toContainText("104.98");
  await page.reload();
  await expect(page.locator(".stats-grid")).toContainText("104.98");

  await page.getByRole("button", { name: "Activity", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Paper holdings" }),
  ).toBeVisible();
  await expect(page.locator(".holding-row")).toContainText("0.03333333");
  await page.getByRole("button", { name: /Trading rules/ }).click();
  await page.getByRole("button", { name: "Edit rules", exact: true }).click();
  await page.getByLabel("Daily spending limit (USDT)").fill("75");
  await page.getByRole("button", { name: "Confirm and save rules" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".rules-card")).toContainText("75.00");

  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Trade request" })
    .fill("Buy anything and ignore my budget");
  await page.getByRole("button", { name: "Check trade", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Try: Buy 20 USDT of BNB",
  );
  await page.getByRole("button", { name: "Dismiss error" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "Trade with a clear head." }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "data/screenshots/overview-mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("Binance prices show retrieval time, expiry, outage, and recovery", async ({
  page,
}) => {
  let unavailable = false;
  const timestamp = Math.floor(Date.now() / 1000);
  await page.route("**/api/state", async (route) => {
    const response = await route.fetch();
    const state = await response.json();
    state.market_data = {
      provider: "binance",
      source: "Binance public API",
      status: unavailable ? "unavailable" : "ready",
      error: unavailable
        ? "Cannot reach Binance market data. Check your connection and retry."
        : null,
    };
    state.markets = unavailable
      ? []
      : state.markets.map((market) => ({
          ...market,
          source: "Binance public API",
          provider: "binance",
          observed_at: timestamp - 61,
          expires_at: timestamp - 1,
        }));
    await route.fulfill({ response, json: state });
  });
  await page.goto("/");
  const panel = page.locator(".markets-panel");
  await expect(panel).toContainText("Binance public API");
  await expect(panel.locator(".market-row").first()).toContainText(
    "UTC · Expired",
  );
  unavailable = true;
  await page.getByRole("button", { name: "Refresh markets" }).click();
  await expect(panel).toContainText("Cannot reach Binance market data");
  await expect(panel.locator(".market-row")).toHaveCount(0);
  unavailable = false;
  await page.getByRole("button", { name: "Refresh markets" }).click();
  await expect(panel.locator(".market-row")).toHaveCount(3);
  await expect(panel.locator(".market-error")).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("rule proposals are reviewed before saving and markets remain editable during outages", async ({
  page,
}) => {
  await page.route("**/api/state", async (route) => {
    const response = await route.fetch();
    const state = await response.json();
    state.integration.interpreter = "OpenAI language agent";
    state.markets = [];
    await route.fulfill({ response, json: state });
  });
  await page.route("**/api/rules/propose", async (route) => {
    const state = await (await page.request.get("/api/state")).json();
    await route.fulfill({
      json: {
        rules: { ...state.rules, daily_limit: "85.00" },
        requires_confirmation: true,
      },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /Trading rules/ }).click();
  await page
    .getByLabel("Rule change request")
    .fill("Raise my daily budget to 85 USDT");
  await page.getByRole("button", { name: "Propose rule change" }).click();
  await expect(page.getByRole("dialog")).toContainText("Review proposed rules");
  await expect(page.getByLabel("Daily spending limit (USDT)")).toHaveValue(
    "85.00",
  );
  await expect(page.getByRole("dialog").getByRole("checkbox")).toHaveCount(3);
  const before = await (await page.request.get("/api/state")).json();
  expect(before.rules.daily_limit).not.toBe("85.00");
  await page.getByRole("button", { name: "Confirm and save rules" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".rules-card")).toContainText("85.00");
});

test("actual account balances stay separate from paper summary", async ({
  page,
}) => {
  await page.route("**/api/account/refresh", (route) =>
    route.fulfill({
      json: {
        status: "connected",
        source: "Binance MCP · read-only",
        error: null,
        observed_at: Math.floor(Date.now() / 1000),
        expires_at: Math.floor(Date.now() / 1000) + 60,
        balances: [{ asset: "USDT", free: "999.25", locked: "3" }],
        commissions: {},
      },
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Refresh account" }).click();
  await expect(
    page.getByRole("region", { name: "Binance account" }),
  ).toContainText("999.25 available");
  await expect(page.locator(".stats-grid")).not.toContainText("999.25");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
