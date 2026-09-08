# Read-only MCP account setup

The local adapter is implemented and tested with synthetic tools. It is **not yet an authenticated Binance integration**. A live unauthenticated initialization returned HTTP 401 on September 8, 2026, so the actual tool schemas could not be discovered. No Binance tool names are guessed in the implementation.

## Authorization

Binance documents the endpoint `https://agent.binance.com/mcp/agentic` and a browser authorization flow in its [official setup guide](https://www.binance.com/en/blog/ecosystem/5991233187660196794). Its [MCP FAQ](https://www.binance.com/en/support/faq/detail/7a6e676e36fb455d96478932cb12d9f3) distinguishes Market data, Account, Trade, and Transfer scopes. For this application, use Account read access and leave Trade/Transfer disabled. Confirm which Agentic sub-account or permitted main-account view the authorization exposes.

Binance rejected the custom TradeCheck OAuth client with error `3346001`: the agent is not supported. Public discovery advertised OAuth capabilities, but that does not mean arbitrary clients are accepted. The custom login command is now disabled.

Use a genuine supported client. Binance explicitly lists Codex and Codex CLI in its FAQ:

```powershell
codex mcp add binance --url https://agent.binance.com/mcp/agentic
# For an already configured server:
codex mcp login binance
```

Follow the URL printed by Codex on the same computer. Select Account read access and leave Trade/Transfer disabled. Codex manages its own authorization and credential storage. **Do not extract Codex's token or reuse its client identity in TradeCheck.**

This connects Binance to Codex. It does not activate the standalone account panel. A supported Codex-mediated integration or explicit Binance approval of a standalone client is still required. The existing standalone adapter remains unactivated; its environment token option is only for authorization explicitly issued to that application.

The Windows encrypted model-key setup is separate and remains available with `python -m backend.setup`.

## Discover, review, and pin tools

Only after Binance explicitly authorizes the standalone application and provides its own valid server token:

```powershell
python -m backend.mcp --discover data/mcp-tools.json
```

This performs MCP initialization and paginated `tools/list`; it does not call any account or trading tool. It saves discovered definitions and a `schema_sha256` covering each input schema and annotations. The transport supports JSON and SSE responses for the [2025-06-18 MCP protocol](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).

Review the actual descriptions and schemas to identify a balance read and per-symbol commission reads. Read-only annotations alone are not proof of a tool's safety; verify its documented purpose before configuring it. The adapter refuses missing/changed schemas, tools without `readOnlyHint: true`, and contradictory `destructiveHint: true` annotations.

Create `data/mcp-account.json` with exactly two top-level keys:

- `balances`: one read specification.
- `commissions`: a map containing `BNBUSDT`, `BTCUSDT`, and `ETHUSDT`, each with a read specification.

Each read specification contains exactly these fields:

| Field           | Value                                                                                    |
| --------------- | ---------------------------------------------------------------------------------------- |
| `tool`          | Actual reviewed name from discovery                                                      |
| `schema_sha256` | Its exact discovered hash                                                                |
| `arguments`     | Fixed arguments matching that tool's input schema                                        |
| `result_path`   | Array of object keys locating the payload inside structuredContent or a JSON text result |

The expected normalized balance payload is an array of `{ "asset": "USDT", "free": "125.00", "locked": "0" }` rows. Commission payloads must contain the requested `symbol` and `standardCommission`, `specialCommission`, and `taxCommission`, each with decimal-string `maker`, `taker`, `buyer`, and `seller` rates. These mirror Binance Spot account data conventions; **actual MCP result shapes must be verified**. If the discovered tools use different fields, support their verified shape in the adapter and tests before connecting. Do not fabricate compatible responses or silently omit unavailable fee components.

## Run and verify

```powershell
python -m backend.server --market-data binance --mcp-manifest data/mcp-account.json
```

Click **Refresh account**. Verify the source account, balances, and commission components against Binance. The app keeps them in memory and separate from the paper wallet. It exposes no arbitrary MCP call endpoint. All configured tool definitions are checked before the first account read. Request arguments are fixed by the manifest, never generated by the language model.

Commissions are informational. Discounts, fee currency, taxes, and actual execution behavior can affect charges; paper fees remain a clearly labeled simulation. Account refresh failures clear the displayed values, and successful snapshots expire after 60 seconds.
