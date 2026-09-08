# TradeCheck submission preparation

Status: source and paper demo are published at https://github.com/PJ-syst/tradecheck and https://pj-syst.github.io/tradecheck/. No social post or survey has been submitted. Live model validation, authenticated MCP mapping, and participant eligibility are outstanding.

## Event requirements checked September 8, 2026

The [official Binance mini-hackathon announcement](https://www.binance.com/en/blog/community/8802181509900814931) lists a deadline of **September 8, 2026, 23:59 UTC**, which is **September 9, 2026, 02:59 in Kampala**. Track A is for an agent built with Agent OS; submission asks for a video or demo, GitHub if applicable, and a completed survey, along with the announced social steps.

The announcement excludes users in certain jurisdictions, including the US, UK, EEA, Hong Kong, and Singapore, plus Binance's prohibited jurisdictions. A Kampala timezone does not establish participant eligibility. Confirm the participant's actual jurisdiction, Binance account eligibility, and the current survey terms before submission. A REST-only price connection plus an unactivated MCP adapter does not establish that Track A requirements are met.

Use the announcement's own links for the survey and social post. Publishing, following/reposting, submitting the survey, and sending messages remain separate user actions.

## Draft description

TradeCheck previews Spot purchases against a user-confirmed spending budget, protected reserve, and allowed-market list. The server checks each proposal and requires explicit approval before a paper purchase. Decimal arithmetic, expiring previews, and atomic, idempotent approvals protect the local paper wallet.

The app supports public Binance prices and exchange-filter estimates. An optional OpenAI interpreter produces structured purchase and rule proposals without execution tools. A configurable read-only MCP adapter is implemented with schema pinning and fixed arguments; authenticated Binance tool mapping and live model validation are still pending. The demo uses fixture prices, a strict parser, and simulated funds.

This draft intentionally describes the current build. Update it only after live integration verification, and do not describe the current demo as actual account trading.

## 90-second demo

Run `npm run demo:record` after `npm run build`. The recording is captioned, silent, and saved at `data/demo/tradecheck-paper-demo.mp4` with a metadata file. It uses a separate database and performs no external account calls.

| Time   | Scene                                                                                              |
| ------ | -------------------------------------------------------------------------------------------------- |
| 0–15s  | Introduce the 125-USDT paper wallet and 100-USDT protected reserve; request a 40-USDT BNB purchase |
| 15–32s | Show rejection and the reserve explanation                                                         |
| 32–54s | Revise to 20 USDT; review quantity, fee, and passing checks                                        |
| 54–66s | Explicitly approve one paper purchase                                                              |
| 66–77s | Show audit history and paper holdings                                                              |
| 77–90s | Show editable rules and disclose pending model/account activation                                  |

## Before publishing

- Finish authorized MCP discovery, verify actual balance/commission mappings, and test the account panel with read-only scope.
- Configure a model and evaluate real ambiguous/injection requests. Current synthetic tests prove server boundaries, not live model comprehension.
- Confirm eligibility and Track A acceptance of this implementation.
- Prepare the public repository and hosted demo/video link. Source and paper demo links are now available above.
- Review the description and recording, then authorize publishing separately.

The source bundle can be generated with `pwsh -File scripts/package-source.ps1` (PowerShell 7); it excludes databases, environment files, credentials, node_modules, build output, and recordings. The video can be reviewed and uploaded separately.

Binance rejected the custom OAuth client as unsupported (3346001). Codex is listed as supported and is the current connection path. Until a real supported-host integration is verified, do not claim an authenticated standalone TradeCheck account integration.
