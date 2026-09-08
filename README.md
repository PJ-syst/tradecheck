# TradeCheck

Your rules. Every trade.

A local prototype for an agent that previews Spot purchases, checks budgets and reserves, and asks for approval. Built for the Binance Agent OS hackathon concept.

**Current status:** tested paper-trading application with Binance public prices and exchange-filter estimates, an optional OpenAI request interpreter, reviewable language-based rule proposals, and a configurable read-only MCP account adapter. Public Binance data was tested live. Model and account paths were tested with synthetic responses; neither is activated in this workspace. The default request field still uses a strict parser. A completed Agent OS integration must not be claimed until account authorization, actual tool-schema mapping, and end-to-end verification are complete.

## Run

Requires Python 3.10+ and Node.js 20.19+ (tested environment: Python 3.14 and Node 24). From this folder:

```powershell
npm install
npm run build
python -m backend.server
```

Open **http://127.0.0.1:8000**. The Python process serves the built frontend and API. Stop with Ctrl+C.

For frontend development, keep the backend running and run `npm run dev` in another terminal. Open http://127.0.0.1:5173; Vite forwards API requests to port 8000.

### Use Binance prices with a paper wallet

```powershell
python -m backend.server --market-data binance --database data/binance-paper.sqlite3
```

This reads BNB/USDT, BTC/USDT, and ETH/USDT prices from Binance's [public market-data service](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md), using the documented [symbol price ticker](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#symbol-price-ticker). No API key or account connection is required. This example uses a separate paper database; all balances and fills remain simulated.

The market panel shows the source and UTC retrieval time. Click **Refresh markets** to update it. Requests share a 15-second cache; prices expire 60 seconds after retrieval begins. Failures are visible and block new previews without substituting fixture prices. Retries back off for 30 seconds, or at least 120 seconds after rate limiting, respecting a longer `Retry-After` value.

A paper approval uses the exact price stored in its preview, even if a later market refresh returns a different price. The preview cannot outlive its quote or cached filters. Changing the server's price source invalidates pending previews. Old live-price previews created before filter support must be checked again.

Binance mode fetches `exchangeInfo` and, when needed, `avgPrice`. It rounds quantity down to an increment satisfying both quantity filters, checks market status, quantity bounds, applicable notional bounds, and paper position/order counters, and blocks unknown filters. The rounded purchase cost is charged, rounded up to a USDT cent, with the simulated fee; the unspent request amount is shown. Metadata is cached for five minutes. See the [official filter definitions](https://github.com/binance/binance-spot-api-docs/blob/master/filters.md).

These are paper estimates, not executable offers. Exchange reference-price overrides, order-book liquidity, slippage, actual account order counters/asset limits, and fee-asset deductions are not execution-verified. Public average-price windows must match the applicable filter. The server refuses a preview if required metadata cannot be retrieved.

Omit `--market-data` (or use `--market-data fixture`) for the offline demo below.

### Activate the language agent

On Windows, run `python -m backend.setup` to enter a model ID and a hidden API key, verify one interpretation, and save the key encrypted for your Windows user under ignored `data/`. Then run `pwsh -File scripts/start-configured.ps1`. Binance browser sign-in is available with `python -m backend.oauth --login` once the public client metadata is deployed. Do not paste credentials into chat or source files.

Configure a Responses-compatible OpenAI model in your server terminal. PowerShell 7 can prompt for a key without putting its literal value in command history:

```powershell
$env:OPENAI_API_KEY = Read-Host 'OpenAI API key' -MaskInput
$env:OPENAI_MODEL = Read-Host 'OpenAI model ID with structured output support'
python -m backend.server --interpreter openai --market-data binance
```

The key stays in the server environment; it is never sent to the browser. `.env` files are not loaded automatically. Close the terminal or remove the environment variable after use. Model calls send the request text and, for rule proposals, the current paper rules. They do not send account balances, credentials, or activity history. API usage is billed by your provider.

The adapter uses [Responses structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), independently validates returned values, and does not grant any model tools. Try `Please spend 20 USDT on BNB`. Review the interpreted symbol, quantity, and amount before approving. Ambiguous inputs should request clarification. Invalid/refused/incomplete outputs fail visibly without a parser fallback.

In **Trading rules**, describe a change, click **Propose rule change**, review the values, then **Confirm and save rules**. A proposal alone changes nothing. Saving a stale rule draft is rejected to avoid overwriting newer rules. Without model configuration, use the strict parser and manual rule editor.

### Configure a read-only Binance account

See [MCP setup and remaining activation work](docs/MCP_SETUP.md). The adapter accepts only fixed, reviewed tool mappings with pinned schemas and read-only annotations. Model outputs and browser requests cannot select MCP tools or supply their arguments.

The account panel fetches actual balances and commission components only when you click **Refresh account**. It keeps results in memory, marks snapshots stale after 60 seconds, and clears failed results. Account data does not fund the paper wallet or change its simulated fees. No order, transfer, or withdrawal endpoint is implemented.

## Try the demo

1. The initial paper wallet has 125.00 USDT. Rules: 50.00 USDT daily budget and 100.00 USDT reserve.
2. Enter `Buy 40 USDT of BNB` and click **Check trade**. The reserve check rejects it: 84.96 USDT would remain after the simulated fee.
3. Enter `Buy 20 USDT of BNB` and check again. All checks pass; total debit is 20.02 USDT.
4. Click **Approve paper purchase**. Balance becomes 104.98 USDT and the purchase appears in Activity.
5. Edit rules to try other budgets or disable markets. Saving rules invalidates existing previews.

Data persists in `data/tradecheck.sqlite3`. For a separate fresh demonstration without deleting existing activity, stop the server and run `python -m backend.server --database data/another-demo.sqlite3`.

## Implementation

- `backend/engine.py`: Decimal calculations, validation, spending limits, preview expiration, atomic and idempotent approvals, SQLite wallet and event storage.
- `backend/market.py`: fixture and Binance public-price providers, validated responses, shared cache, and failure backoff.
- `backend/filters.py`: exchange metadata validation, increment rounding, and paper MARKET-buy checks.
- `backend/interpreter.py`: optional OpenAI structured interpretation and rule proposals without mutation capabilities.
- `backend/mcp.py`: discovery and configurable read-only account adapter; actual authorization and tool mapping still required.
- `backend/server.py`: loopback-only HTTP service, same-origin mutation checks, request token, JSON API, static frontend hosting.
- `src/main.jsx`: React dashboard, preview and approval interaction, rule editor, activity and holdings.
- `src/style.css`: responsive interface with desktop and mobile layouts.
- `tests/`: policy, concurrency, persistence, and HTTP tests using temporary databases.
- `PLAN.md`: remaining integration, language-agent, and submission milestones.

## Prototype assumptions

- Purchases only: BNB/USDT, BTC/USDT, ETH/USDT.
- Default fixture prices: BNB 600, BTC 90,000, ETH 3,000 USDT. These are illustrative, not current market quotes. Select `--market-data binance` for public prices.
- Simulated fee: 0.1%, charged in USDT and rounded upward to a cent. Real Binance fee tiers and fee assets differ.
- Fixture minimum order: 5 USDT; fixture quantity is rounded down to eight decimals, and fixture fills debit the requested amount plus fee. Binance mode uses the filter estimates and rounded purchase cost described above.
- Daily budget includes fees and resets at midnight UTC. A preview expires after at most 120 seconds (also capped by quote expiry for Binance prices) and cannot cross the UTC day boundary.
- A preview never reserves or spends funds. Approval rechecks rules and balance inside a SQLite write transaction. Repeated approval returns the existing receipt.
- One local user; no production authentication or deployment hardening. Keep the server bound to loopback.
- Google Fonts is optional; system sans-serif fallback works offline.

## Verify

```powershell
python -m unittest discover -s tests -v
npm run build
npm run test:browser
```

The browser tests use installed Microsoft Edge in headless mode, a temporary paper database, and port 8011. They do not change the wallet used by your app on port 8000. The test-only server has a private shutdown hook to avoid Windows process cleanup hangs; the production server has no such endpoint. Screenshots are saved under `data/screenshots/`.

Verification: 57 backend/API tests and four browser workflows passed. Automated tests use synthetic market, model, and account responses and never contact a trading account. They verify enforcement under injected/malformed model outputs, not the semantic accuracy of a live model. A public Binance BNB price/filter/average-price smoke check passed on September 8, 2026. Live model behavior and authenticated MCP schemas/results remain unverified.

## Demo and submission materials

`npm run demo:record` records a 90-second captioned browser demonstration to `data/demo/tradecheck-paper-demo.mp4`. It requires installed Edge and `ffmpeg` on PATH, uses a separate paper database on port 8022, and shows the strict parser with fixture prices. It does not imply a connected model or account. See [submission preparation](docs/SUBMISSION.md) for the draft, deadline, and remaining requirements.

## Integration references

- [Binance Agent OS](https://www.binance.com/en/agent-os)
- [Official Spot public market-data guide](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md)
- [Hackathon announcement](https://www.binance.com/en-IN/blog/community/8802181509900814931)

The remaining activation work is configuring and validating a live model, completing MCP authorization and actual tool mappings, and confirming submission eligibility. Real trading requires a separate implementation and explicit account authorization.

Binance's [official Agent OS setup guide](https://www.binance.com/en/blog/ecosystem/5991233187660196794) documents the MCP endpoint `https://agent.binance.com/mcp/agentic` and browser authentication with account permissions. The public REST adapter is separate from MCP.
