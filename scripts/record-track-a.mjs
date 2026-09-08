import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { once } from 'node:events';
import { randomUUID } from 'node:crypto';
import { resolve } from 'node:path';

const output = resolve('data/demo', `track-a-${new Date().toISOString().replaceAll(':', '-')}`);
await mkdir(output, { recursive: true });
const base = 'http://127.0.0.1:8023';
const server = spawn('python', ['-m', 'backend.server', '--port', '8023', '--database', `${output}/paper-${randomUUID()}.sqlite3`,
  '--market-data', 'binance', '--agentos', '--news-config', 'news-config.example.json'], { windowsHide: true, stdio: 'ignore' });
let browser, encoder;
const scenes = [];
const errors = [];
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
try {
  for (let attempt = 0; ; attempt++) {
    try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {}
    if (attempt >= 80 || server.exitCode !== null) throw new Error('Demo server did not start.');
    await pause(250);
  }
  browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
  page.setDefaultTimeout(90000);
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(base);
  await page.getByRole('heading', { name: 'Trade with a clear head.' }).waitFor();
  await page.evaluate(() => {
    const caption = document.createElement('div');
    caption.id = 'demo-caption';
    caption.style.cssText = 'position:fixed;bottom:0;left:0;right:0;z-index:99999;background:#123c32;color:white;padding:20px 32px;font:22px/1.45 Arial;box-shadow:0 -4px 20px #0003;min-height:95px';
    document.body.append(caption);
    document.body.style.paddingBottom = '145px';
  });
  const destination = `${output}/tradecheck-track-a-demo.mp4`;
  encoder = spawn('ffmpeg', ['-loglevel', 'error', '-f', 'image2pipe', '-framerate', '2', '-vcodec', 'png', '-i', 'pipe:0',
    '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-r', '24', '-movflags', '+faststart', destination],
    { windowsHide: true, stdio: ['pipe', 'ignore', 'pipe'] });
  let encoderError = '';
  encoder.stderr.on('data', (chunk) => encoderError += chunk);
  const finished = once(encoder, 'close');
  async function scene(title, detail, seconds = 10) {
    await page.locator('#demo-caption').evaluate((el, values) => {
      el.replaceChildren();
      const strong = document.createElement('strong'); strong.textContent = values[0];
      const line = document.createElement('div'); line.textContent = values[1]; line.style.fontSize = '17px';
      el.append(strong, line);
    }, [title, detail]);
    await pause(250);
    const png = await page.screenshot({ animations: 'disabled' });
    const file = `${String(scenes.length + 1).padStart(2, '0')}.png`;
    await writeFile(`${output}/${file}`, png);
    scenes.push({ title, detail, seconds, screenshot: file });
    for (let frame = 0; frame < seconds * 2; frame++) {
      if (!encoder.stdin.write(png)) await once(encoder.stdin, 'drain');
    }
    console.log(`Captured scene ${scenes.length}: ${title}`);
  }
  await scene('TradeCheck — portfolio decisions within your rules', 'Track A prototype | Live data · simulated funds · human approval');
  await page.locator('.markets-panel').scrollIntoViewIfNeeded();
  await scene('Live Binance markets. A separate 125-USDT paper wallet.', 'Protect a 100-USDT reserve and enforce a daily spending limit. No real account balance is shown.');
  await page.getByRole('button', { name: /Research|Advice/ }).first().click();
  const adviceResponse = page.waitForResponse((r) => r.url().endsWith('/api/advice') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Analyze', exact: true }).click();
  const response = await adviceResponse;
  const advice = await response.json();
  if (!response.ok) throw new Error(advice.error || 'Analysis failed.');
  const agentos = advice.evidence.find((e) => e.type === 'agentos_market' && e.status === 'ready');
  const news = advice.evidence.filter((e) => e.type === 'news');
  if (!agentos || !news.length) throw new Error('Recording requires live Agent OS and news evidence.');
  await page.getByRole('heading', { name: /HOLD.*BNB/ }).waitFor();
  await page.getByRole('heading', { name: /HOLD.*BNB/ }).scrollIntoViewIfNeeded();
  await scene('Advice interface: a clearly labeled sample assessment', 'The HOLD response is a development fixture. A live model/key still needs configuring; this is not live AI reasoning.');
  await page.getByText('Binance Agent OS · Spot', { exact: false }).evaluate((el) => el.scrollIntoView({ block: 'center' }));
  await scene('Real Agent OS evidence, retrieved through the Codex host', 'A pinned public Spot read supplies BNB/USDT data. The adapter cannot select order or withdrawal tools.');
  await page.getByRole('link', { name: news[0].headline, exact: true }).evaluate((el) => el.scrollIntoView({ block: 'center' }));
  await scene('Current news with visible sources and timestamps', 'Live RSS articles are filtered for asset relevance and freshness. News is input data, never execution authority.');
  await page.getByRole('button', { name: 'Overview', exact: true }).click();
  await page.getByLabel('Trade request').fill('Buy 40 USDT of BNB');
  await page.getByRole('button', { name: 'Check trade', exact: true }).click();
  await page.getByRole('heading', { name: 'This purchase needs a rethink.' }).waitFor();
  await page.locator('.decision').scrollIntoViewIfNeeded();
  await scene('Blocked: this request would breach the reserve', 'The backend checks the live-price paper proposal against saved rules. Advice cannot override those rules.');
  await page.getByLabel('Trade request').fill('Buy 20 USDT of BNB');
  await page.getByRole('button', { name: 'Check trade', exact: true }).click();
  await page.getByRole('heading', { name: 'Within your limits.' }).waitFor();
  await page.locator('.decision').scrollIntoViewIfNeeded();
  await scene('Revised proposal: review before approving', 'Inspect quantity, exchange-filter estimates, simulated fees, and the remaining cash balance.');
  await page.getByRole('button', { name: 'Approve paper purchase', exact: true }).click();
  await page.getByRole('heading', { name: 'Paper purchase complete.' }).waitFor();
  await page.locator('.receipt').scrollIntoViewIfNeeded();
  await scene('Explicit approval completes one paper purchase', 'The fill is atomic and repeat approval cannot duplicate it. No real order or transfer is submitted.');
  await page.getByRole('button', { name: 'Activity', exact: true }).click();
  await page.getByRole('heading', { name: 'Paper holdings' }).scrollIntoViewIfNeeded();
  await scene('An audit trail connects requests to portfolio changes', 'Recorded checks and fills support the paper ledger, holdings, fee totals, and weighted-average cost basis.');
  await page.getByRole('button', { name: 'Reports', exact: true }).click();
  await page.getByRole('button', { name: 'Daily current', exact: true }).click();
  await page.getByRole('button', { name: 'View', exact: true }).first().click();
  await page.getByText('Coverage: partial', { exact: true }).evaluate((el) => el.scrollIntoView({ block: 'center' }));
  await scene('Daily portfolio reports disclose incomplete history', 'Factual accounting, downloadable HTML/Markdown/JSON. Missing historical values are not replaced with current prices.');
  await page.getByRole('button', { name: 'Monthly current', exact: true }).click();
  await page.getByRole('button', { name: 'Schedule monthly', exact: true }).click();
  await page.getByText('monthly · Enabled', { exact: true }).waitFor();
  await page.getByRole('heading', { name: 'Private publication schedule' }).evaluate((el) => el.scrollIntoView({ block: 'center' }));
  await scene('Monthly reporting with a persistent private schedule', 'Reports publish to this local dashboard while the backend runs. No public or email delivery is configured.');
  await scene('TradeCheck — evidence, review, approval, accountability', '95 backend tests + 5 browser workflows passed | Live model activation remains | github.com/PJ-syst/tradecheck');
  encoder.stdin.end();
  const [exitCode] = await finished;
  if (exitCode !== 0) throw new Error(encoderError || 'Video encoder failed.');
  if (errors.length) throw new Error(errors.join('\n'));
  await writeFile(`${output}/recording.json`, JSON.stringify({ file: destination, recorded_at: new Date().toISOString(),
    duration_seconds: scenes.reduce((sum, scene) => sum + scene.seconds, 0), mode: 'paper', advice: 'fixture; no live model configured',
    prices: 'live Binance public API', agentos, news_items: news.length, scenes }, null, 2));
  await writeFile(`${output}/README.txt`, 'TradeCheck Track A demo\n120-second captioned, silent walkthrough.\nLive Agent OS Spot evidence and RSS news; simulated funds and fixture advice.\nThis video does not demonstrate live model reasoning. Configure a model and replace that segment before claiming a complete AI-agent submission.\n');
  console.log(`SAVED ${destination}`);
} finally {
  if (browser) await browser.close();
  if (encoder && encoder.exitCode === null) encoder.kill();
  server.kill();
}
