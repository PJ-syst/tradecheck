# TradeCheck build plan

## Product

An assistant that checks a proposed Spot purchase against user-confirmed limits, explains the decision, and requires approval before execution. The server enforces every rule. An eventual language model may propose structured requests but cannot authorize or execute trades itself.

## Milestone 1 — Local demonstrable prototype (completed)

- React dashboard: account overview, trade request, decision preview, editable rules, activity log.
- Python backend using Decimal arithmetic and SQLite transactions.
- Support BNB/USDT, BTC/USDT, and ETH/USDT purchases in quote currency.
- Enforce daily spending including estimated fees, minimum USDT reserve, allowed pairs, and simulated exchange minimums.
- Require explicit approval of a stored, expiring preview; revalidate rules and funds at approval and prevent duplicate execution.
- Clearly label the paper wallet, fixture prices, and simulated fills.
- Test boundaries, stale previews, duplicate and concurrent approvals, changed rules, and malformed inputs.

Acceptance demo: begin with 125 USDT, 100 USDT reserve, 50 USDT daily budget. Request 40 USDT of BNB and show rejection. Request 20 USDT, preview fees and reserve, approve once, and show the resulting wallet and audit entry.

The default offline prototype is complete. Milestone 2 has public-data support plus an unactivated account adapter; milestone 3 is implemented but awaits live model validation; milestone 4 has local review materials. Browser screenshots are in `data/screenshots/` (ignored by Git).

## Milestone 2 — Binance data and account integration

- Completed: optional public price adapter (`--market-data binance`) using Binance's documented ticker endpoint. Source, UTC retrieval time, expiry, refresh, and failure status are visible. No silent fixture fallback.
- Completed: response validation, shared request cache, rate-limit backoff, quote expiry, and stored preview prices for paper approvals. Source changes invalidate pending previews. Added 11 backend/API tests and a browser workflow for market status, expiry, outage, and recovery. Public smoke check succeeded for all three pairs on September 8, 2026.
- Completed: exchangeInfo/avgPrice retrieval; quantity increments, quantity and applicable notional bounds, market permissions, paper position/order constraints, and rejection of unknown filters. Rounded purchase cost and unspent amount are visible. A live BNB price/filter/average-price check passed.
- Implemented with synthetic tests: read-only MCP transport/discovery, fixed reviewed mappings, schema pinning, response validation, and a separate account panel for balances and commission components. Results remain in memory and do not fund the paper wallet or alter its simulated fee.
- Custom OAuth login was rejected by Binance as an unsupported agent (3346001) and is disabled. Metadata support did not establish client acceptance. Connect through genuine Codex MCP; this does not authorize the standalone backend. A supported host integration or explicit standalone client approval remains required. Encrypted Windows-user model-key storage is implemented.
- Pending: authenticated discovery and review of actual balance/commission tool names, schemas, and result mappings. Live unauthenticated initialization returned HTTP 401. No tool names are guessed.
- Pending: live verification against the authorized account. Actual exchange reference-price overrides, account-wide limits, liquidity, slippage, and fee-asset execution remain outside the paper model. Its filter estimates are not complete real-order validation.

Verification uses isolated paper databases. Browser tests now have a test-only private shutdown hook to avoid Windows cleanup hangs; the production server exposes no shutdown endpoint.

## Milestone 3 — Language agent

- Implemented: optional OpenAI Responses interpreter, structured output and independent validation, purchase previews, and editable natural-language rule proposals requiring explicit save confirmation.
- Model has no tools, account data, credentials, or approval capability. Server rules remain authoritative. Stale rule drafts cannot overwrite newer rules.
- Synthetic tests cover clarification, invalid/refused/incomplete outputs, unsupported values, fabricated tools, and attempts to override rules. These test server boundaries, not live model comprehension.
- Pending: configure OPENAI_API_KEY and OPENAI_MODEL, then evaluate live ordinary, ambiguous, and injection requests. No model credentials were available. The strict parser remains the default.

## Milestone 4 — Submission

- Completed: captioned 90-second paper demo at `data/demo/tradecheck-paper-demo.mp4`; repeatable with `npm run demo:record`. It clearly uses fixture prices, a strict parser, and simulated funds.
- Completed: README, MCP setup notes, submission draft, and source-bundle script. Nothing has been published or posted.
- Deadline verified from the official announcement: September 8, 2026, 23:59 UTC / September 9, 02:59 Kampala.
- Pending: verify participant eligibility and Track A compliance after actual Agent OS activation; create/publish a remote repository and video/demo link; complete social and survey submission steps. Publishing and posting require a separate user request.

## Stack and scope

React + Vite; Python standard-library HTTP server; SQLite; no backend dependency installation needed. Start with one local user and Spot purchases. No withdrawals, futures, background trading, real-order endpoint, or production authentication in this prototype.

## Verification

Run backend unit and HTTP tests, build the frontend, and exercise the browser if a browser runner is available. Validate the complete preview-to-approval flow and the rejection flow. Tests use temporary databases and never contact a trading account.

Four headless Edge workflows cover the paper purchase flow, market failure/recovery, rule-proposal confirmation while markets are unavailable, and separate account display, including mobile overflow checks. Public Binance data was checked live; model/account tests use synthetic responses. See README for the final test count and activation limitations.
