import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { once } from "node:events";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";

const output = resolve("data/demo");
await mkdir(output, { recursive: true });
const server = spawn(
  "python",
  [
    "-m",
    "backend.server",
    "--port",
    "8022",
    "--database",
    `${output}/paper-${randomUUID()}.sqlite3`,
  ],
  { windowsHide: true, stdio: "ignore" },
);
let browser, encoder;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
try {
  let ready = false;
  for (let attempt = 0; attempt < 60; attempt++) {
    if (server.exitCode !== null)
      throw new Error("Demo server exited before startup.");
    try {
      ready = (await fetch("http://127.0.0.1:8022/api/health")).ok;
    } catch {}
    if (ready) break;
    await sleep(250);
  }
  if (!ready) throw new Error("Demo server did not start.");
  browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1100 },
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:8022");
  await page
    .getByRole("heading", { name: "Trade with a clear head." })
    .waitFor();
  await page.evaluate(() => {
    const caption = document.createElement("div");
    caption.id = "demo-caption";
    caption.style.cssText =
      "position:fixed;bottom:0;left:0;right:0;z-index:9999;background:#183a30;color:white;padding:18px 28px;font:20px/1.5 Arial;box-shadow:0 -4px 20px #0002";
    document.body.append(caption);
  });
  async function caption(text) {
    await page.locator("#demo-caption").evaluate((element, value) => {
      element.textContent =
        value + "  |  Fixture demo · paper funds · no model/account connected";
    }, text);
  }
  await caption(
    "TradeCheck: your rules, every trade. Start with 125 USDT and protect 100.",
  );
  const destination = `${output}/tradecheck-paper-demo.mp4`;
  encoder = spawn(
    "ffmpeg",
    [
      "-y",
      "-loglevel",
      "error",
      "-f",
      "image2pipe",
      "-framerate",
      "2",
      "-vcodec",
      "png",
      "-i",
      "pipe:0",
      "-an",
      "-c:v",
      "libx264",
      "-preset",
      "veryfast",
      "-pix_fmt",
      "yuv420p",
      "-r",
      "24",
      "-t",
      "90",
      "-movflags",
      "+faststart",
      destination,
    ],
    { windowsHide: true, stdio: ["pipe", "ignore", "pipe"] },
  );
  let encoderError = "";
  encoder.stderr.on("data", (chunk) => {
    encoderError += chunk;
  });
  const finished = once(encoder, "close");
  const start = Date.now();
  for (let frame = 0; frame < 180; frame++) {
    if (frame === 20) {
      await page.getByLabel("Trade request").fill("Buy 40 USDT of BNB");
      await caption(
        "Request 40 USDT of BNB. Every request is checked on the server.",
      );
    }
    if (frame === 30) {
      await page
        .getByRole("button", { name: "Check trade", exact: true })
        .click();
      await page
        .getByRole("heading", { name: "This purchase needs a rethink." })
        .waitFor();
      await page.locator(".decision").scrollIntoViewIfNeeded();
      await caption(
        "Blocked: this purchase would breach the protected 100-USDT reserve.",
      );
    }
    if (frame === 64) {
      await page.getByLabel("Trade request").fill("Buy 20 USDT of BNB");
      await page.getByLabel("Trade request").scrollIntoViewIfNeeded();
      await caption(
        "Revise the request to 20 USDT. The saved rules stay in force.",
      );
    }
    if (frame === 78) {
      await page
        .getByRole("button", { name: "Check trade", exact: true })
        .click();
      await page
        .getByRole("heading", { name: "Within your limits." })
        .waitFor();
      await page.locator(".decision").scrollIntoViewIfNeeded();
      await caption(
        "All checks pass. Review quantity, simulated fee, and the remaining balance.",
      );
    }
    if (frame === 108) {
      await page
        .getByRole("button", { name: "Approve paper purchase" })
        .click();
      await page
        .getByRole("heading", { name: "Paper purchase complete." })
        .waitFor();
      await page.locator(".receipt").scrollIntoViewIfNeeded();
      await caption(
        "Explicit approval completes one paper purchase. No real order is submitted.",
      );
    }
    if (frame === 132) {
      await page.getByRole("button", { name: "Activity", exact: true }).click();
      await page.evaluate(() => window.scrollTo(0, 0));
      await caption(
        "Activity records the blocked request, revised preview, and completed purchase.",
      );
    }
    if (frame === 154) {
      await page.getByRole("button", { name: /Trading rules/ }).click();
      await page
        .getByRole("button", { name: "Edit rules", exact: true })
        .click();
      await caption(
        "Rules belong to you. Any saved change invalidates pending previews.",
      );
    }
    if (frame === 172) {
      await page.getByRole("button", { name: "Close rules" }).click();
      await caption(
        "Implemented and tested locally. Model activation and authorized MCP setup remain.",
      );
    }
    const png = await page.screenshot({ animations: "disabled" });
    if (!encoder.stdin.write(png)) await once(encoder.stdin, "drain");
    if (frame % 40 === 0) console.log(`Recorded ${frame / 2}/90 seconds`);
    await sleep(Math.max(0, start + (frame + 1) * 500 - Date.now()));
  }
  encoder.stdin.end();
  const [exitCode] = await finished;
  if (exitCode !== 0) throw new Error(encoderError || "Video encoder failed.");
  if (errors.length) throw new Error(errors.join("\n"));
  await writeFile(
    `${output}/recording.json`,
    JSON.stringify(
      {
        file: destination,
        duration_seconds: 90,
        mode: "paper",
        prices: "fixtures",
        interpreter: "strict parser",
        account_connected: false,
        recorded_at: new Date().toISOString(),
      },
      null,
      2,
    ),
  );
  console.log(`Saved ${destination}`);
} finally {
  if (browser) await browser.close();
  if (encoder && encoder.exitCode === null) encoder.kill();
  server.kill();
}
