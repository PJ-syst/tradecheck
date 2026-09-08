import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ShieldCheck,
  LayoutDashboard,
  ArrowUpRight,
  ArrowRight,
  SlidersHorizontal,
  History,
  FlaskConical,
  Wallet,
  CircleCheck,
  CircleX,
  Clock3,
  ChevronRight,
  LockKeyhole,
  Sparkles,
  Check,
  LoaderCircle,
  X,
  Info,
  LineChart,
  Newspaper,
  Download,
  TrendingUp,
} from "lucide-react";
import "./style.css";

const currency = (value) =>
  Number(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
const asset = (symbol) => symbol.replace("USDT", "");
const quoteTime = (timestamp) =>
  new Date(timestamp * 1000).toLocaleTimeString("en-GB", { timeZone: "UTC" }) +
  " UTC";

function App() {
  const [state, setState] = useState(null);
  const [tab, setTab] = useState("overview");
  const [message, setMessage] = useState("");
  const [preview, setPreview] = useState(null);
  const [receipt, setReceipt] = useState(null);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [now, setNow] = useState(Date.now());
  const [ruleRequest, setRuleRequest] = useState("");
  const [proposed, setProposed] = useState(false);
  const [tradeSide, setTradeSide] = useState("BUY");
  const [tradeAsset, setTradeAsset] = useState("BNBUSDT");
  const [tradeAmount, setTradeAmount] = useState("");
  const [advice, setAdvice] = useState(null);
  const [adviceRequest, setAdviceRequest] = useState({ asset: "BNBUSDT", horizon: "short", question: "" });
  const [reports, setReports] = useState([]);
  const [activeReport, setActiveReport] = useState(null);
  const [schedules, setSchedules] = useState([]);
  const [scheduleTime, setScheduleTime] = useState("08:00");
  const [adviceAmount, setAdviceAmount] = useState("");

  async function previewAdvice() {
    setBusy(true); setError("");
    try {
      setPreview(await post(`advice/${advice.id}/preview`, { amount: adviceAmount }));
      setReceipt(null); setTab("overview");
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  async function saveSchedule(report_type) {
    setBusy(true); setError("");
    try {
      const existing = schedules.find((s) => s.report_type === report_type);
      await post("report-schedules", { id: existing?.id, report_type, local_time: scheduleTime,
        timezone: "Africa/Kampala", destination: { type: "private" }, enabled: true });
      await loadReports();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  async function toggleSchedule(schedule) {
    setBusy(true); setError("");
    try {
      await post(`report-schedules/${schedule.id}`, { action: schedule.enabled ? "pause" : "enable" });
      await loadReports();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  async function refresh() {
    const response = await fetch("/api/state");
    if (!response.ok)
      throw new Error(
        "Could not reach the local service. Start the Python backend and try again.",
      );
    const result = await response.json();
    setState(result);
    return result;
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  async function post(path, body) {
    const response = await fetch(`/api/${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-TradeCheck-Token": state.csrf_token,
      },
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.error || "Request failed. Please try again.");
    return result;
  }

  async function refreshMarkets() {
    setBusy(true);
    setError("");
    try {
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function checkStructuredTrade(event) {
    event.preventDefault();
    if (!tradeAmount.trim() || busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    setReceipt(null);
    setPreview(null);
    try {
      const payload = { side: tradeSide, symbol: tradeAsset, quantity: tradeAmount };
      setPreview(await post("preview", payload));
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function analyze(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    setAdvice(null);
    try {
      const result = await post("advice", { ...adviceRequest, symbol: adviceRequest.asset });
      setAdvice(result);
      setTab("advice");
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function loadReports() {
    try {
      const result = await fetch("/api/reports").then((r) => r.json());
      setReports(result.reports || []);
      const scheduled = await fetch("/api/report-schedules").then((r) => r.json());
      setSchedules(scheduled.schedules || []);
    } catch (e) {
      setError(e.message);
    }
  }

  async function generateReport(report_type, period = "current") {
    setBusy(true);
    setError("");
    try {
      await post("reports", { report_type, period });
      await loadReports();
      setNotice(`${report_type} report generated.`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function openReport(report_id) {
    setBusy(true);
    try {
      const result = await fetch(`/api/reports/${report_id}`).then((r) => r.json());
      setActiveReport(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function checkTrade(event) {
    event.preventDefault();
    if (!message.trim() || busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    setReceipt(null);
    setPreview(null);
    try {
      setPreview(await post("preview", { message }));
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await post("approve", { preview_id: preview.id });
      setReceipt(result.trade);
      setPreview(null);
      setMessage("");
      await refresh();
    } catch (e) {
      setError(e.message);
      setPreview(null);
      await refresh().catch(() => {});
    } finally {
      setBusy(false);
    }
  }

  async function saveRules(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await post("rules", draft);
      await refresh();
      setDraft(null);
      setPreview(null);
      setNotice("Rules saved. Every new purchase will use these limits.");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function proposeRules(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await post("rules/propose", { message: ruleRequest });
      setDraft(result.rules);
      setProposed(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function refreshAccount() {
    setBusy(true);
    setError("");
    try {
      const account = await post("account/refresh", {});
      setState((current) => ({ ...current, account }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function openRules() {
    setProposed(false);
    setDraft({ ...state.rules });
    setError("");
  }
  const seconds = preview
    ? Math.max(0, Math.ceil(preview.expires_at - now / 1000))
    : 0;

  if (!state)
    return (
      <div className="loading-screen">
        <ShieldCheck size={40} />
        <h1>TradeCheck</h1>
        <p>{error || "Opening your workspace…"}</p>
        {error && (
          <button
            onClick={() => {
              setError("");
              refresh().catch((e) => setError(e.message));
            }}
          >
            Try again
          </button>
        )}
      </div>
    );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setTab("overview");
          }}
        >
          <span className="brand-mark">
            <ShieldCheck size={23} />
          </span>
          TradeCheck<span className="brand-dot">.</span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          <button
            className={tab === "overview" ? "nav-item active" : "nav-item"}
            onClick={() => setTab("overview")}
          >
            <LayoutDashboard size={18} />
            Overview
          </button>
          <button
            className={tab === "rules" ? "nav-item active" : "nav-item"}
            onClick={() => setTab("rules")}
          >
            <SlidersHorizontal size={18} />
            Trading rules<span className="nav-count">3</span>
          </button>
          <button
            className={tab === "activity" ? "nav-item active" : "nav-item"}
            onClick={() => setTab("activity")}
          >
            <History size={18} />
            Activity
          </button>
          <button
            className={tab === "advice" ? "nav-item active" : "nav-item"}
            onClick={() => setTab("advice")}
          >
            <TrendingUp size={18} />
            Research
          </button>
          <button
            className={tab === "reports" ? "nav-item active" : "nav-item"}
            onClick={() => { setTab("reports"); loadReports(); }}
          >
            <Newspaper size={18} />
            Reports
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="sandbox-card">
            <FlaskConical size={20} />
            <strong>A little room to experiment.</strong>
            <p>Explore your trading rules with a paper wallet.</p>
            <span>
              <span className="status-dot" /> Simulation active
            </span>
          </div>
          <div className="profile">
            <div className="avatar">P</div>
            <div>
              <strong>Personal workspace</strong>
              <small>Local prototype · v0.1</small>
            </div>
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <ChevronRight size={14} />
            <strong>
              {tab === "overview"
                ? "Overview"
                : tab === "rules"
                  ? "Trading rules"
                  : tab === "activity"
                    ? "Activity"
                    : tab === "advice"
                      ? "Research"
                      : "Reports"}
            </strong>
          </div>
          <span className="mode-pill">
            <FlaskConical size={14} /> Paper mode
          </span>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">YOUR RULES. EVERY TRADE.</div>
              <h1>
                {tab === "overview"
                  ? "Trade with a clear head."
                  : tab === "rules"
                    ? "Set your boundaries."
                    : tab === "activity"
                      ? "Every decision, recorded."
                      : tab === "advice"
                        ? "Research before you act."
                        : "Portfolio reports."}
              </h1>
              <p>
                {tab === "overview"
                  ? "A second look before your next move."
                  : tab === "rules"
                    ? "You decide the limits. TradeCheck checks every purchase."
                    : tab === "activity"
                      ? "Follow the requests, checks, and paper purchases in your workspace."
                      : tab === "advice"
                        ? "Evidence, thesis, and risks for supported assets."
                        : "Daily and monthly summaries of your paper portfolio."}
              </p>
            </div>
            <span className="local-badge">
              <span className="status-dot" /> Local service online
            </span>
          </div>
          {error && (
            <div className="alert error" role="alert">
              <CircleX size={18} />
              <span>{error}</span>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert success" role="status">
              <CircleCheck size={18} />
              <span>{notice}</span>
              <button
                aria-label="Dismiss notification"
                onClick={() => setNotice("")}
              >
                <X size={16} />
              </button>
            </div>
          )}

          {tab === "overview" && (
            <>
              <section className="stats-grid" aria-label="Paper wallet summary">
                <Stat
                  label="Available balance"
                  value={state.balance}
                  icon={<Wallet size={18} />}
                  note="USDT in your paper wallet"
                />
                <Stat
                  label="Daily budget remaining"
                  value={state.remaining_budget}
                  icon={<Clock3 size={18} />}
                  note={`${currency(state.spent_today)} of ${currency(state.rules.daily_limit)} USDT used · UTC`}
                  progress={Math.min(
                    100,
                    (Number(state.spent_today) /
                      (Number(state.rules.daily_limit) || 1)) *
                      100,
                  )}
                />
                <Stat
                  label="Protected reserve"
                  value={state.rules.reserve}
                  icon={<LockKeyhole size={18} />}
                  note="Your minimum balance after a purchase"
                  protectedCard
                />
              </section>
              <div className="content-grid">
                <div className="primary-column">
                  <section className="panel trade-panel">
                    <div className="panel-heading">
                      <div className="icon-title">
                        <span className="icon-tile">
                          <Sparkles size={20} />
                        </span>
                        <div>
                          <h2>What’s your next move?</h2>
                          <p>Check a trade against your trading rules.</p>
                        </div>
                      </div>
                      <span className="small-badge">SPOT {tradeSide}</span>
                    </div>
                    <div className="side-toggle">
                      {["BUY", "SELL"].map((side) => (
                        <button
                          key={side}
                          type="button"
                          className={tradeSide === side ? "active" : ""}
                          onClick={() => setTradeSide(side)}
                          disabled={busy}
                        >
                          {side}
                        </button>
                      ))}
                    </div>
                    {tradeSide === "BUY" ? (
                      <form onSubmit={checkTrade}>
                        <label className="sr-only" htmlFor="trade-request">
                          Trade request
                        </label>
                        <textarea
                          id="trade-request"
                          value={message}
                          onChange={(e) => setMessage(e.target.value)}
                          placeholder="Buy 40 USDT of BNB"
                          maxLength={
                            state.integration.interpreter ===
                            "strict request parser"
                              ? 200
                              : 1000
                          }
                          rows={3}
                          disabled={busy}
                        />
                        <div className="request-footer">
                          <span>
                            <LockKeyhole size={13} /> Every purchase needs your
                            approval
                          </span>
                          <button
                            className="primary-button"
                            disabled={busy || !message.trim()}
                          >
                            {busy ? (
                              <LoaderCircle size={16} className="spin" />
                            ) : (
                              <ShieldCheck size={16} />
                            )}
                            Check trade
                            <ArrowRight size={16} />
                          </button>
                        </div>
                      </form>
                    ) : (
                      <form onSubmit={checkStructuredTrade}>
                        <div className="sell-form">
                          <label>
                            Asset
                            <select
                              value={tradeAsset}
                              onChange={(e) => setTradeAsset(e.target.value)}
                              disabled={busy}
                            >
                              {state.supported_pairs.map((sym) => (
                                <option key={sym} value={sym}>
                                  {asset(sym)}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label>
                            Quantity to sell
                            <input
                              type="number"
                              step="0.00000001"
                              min="0"
                              value={tradeAmount}
                              onChange={(e) => setTradeAmount(e.target.value)}
                              placeholder="0.01"
                              disabled={busy}
                            />
                          </label>
                        </div>
                        <div className="request-footer">
                          <span>
                            <LockKeyhole size={13} /> Sells require your
                            approval
                          </span>
                          <button
                            className="primary-button"
                            disabled={busy || !tradeAmount.trim()}
                          >
                            {busy ? (
                              <LoaderCircle size={16} className="spin" />
                            ) : (
                              <ShieldCheck size={16} />
                            )}
                            Check sale
                            <ArrowRight size={16} />
                          </button>
                        </div>
                      </form>
                    )}
                    {tradeSide === "BUY" && (
                      <div className="suggestions">
                        <span>TRY A REQUEST</span>
                        {["Buy 40 USDT of BNB", "Buy 20 USDT of BTC"].map(
                          (example) => (
                            <button
                              key={example}
                              disabled={busy}
                              onClick={() => setMessage(example)}
                            >
                              {example}
                              <ArrowUpRight size={12} />
                            </button>
                          ),
                        )}
                      </div>
                    )}
                  </section>

                  {preview ? (
                    <section
                      className={`panel decision ${preview.allowed ? "decision-pass" : "decision-block"}`}
                      aria-live="polite"
                    >
                      <div className="decision-title">
                        {preview.allowed ? (
                          <CircleCheck size={24} />
                        ) : (
                          <ShieldCheck size={24} />
                        )}
                        <div>
                          <h2>
                            {preview.allowed
                              ? "Within your limits."
                              : preview.side === "SELL" ? "This sale needs a rethink." : "This purchase needs a rethink."}
                          </h2>
                          <p>
                            {preview.allowed
                              ? `Review the details before approving this paper ${preview.side === "SELL" ? "sale" : "purchase"}.`
                              : "This request does not meet all of your trading rules."}
                          </p>
                        </div>
                      </div>
                      <div className="trade-summary">
                        <span>
                          {preview.side || "BUY"} <strong>{asset(preview.symbol)}</strong>
                        </span>
                        <strong>
                          {currency(preview.side === "SELL" ? preview.gross_proceeds : preview.amount)} <small>USDT</small>
                        </strong>
                      </div>
                      <p className="disclosure">
                        Paper quantity: {preview.quantity}{" "}
                        {asset(preview.symbol)}.
                        {Number(preview.unspent_amount) > 0 &&
                          ` Rounding leaves ${preview.unspent_amount} USDT unspent.`}
                      </p>
                      <div className="checks">
                        {preview.checks.map((check) => (
                          <div className="check-row" key={check.name}>
                            {check.pass ? (
                              <CircleCheck size={17} className="green" />
                            ) : (
                              <CircleX size={17} className="amber" />
                            )}
                            <div>
                              <strong>{check.name}</strong>
                              <p>{check.detail}</p>
                            </div>
                            <span
                              className={
                                check.pass
                                  ? "check-label green"
                                  : "check-label amber"
                              }
                            >
                              {check.pass ? "Passed" : "Blocked"}
                            </span>
                          </div>
                        ))}
                      </div>
                      <div className="cost-grid">
                        <div>
                          <span>Simulated fee (0.1%)</span>
                          <strong>{preview.fee} USDT</strong>
                        </div>
                        <div>
                          <span>{preview.side === "SELL" ? "Net proceeds" : "Total debit"}</span>
                          <strong>{preview.total} USDT</strong>
                        </div>
                        <div>
                          <span>Balance after</span>
                          <strong>{preview.balance_after} USDT</strong>
                        </div>
                      </div>
                      {preview.allowed ? (
                        <div className="approval">
                          <p>
                            <Clock3 size={14} />{" "}
                            {seconds
                              ? `Preview valid for ${seconds}s`
                              : "Preview expired. Check your request again."}
                          </p>
                          <button
                            className="primary-button"
                            disabled={busy || !seconds}
                            onClick={approve}
                          >
                            <Check size={16} />
                            Approve paper {preview.side === "SELL" ? "sale" : "purchase"}
                          </button>
                        </div>
                      ) : (
                        <div className="blocked-action">
                          <p>
                            {Number(preview.maximum) > 0
                              ? `Your current rules allow up to ${preview.maximum} USDT before fees.`
                              : "Update your request or rules before continuing."}
                          </p>
                          {Number(preview.maximum) > 0 && (
                            <button
                              className="text-button"
                              disabled={busy}
                              onClick={() => {
                                setMessage(
                                  `Buy ${preview.maximum} USDT of ${asset(preview.symbol)}`,
                                );
                                setPreview(null);
                              }}
                            >
                              Use this amount
                              <ArrowRight size={14} />
                            </button>
                          )}
                        </div>
                      )}
                      <p className="disclosure">
                        {preview.price_source}: {currency(preview.price)} USDT.
                        {preview.quote?.observed_at != null &&
                          ` Retrieved ${quoteTime(preview.quote.observed_at)}.`}{" "}
                        Paper fill uses this preview price. Simulated fee;
                        {preview.filter_source === "Binance exchangeInfo"
                          ? " Binance quantity and notional checks are estimates for this paper wallet. Actual fills, reference prices, and account limits may differ."
                          : " Demo minimum and quantity rounding apply."}
                      </p>
                    </section>
                  ) : receipt ? (
                    <section className="panel receipt" aria-live="polite">
                      <span className="receipt-icon">
                        <CircleCheck size={30} />
                      </span>
                      <h2>Paper {receipt.side === "SELL" ? "sale" : "purchase"} complete.</h2>
                      <p>
                        {receipt.side === "SELL" ? "You sold" : "You added"} {receipt.quantity} {asset(receipt.symbol)} {receipt.side === "SELL" ? "from" : "to"} your paper wallet.
                      </p>
                      <div>
                        <span>{receipt.side === "SELL" ? "Net proceeds" : "Total debit"}</span>
                        <strong>{receipt.total} USDT</strong>
                      </div>
                      <div>
                        <span>Available balance</span>
                        <strong>{receipt.balance_after} USDT</strong>
                      </div>
                      <small>
                        Reference: {receipt.id} · No real funds moved.
                      </small>
                    </section>
                  ) : (
                    <section className="panel empty-preview">
                      <div className="preview-art">
                        <ShieldCheck size={33} />
                        <span className="art-orbit orbit-one" />
                        <span className="art-orbit orbit-two" />
                        <span className="art-dot" />
                      </div>
                      <h2>A clearer decision starts here.</h2>
                      <p>
                        Your preview will show the cost, the checks,
                        <br />
                        and what’s left in your wallet.
                      </p>
                      <div className="preview-steps">
                        <span>
                          01 <b>Request</b>
                        </span>
                        <ChevronRight size={13} />
                        <span>
                          02 <b>Review</b>
                        </span>
                        <ChevronRight size={13} />
                        <span>
                          03 <b>Approve</b>
                        </span>
                      </div>
                    </section>
                  )}
                </div>
                <div className="secondary-column">
                  <RulesCard rules={state.rules} onEdit={openRules} />
                  <section className="panel markets-panel">
                    <div className="section-title">
                      <h2>Market prices</h2>
                      <span className="small-badge">
                        {state.market_data.provider === "binance"
                          ? "BINANCE"
                          : "FIXTURE DATA"}
                      </span>
                    </div>
                    {state.market_data.error && (
                      <p className="market-error" role="status">
                        {state.market_data.error}
                      </p>
                    )}
                    {state.markets.map((market) => (
                      <div className="market-row" key={market.symbol}>
                        <div
                          className={`coin coin-${asset(market.symbol).toLowerCase()}`}
                        >
                          {asset(market.symbol) === "BTC"
                            ? "₿"
                            : asset(market.symbol) === "ETH"
                              ? "Ξ"
                              : "B"}
                        </div>
                        <div>
                          <strong>{asset(market.symbol)}</strong>
                          <small>{asset(market.symbol)}/USDT</small>
                          {market.observed_at != null && (
                            <small>
                              {quoteTime(market.observed_at)}
                              {now >= market.expires_at * 1000
                                ? " · Expired"
                                : ""}
                            </small>
                          )}
                        </div>
                        <strong className="market-price">
                          {currency(market.price)}
                        </strong>
                      </div>
                    ))}
                    <p className="disclosure">
                      {state.market_data.provider === "binance"
                        ? "Binance public API · Last traded prices in USDT. Times show retrieval, not the last trade. Paper wallet only."
                        : "Illustrative prices, not live quotes."}
                    </p>
                    {state.market_data.provider === "binance" && (
                      <button
                        className="text-button"
                        disabled={busy}
                        onClick={refreshMarkets}
                      >
                        Refresh markets
                      </button>
                    )}
                  </section>
                  <div className="integration-note">
                    <Info size={17} />
                    <p>
                      Request interpreter: {state.integration.interpreter}.
                      Every proposal is checked by the server and needs your
                      approval.
                    </p>
                  </div>
                </div>
              </div>
              <section
                className="panel account-panel"
                aria-label="Binance account"
              >
                <div className="section-title">
                  <h2>Binance account · Read only</h2>
                  <button
                    className="text-button"
                    onClick={refreshAccount}
                    disabled={busy}
                  >
                    Refresh account
                  </button>
                </div>
                <p className="disclosure">
                  {state.account.status} · Actual account balances are separate
                  from your paper wallet.
                </p>
                {state.account.observed_at != null && (
                  <p className="disclosure">
                    Retrieved {quoteTime(state.account.observed_at)}
                    {now >= state.account.expires_at * 1000
                      ? " · Expired — refresh to update"
                      : ""}
                  </p>
                )}
                {state.account.error && (
                  <p className="market-error" role="status">
                    {state.account.error}
                  </p>
                )}
                {state.account.status === "not connected" && (
                  <p className="disclosure">
                    Complete Binance MCP authorization and configure the
                    read-only account integration on the server.
                  </p>
                )}
                {state.account.balances.map((balance) => (
                  <div className="holding-row" key={balance.asset}>
                    <strong>{balance.asset}</strong>
                    <span>
                      {balance.free} available · {balance.locked} locked
                    </span>
                  </div>
                ))}
                {Object.entries(state.account.commissions).map(
                  ([symbol, rates]) => (
                    <details key={symbol}>
                      <summary>
                        {asset(symbol)}/USDT account commission rates
                      </summary>
                      {Object.entries(rates).map(([category, values]) => (
                        <p className="disclosure" key={category}>
                          {category}:{" "}
                          {Object.entries(values)
                            .map(([key, value]) => `${key} ${value}`)
                            .join(" · ")}
                        </p>
                      ))}
                      <p className="disclosure">
                        Rates are fractions. Discounts and fee assets may change
                        actual charges. Paper fees remain simulated.
                      </p>
                    </details>
                  ),
                )}
              </section>
              <Activity
                events={state.events.slice(0, 4)}
                onViewAll={() => setTab("activity")}
              />
            </>
          )}
          {tab === "rules" && (
            <div className="rules-page">
              <RulesCard rules={state.rules} onEdit={openRules} />
              {state.integration.interpreter !== "strict request parser" && (
                <section className="panel rules-explainer">
                  <h2>Describe a rule change</h2>
                  <p>Review and confirm the proposed values before saving.</p>
                  <form onSubmit={proposeRules}>
                    <label htmlFor="rule-request">Rule change request</label>
                    <textarea
                      id="rule-request"
                      value={ruleRequest}
                      onChange={(e) => setRuleRequest(e.target.value)}
                      maxLength={1000}
                      rows={3}
                      placeholder="Set my daily budget to 75 USDT and keep 100 USDT in reserve"
                      disabled={busy}
                    />
                    <button
                      className="primary-button"
                      disabled={busy || !ruleRequest.trim()}
                    >
                      Propose rule change
                    </button>
                  </form>
                </section>
              )}
              <section className="panel rules-explainer">
                <ShieldCheck size={28} />
                <h2>Checked on the server.</h2>
                <p>
                  Your daily spending limit includes estimated fees and resets
                  at midnight UTC. Your reserve is the minimum USDT balance
                  allowed after a purchase.
                </p>
                <p>
                  Every approval rechecks the saved rules and available balance.
                  Changing rules invalidates existing previews.
                </p>
                <p>Turning off all markets pauses paper purchases.</p>
              </section>
            </div>
          )}
          {tab === "activity" && (
            <>
              <Activity events={state.events} />
              <section className="panel holdings-panel">
                <h2>Paper holdings</h2>
                {Object.keys(state.holdings).length ? (
                  Object.entries(state.holdings).map(([symbol, quantity]) => (
                    <div className="holding-row" key={symbol}>
                      <strong>{symbol}</strong>
                      <span>{quantity}</span>
                    </div>
                  ))
                ) : (
                  <p>Your approved paper purchases will appear here.</p>
                )}
              </section>
            </>
          )}
          {tab === "advice" && (
            <>
              <section className="panel trade-panel">
                <div className="panel-heading">
                  <div className="icon-title">
                    <span className="icon-tile">
                      <LineChart size={20} />
                    </span>
                    <div>
                      <h2>Request an analysis</h2>
                      <p>Choose an asset, horizon, and optional question.</p>
                    </div>
                  </div>
                </div>
                <form onSubmit={analyze}>
                  <div className="sell-form">
                    <label>
                      Asset
                      <select
                        value={adviceRequest.asset}
                        onChange={(e) =>
                          setAdviceRequest({ ...adviceRequest, asset: e.target.value })
                        }
                        disabled={busy}
                      >
                        {state.supported_pairs.map((sym) => (
                          <option key={sym} value={sym}>
                            {asset(sym)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Horizon
                      <select
                        value={adviceRequest.horizon}
                        onChange={(e) =>
                          setAdviceRequest({ ...adviceRequest, horizon: e.target.value })
                        }
                        disabled={busy}
                      >
                        {["short", "medium", "long"].map((h) => (
                          <option key={h} value={h}>
                            {h}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <label>
                    Optional question
                    <input
                      type="text"
                      value={adviceRequest.question}
                      onChange={(e) =>
                        setAdviceRequest({ ...adviceRequest, question: e.target.value })
                      }
                      placeholder="What would change your view?"
                      disabled={busy}
                    />
                  </label>
                  <button className="primary-button" disabled={busy}>
                    {busy ? <LoaderCircle size={16} className="spin" /> : <TrendingUp size={16} />}
                    Analyze
                  </button>
                </form>
              </section>
              {advice && (
                <section className="panel decision decision-pass">
                  <div className="decision-title">
                    <LineChart size={24} />
                    <div>
                      <h2>
                        {advice.output.recommendation.replace("_", " ")} · {asset(advice.asset)}
                      </h2>
                      <p>{advice.model}</p>
                    </div>
                  </div>
                  <p className="disclosure">{advice.output.thesis}</p>
                  <div className="checks">
                    {advice.output.supporting_factors.map((f, i) => (
                      <div className="check-row" key={`sup-${i}`}>
                        <CircleCheck size={17} className="green" />
                        <div>
                          <strong>Supporting</strong>
                          <p>{f}</p>
                        </div>
                      </div>
                    ))}
                    {advice.output.risks.map((f, i) => (
                      <div className="check-row" key={`risk-${i}`}>
                        <ShieldCheck size={17} className="amber" />
                        <div>
                          <strong>Risk</strong>
                          <p>{f}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                  <p className="disclosure">Evidence IDs: {advice.evidence_ids.join(", ")}</p>
                  <p>{advice.output.news_impact}</p>
                  <p>{advice.output.portfolio_impact}</p>
                  {["opposing_factors", "missing_inputs", "invalidation_conditions"].map((key) => (
                    <div key={key}><h3>{key.replaceAll("_", " ")}</h3>
                      <ul>{advice.output[key].map((text, i) => <li key={i}>{text}</li>)}</ul></div>
                  ))}
                  {(advice.evidence || []).map((ev) => <p key={ev.id}>
                    {ev.canonical_url?.startsWith("https://") ? <a href={ev.canonical_url} target="_blank" rel="noreferrer">{ev.headline}</a> : ev.source || ev.error || ev.id}
                    {ev.published_at && ` · Published ${new Date(ev.published_at * 1000).toLocaleString()}`}
                    {ev.price && ` · ${ev.price} USDT`}
                    {ev.retrieved_at && ` · Retrieved ${new Date(ev.retrieved_at * 1000).toLocaleString()}`}
                  </p>)}
                  <p>Paper portfolio · {advice.horizon} horizon · Expires {quoteTime(advice.expires_at)}</p>
                  {["BUY", "SELL"].includes(advice.output.recommendation) && <div className="sell-form">
                    <label>Proposal amount ({advice.output.recommendation === "BUY" ? "USDT" : asset(advice.asset)})
                      <input value={adviceAmount} onChange={(e) => setAdviceAmount(e.target.value)} inputMode="decimal" />
                    </label>
                    <button className="secondary-button" disabled={busy || !adviceAmount || now / 1000 >= advice.expires_at} onClick={previewAdvice}>Preview paper {advice.output.recommendation.toLowerCase()}</button>
                  </div>}
                </section>
              )}
            </>
          )}
          {tab === "reports" && (
            <>
              <section className="panel trade-panel">
                <div className="panel-heading">
                  <div className="icon-title">
                    <span className="icon-tile">
                      <Newspaper size={20} />
                    </span>
                    <div>
                      <h2>Generate a report</h2>
                      <p>Daily or month-to-date summaries of your paper portfolio.</p>
                    </div>
                  </div>
                </div>
                <div className="sell-form">
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() => generateReport("daily", "current")}
                  >
                    Daily current
                  </button>
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() => generateReport("monthly", "current")}
                  >
                    Monthly current
                  </button>
                </div>
              </section>
              {activeReport && (
                <section className="panel decision decision-pass">
                  <div className="section-title">
                    <h2>{activeReport.calculations.period_label}</h2>
                    <button className="icon-button" onClick={() => setActiveReport(null)}>
                      <X size={20} />
                    </button>
                  </div>
                  <p className="disclosure">Coverage: {activeReport.calculations.coverage}</p>
                  {activeReport.calculations.coverage_notes.map((note, i) => <p key={i}>{note}</p>)}
                  <p>Buys: {activeReport.calculations.buys} · Sells: {activeReport.calculations.sells} · Fees: {activeReport.calculations.fees} USDT · Realized P&amp;L: {activeReport.calculations.realized_pnl} USDT</p>
                  <p className="disclosure">
                    Opening value: {activeReport.calculations.opening_value} USDT · Closing value:{" "}
                    {activeReport.calculations.closing_value} USDT
                  </p>
                  <div className="sell-form">
                    <a
                      className="text-button"
                      href={`/api/reports/${activeReport.id}/download?format=markdown`}
                    >
                      <Download size={14} /> Markdown
                    </a>
                    <a
                      className="text-button"
                      href={`/api/reports/${activeReport.id}/download?format=html`}
                    >
                      <Download size={14} /> HTML
                    </a>
                    <a
                      className="text-button"
                      href={`/api/reports/${activeReport.id}/download?format=json`}
                    >
                      <Download size={14} /> JSON
                    </a>
                  </div>
                </section>
              )}
              <section className="panel activity-panel">
                <div className="section-title">
                  <h2>Reports</h2>
                </div>
                {reports.length ? (
                  reports.map((r) => (
                    <div className="activity-row" key={r.id}>
                      <span className="event-icon rules">
                        <Newspaper size={17} />
                      </span>
                      <div>
                        <strong>{r.report_type}</strong>
                        <p>{r.period_label}</p>
                      </div>
                      <button className="text-button" onClick={() => openReport(r.id)}>
                        View
                      </button>
                    </div>
                  ))
                ) : (
                  <p>No reports yet.</p>
                )}
              </section>
              <section className="panel">
                <h2>Private publication schedule</h2>
                <p>Reports publish here while the backend runs. Missed runs are recovered at startup; unavailable historical values remain disclosed.</p>
                <label>Publication time (Africa/Kampala)<input type="time" value={scheduleTime} onChange={(e) => setScheduleTime(e.target.value)} /></label>
                <div className="sell-form">{["daily", "monthly"].map((type) => <button key={type} className="secondary-button" disabled={busy} onClick={() => saveSchedule(type)}>Schedule {type}</button>)}</div>
                {schedules.map((s) => <div key={s.id} className="activity-row"><div><strong>{s.report_type} · {s.enabled ? "Enabled" : "Paused"}</strong><p>Next: {new Date(s.next_run * 1000).toLocaleString()} · {s.timezone}</p></div><button disabled={busy} onClick={() => toggleSchedule(s)}>{s.enabled ? "Pause" : "Enable"}</button></div>)}
                <div className="sell-form"><button disabled={busy} onClick={() => generateReport("daily", "completed")}>Previous day</button><button disabled={busy} onClick={() => generateReport("monthly", "completed")}>Previous month</button></div>
              </section>
            </>
          )}
          <footer>
            <span>
              <ShieldCheck size={14} />
              TradeCheck · Built around your boundaries.
            </span>
            <span>Paper wallet · No real orders</span>
          </footer>
        </main>
      </div>

      {draft && (
        <div
          className="modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget && !busy) setDraft(null);
          }}
        >
          <section
            className="modal panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby="rules-title"
            onKeyDown={(e) => {
              if (e.key === "Escape" && !busy) setDraft(null);
            }}
          >
            <div className="section-title">
              <h2 id="rules-title">
                {proposed ? "Review proposed rules" : "Edit trading rules"}
              </h2>
              <button
                className="icon-button"
                aria-label="Close rules"
                disabled={busy}
                onClick={() => setDraft(null)}
              >
                <X size={20} />
              </button>
            </div>
            <p>
              {proposed
                ? "The language agent proposed these values. Review each change before confirming."
                : "Confirm the limits for future paper purchases."}
            </p>
            {proposed && (
              <p className="disclosure">
                Current daily budget: {state.rules.daily_limit} USDT. Current
                reserve: {state.rules.reserve} USDT. Current markets:{" "}
                {state.rules.allowed_pairs.map(asset).join(", ") || "None"}.
              </p>
            )}
            <form onSubmit={saveRules}>
              <label>
                Daily spending limit (USDT)
                <input
                  autoFocus
                  type="number"
                  min="0"
                  max="1000000"
                  step="0.01"
                  required
                  value={draft.daily_limit}
                  onChange={(e) =>
                    setDraft({ ...draft, daily_limit: e.target.value })
                  }
                />
              </label>
              <label>
                Protected reserve (USDT)
                <input
                  type="number"
                  min="0"
                  max="1000000"
                  step="0.01"
                  required
                  value={draft.reserve}
                  onChange={(e) =>
                    setDraft({ ...draft, reserve: e.target.value })
                  }
                />
              </label>
              <fieldset>
                <legend>Allowed markets</legend>
                {state.supported_pairs.map((symbol) => (
                  <label className="checkbox-label" key={symbol}>
                    <input
                      type="checkbox"
                      checked={draft.allowed_pairs.includes(symbol)}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          allowed_pairs: e.target.checked
                            ? [...draft.allowed_pairs, symbol]
                            : draft.allowed_pairs.filter((x) => x !== symbol),
                        })
                      }
                    />
                    {asset(symbol)}/USDT
                  </label>
                ))}
              </fieldset>
              {error && (
                <p className="form-error" role="alert">
                  {error}
                </p>
              )}
              <p className="disclosure">
                Saving rules invalidates existing trade previews.
              </p>
              <button className="primary-button" disabled={busy}>
                <Check size={16} />
                Confirm and save rules
              </button>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, icon, note, progress, protectedCard }) {
  return (
    <article className={`stat-card ${protectedCard ? "reserve-card" : ""}`}>
      <div className="stat-label">
        {label}
        {icon}
      </div>
      <div className="stat-value">
        {currency(value)}
        <span>USDT</span>
      </div>
      {progress !== undefined && (
        <div className="progress-track">
          <span style={{ width: `${progress}%` }} />
        </div>
      )}
      <p>
        {protectedCard && <ShieldCheck size={13} />}
        {note}
      </p>
    </article>
  );
}

function RulesCard({ rules, onEdit }) {
  return (
    <section className="panel rules-card">
      <div className="section-title">
        <h2>Your trading rules</h2>
        <span className="shield-mini">
          <ShieldCheck size={18} />
        </span>
      </div>
      <p className="panel-subtitle">A few boundaries. More peace of mind.</p>
      <div className="rule-row">
        <span>Daily spending limit</span>
        <strong>
          {currency(rules.daily_limit)} <small>USDT</small>
        </strong>
      </div>
      <div className="rule-row">
        <span>Protected reserve</span>
        <strong>
          {currency(rules.reserve)} <small>USDT</small>
        </strong>
      </div>
      <div className="rule-markets">
        <span>Allowed markets</span>
        <div>
          {rules.allowed_pairs.length ? (
            rules.allowed_pairs.map((symbol) => (
              <span className="asset-pill" key={symbol}>
                {asset(symbol)}
              </span>
            ))
          ) : (
            <span className="amber">All purchases paused</span>
          )}
        </div>
      </div>
      <div className="approval-rule">
        <LockKeyhole size={15} />
        <span>Approval required for every purchase</span>
        <Check size={15} />
      </div>
      <button className="secondary-button" onClick={onEdit}>
        <SlidersHorizontal size={15} />
        Edit rules
      </button>
    </section>
  );
}

function Activity({ events, onViewAll }) {
  return (
    <section className="panel activity-panel">
      <div className="section-title">
        <h2>Recent activity</h2>
        {onViewAll && (
          <button className="text-button" onClick={onViewAll}>
            View all
            <ArrowUpRight size={14} />
          </button>
        )}
      </div>
      {events.length ? (
        events.map((event, i) => (
          <div className="activity-row" key={`${event.timestamp}-${i}`}>
            <span className={`event-icon ${event.kind}`}>
              {event.kind === "blocked" ? (
                <ShieldCheck size={17} />
              ) : event.kind === "rules" ? (
                <SlidersHorizontal size={17} />
              ) : (
                <Check size={17} />
              )}
            </span>
            <div>
              <strong>{event.title}</strong>
              <p>{event.detail}</p>
            </div>
            <time dateTime={new Date(event.timestamp * 1000).toISOString()}>
              {new Date(event.timestamp * 1000).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </time>
          </div>
        ))
      ) : (
        <div className="activity-empty">
          <History size={19} />
          <span>A fresh start. Your first trade check will appear here.</span>
        </div>
      )}
    </section>
  );
}

createRoot(document.getElementById("root")).render(<App />);
