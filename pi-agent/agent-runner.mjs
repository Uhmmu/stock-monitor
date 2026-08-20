// Agent research runner: builds a Pi Agent with backend-backed tools and the
// terminating submit_discovery_result tool, runs the research funnel, and
// returns the final structured result.

import {
  Agent,
} from "@earendil-works/pi-agent-core";
import {
  createModels,
  createProvider,
  envApiKeyAuth,
} from "@earendil-works/pi-ai";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";

const USER_AGENT = "stock-monitor-pi-agent/1.0";
const RESCUE_TIMEOUT_MS = 120_000; // rescue turn must not hang the worker forever

function env(name, fallback = "") {
  const value = process.env[name];
  return value === undefined || value === "" ? fallback : value;
}

// ---------------------------------------------------------------------------
// Backend gateway client
// ---------------------------------------------------------------------------

export class BackendGateway {
  constructor({ baseUrl, token, runId, userId, scope = "opportunity_research" }) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.token = token;
    this.runId = runId;
    this.userId = userId;
    this.scope = scope;
    this.toolCalls = [];
  }

  async fetchJson(path, { method = "GET", body } = {}) {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-Agent-Token": this.token,
        "User-Agent": USER_AGENT,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    let payload = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      payload = { raw: text.slice(0, 500) };
    }
    return { status: response.status, payload };
  }

  async listTools() {
    const scope = encodeURIComponent(this.scope);
    const { status, payload } = await this.fetchJson(`/api/agent/v1/tools?scope=${scope}`);
    if (status !== 200 || !Array.isArray(payload?.tools)) {
      throw new Error(`agent gateway /tools failed (HTTP ${status})`);
    }
    return payload.tools;
  }

  async executeTool(name, arguments_) {
    const { status, payload } = await this.fetchJson("/api/agent/v1/execute", {
      method: "POST",
      body: {
        run_id: this.runId, user_id: this.userId, tool: name,
        arguments: arguments_, tool_scope: this.scope,
      },
    });
    if (status === 404) {
      return { error: { code: "RUN_NOT_FOUND", message: "The discovery run no longer exists." } };
    }
    if (status !== 200) {
      const message = payload?.detail || payload?.error || `tool execute failed (HTTP ${status})`;
      // 402/409/429 are provider-level conditions the model can adapt to.
      const retryable = status === 429 || status >= 500;
      return { error: { code: `HTTP_${status}`, message, retryable } };
    }
    this.toolCalls.push({
      tool_name: name,
      status: payload?.status,
      cost_usd: payload?.stats?.cache_hit ? 0 : undefined,
    });
    return payload;
  }

  async reportProgress(event) {
    try {
      await this.fetchJson("/api/agent/v1/progress", {
        method: "POST",
        body: {
          run_id: this.runId,
          user_id: this.userId,
          event_type: event.event_type,
          stage: event.stage,
          detail: event.detail || "",
          funnel_stats: event.funnel_stats || {},
        },
      });
    } catch {
      // Progress reporting is best-effort; never abort research for it.
    }
  }
}

// ---------------------------------------------------------------------------
// Tool wrapping: backend OpenAI schema -> Pi AgentTool
// ---------------------------------------------------------------------------

export function wrapBackendTool(spec, gateway, limits, counters) {
  return {
    name: spec.function.name,
    label: spec.function.name,
    description: spec.function.description || spec.function.name,
    parameters: spec.function.parameters || { type: "object", properties: {} },
    async execute(_toolCallId, params) {
      const name = spec.function.name;
      if (name === "run_deep_web_research") {
        if (counters.deepResearch >= 1) {
          return {
            content: [{ type: "text", text: "Deep research budget exhausted: one deep run is allowed per discovery run. Continue with the evidence you already have." }],
            details: { budget_exhausted: true },
          };
        }
        counters.deepResearch += 1;
      } else if (/^search_/.test(name)) {
        if (counters.webSearches >= limits.max_web_search_calls) {
          return {
            content: [{ type: "text", text: `Web search budget exhausted (${limits.max_web_search_calls} calls). Continue with internal tools and the evidence you already have.` }],
            details: { budget_exhausted: true },
          };
        }
        counters.webSearches += 1;
      }
      const result = await gateway.executeTool(name, params);
      const text = formatToolResult(result);
      return { content: [{ type: "text", text }], details: { backend_result: result } };
    },
  };
}

export function formatToolResult(result) {
  if (!result) return "Tool returned an empty result.";
  if (result.error) {
    return `Tool error (${result.error.code || "unknown"}): ${result.error.message || "no message"}`;
  }
  // ToolExecutionResult envelope: prefer summary + compact data.
  const parts = [];
  if (result.summary) parts.push(`Summary: ${result.summary}`);
  if (result.data !== undefined && result.data !== null) {
    parts.push(`Data: ${safeJson(result.data)}`);
  }
  if (Array.isArray(result.sources) && result.sources.length) {
    parts.push(`Sources: ${safeJson(result.sources.slice(0, 20))}`);
  }
  if (Array.isArray(result.warnings) && result.warnings.length) {
    parts.push(`Warnings: ${safeJson(result.warnings.slice(0, 5))}`);
  }
  if (result.error) parts.push(`Error: ${result.error.message}`);
  return parts.join("\n") || safeJson(result);
}

export function safeJson(value) {
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

// ---------------------------------------------------------------------------
// Tool activity -> progress events
//
// The backend already maps event types to funnel stages, so reporting tool
// activity as it happens turns the two-event (started/finalized) progress
// stream into a live one — without ever exposing model reasoning. Only tool
// *names* are inspected; never message content.
// ---------------------------------------------------------------------------

const PORTFOLIO_TOOL_PATTERN = /^(get_portfolio_|get_position_|get_completed_trades|get_trade_statistics|get_dividend_history|get_fee_and_tax_summary|get_cash_flow_summary|get_currency_exposure)/;

const COMPANY_DATA_TOOLS = new Set([
  "get_company_snapshot", "get_company_profile", "get_company_peers",
  "get_latest_valuation", "get_valuation_history", "compare_valuations",
  "get_financial_summary", "get_financial_statements", "get_financial_trends",
  "compare_financial_metrics", "get_mood_overview", "get_latest_price",
  "get_price_history", "compare_price_performance",
]);

const EVIDENCE_TOOLS = new Set([
  "get_latest_news", "search_news", "get_news_detail", "get_news_archives",
  "get_sec_filings", "get_sec_filing_detail", "get_sec_events",
  "get_sec_financial_facts", "get_insider_trades", "get_institutional_holdings",
  "get_company_ownership_activity", "get_technical_analysis",
  "get_technical_levels", "compare_technical_signals",
  "get_technical_chart_reference", "get_calendar_events",
  "get_calendar_event_detail", "get_options_overview",
  "get_symbol_options_summary", "get_mood_history", "get_mood_validation",
]);

export function mapToolProgress(name) {
  if (name === "run_deep_web_research") {
    return { eventType: "external_search", stats: { deep_searches: 1 } };
  }
  if (/^search_/.test(name)) {
    return { eventType: "external_search", stats: { web_searches: 1 } };
  }
  if (PORTFOLIO_TOOL_PATTERN.test(name)) {
    return { eventType: "portfolio_loaded", stats: {} };
  }
  if (COMPANY_DATA_TOOLS.has(name)) {
    return { eventType: "candidate_screened", stats: {} };
  }
  if (EVIDENCE_TOOLS.has(name)) {
    return { eventType: "evidence_found", stats: {} };
  }
  return null; // unmapped (e.g. list_research_capabilities): counted, not reported
}

// Screening is counted per *symbol*, not per call: the agent legitimately
// pulls several company tools for the same candidate, and per-call counting
// inflated `candidates_screened` far beyond the real candidate pool.
export function extractToolSymbols(args) {
  const symbols = new Set();
  if (!args || typeof args !== "object") return symbols;
  const add = (value) => {
    if (typeof value === "string" && value.trim()) symbols.add(value.trim().toUpperCase());
  };
  add(args.symbol);
  add(args.ticker);
  for (const key of ["symbols", "tickers"]) {
    if (Array.isArray(args[key])) for (const item of args[key]) add(item);
  }
  return symbols;
}

// Batches cheap tool activity so a fast loop does not hammer /progress; paid
// events (web/deep search) and the first portfolio load are sent immediately.
// The backend merges funnel_stats additively, so every report only ever sends
// deltas and `reported` tracks what has already been counted server-side —
// finalize therefore cannot double-count earlier reports.
export class ProgressBridge {
  constructor(gateway, { intervalMs = 4000, now = () => Date.now() } = {}) {
    this.gateway = gateway;
    this.intervalMs = intervalMs;
    this.now = now;
    this.lastSentAt = 0;
    this.pendingStats = {};
    this.pendingEventType = null;
    this.hasPending = false;
    this.portfolioLoaded = false;
    this.screenedSymbols = new Set();
    this.reported = {};
    this.totals = { tool_calls: 0, web_searches: 0, deep_searches: 0 };
  }

  _addStats(target, stats) {
    for (const [key, value] of Object.entries(stats)) {
      target[key] = (target[key] || 0) + value;
    }
  }

  _send(eventType, detail, stats) {
    this.gateway.reportProgress({ event_type: eventType, detail, funnel_stats: stats });
    this._addStats(this.reported, stats);
    this.lastSentAt = this.now();
  }

  onAgentEvent(event) {
    if (event?.type === "tool_execution_start") {
      const name = String(event.toolName || "");
      if (COMPANY_DATA_TOOLS.has(name)) {
        for (const symbol of extractToolSymbols(event.args)) this.screenedSymbols.add(symbol);
      }
      return;
    }
    if (event?.type !== "tool_execution_end") return;
    const name = String(event.toolName || "");
    this.totals.tool_calls += 1;
    if (event.result?.details?.budget_exhausted) return; // stub answer, nothing really executed
    const mapped = mapToolProgress(name);
    if (!mapped) return;
    this._addStats(this.totals, mapped.stats);
    if (mapped.eventType === "portfolio_loaded") {
      if (this.portfolioLoaded) return;
      this.portfolioLoaded = true;
      this._send("portfolio_loaded", name, { tool_calls: 1 });
      return;
    }
    if (mapped.eventType === "external_search") {
      this._send("external_search", name, { ...mapped.stats, tool_calls: 1 });
      return;
    }
    this._addStats(this.pendingStats, { tool_calls: 1 });
    this.pendingEventType = mapped.eventType;
    this.hasPending = true;
    if (this.now() - this.lastSentAt >= this.intervalMs) this.flush();
  }

  flush() {
    if (!this.hasPending) return;
    const funnel_stats = { ...this.pendingStats };
    const screenedDelta = this.screenedSymbols.size - (this.reported.candidates_screened || 0);
    if (screenedDelta > 0) funnel_stats.candidates_screened = screenedDelta;
    this.pendingStats = {};
    this.hasPending = false;
    this._send(this.pendingEventType || "stage_update", "", funnel_stats);
  }

  finalize(detail = "result submitted") {
    this.flush();
    const totals = { ...this.totals, candidates_screened: this.screenedSymbols.size };
    const delta = {};
    for (const [key, value] of Object.entries(totals)) {
      const remaining = value - (this.reported[key] || 0);
      if (remaining > 0) delta[key] = remaining;
    }
    this._send("finalized", detail, delta);
  }
}

// Hard stop for the agent loop: max_turns is no longer just prompt text.
// One turn = one completed model round trip (`turn_end`); when the budget is
// exhausted the loop is aborted and the rescue turn forces a best-effort
// submit instead of failing the whole run.
export class TurnBudget {
  constructor(maxTurns) {
    this.maxTurns = Number(maxTurns) || 0;
    this.turns = 0;
    this.reached = false;
  }

  note(event) {
    if (event?.type !== "turn_end") return false;
    this.turns += 1;
    if (this.reached || this.maxTurns <= 0) return false;
    if (this.turns >= this.maxTurns) {
      this.reached = true;
      return true;
    }
    return false;
  }
}

// ---------------------------------------------------------------------------
// Provider setup: project OpenAI-compatible endpoint
// ---------------------------------------------------------------------------

function buildModels(modelIdOverride) {
  const baseUrl = env("OPENAI_BASE_URL", "https://api.openai.com/v1");
  const apiKey = env("OPENAI_API_KEY");
  const modelId = modelIdOverride || env("PI_AGENT_MODEL", "");
  if (!modelId) throw new Error("PI_AGENT_MODEL or request.model is required");
  if (!apiKey) throw new Error("OPENAI_API_KEY is not configured");
  const provider = createProvider({
    id: "stock-monitor",
    name: "stock-monitor OpenAI-compatible endpoint",
    baseUrl,
    auth: {
      apiKey: {
        name: "stock-monitor endpoint key",
        resolve: async () => ({ auth: { apiKey } }),
      },
    },
    models: [
      {
        id: modelId,
        name: modelId,
        api: "openai-completions",
        provider: "stock-monitor",
        baseUrl,
        reasoning: false,
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: Number(env("PI_AGENT_CONTEXT_WINDOW", 128000)),
        maxTokens: Number(env("PI_AGENT_MAX_OUTPUT_TOKENS", 32000)),
      },
    ],
    api: openAICompletionsApi(),
  });
  const models = createModels();
  models.setProvider(provider);
  return { models, model: models.getModel("stock-monitor", modelId) };
}

// ---------------------------------------------------------------------------
// Research run
// ---------------------------------------------------------------------------

export async function runAgentResearch({ request, backendBaseUrl, agentToken }) {
  const runId = Number(request.run_id);
  const userId = Number(request.user_id);
  if (!Number.isInteger(runId) || runId <= 0) throw new Error("run_id is required");
  if (!Number.isInteger(userId) || userId <= 0) throw new Error("user_id is required");
  const modelId = String(request.model || env("PI_AGENT_MODEL", "gpt-5.4"));
  const limits = {
    max_turns: Number(request.limits?.max_turns || 40),
    max_web_search_calls: Number(request.limits?.max_web_search_calls || 15),
    deep_effort: String(request.limits?.deep_effort || "medium"),
    max_output_tokens: Number(request.limits?.max_output_tokens || 12000),
    timeout_seconds: Number(request.limits?.timeout_seconds || 900),
  };

  const gateway = new BackendGateway({
    baseUrl: backendBaseUrl, token: agentToken, runId, userId,
    scope: String(request.tool_scope || "opportunity_research"),
  });
  await gateway.reportProgress({ event_type: "research_started", detail: "agent loop starting", funnel_stats: {} });
  const progress = new ProgressBridge(gateway);

  const backendTools = await gateway.listTools();
  const counters = { webSearches: 0, deepResearch: 0 };
  const tools = backendTools.map((spec) => wrapBackendTool(spec, gateway, limits, counters));

  let submitted = null;
  const submitTool = {
    name: "submit_discovery_result",
    label: "Submit discovery result",
    description:
      "Submit the final structured opportunity discovery result. This is your last action; the run ends after this call. Provide the complete DiscoveryResult JSON.",
    parameters: request.output_schema || { type: "object", additionalProperties: true },
    async execute(_toolCallId, params) {
      submitted = params;
      return { content: [{ type: "text", text: "Result submitted." }], details: {}, terminate: true };
    },
  };
  tools.push(submitTool);

  const { models, model } = buildModels(modelId);

  const events = [];
  const usageTotals = { input_tokens: 0, output_tokens: 0, total_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 };
  const toolResults = [];

  const agent = new Agent({
    initialState: {
      systemPrompt: String(request.system_prompt || "You are a stock research agent."),
      model,
      tools,
      messages: [
        {
          role: "user",
          content: [
            {
              type: "text",
              text: buildUserPrompt(request, limits),
            },
          ],
        },
      ],
    },
    streamFn: models.streamSimple.bind(models),
    toolExecution: "parallel",
  });

  const turnBudget = new TurnBudget(limits.max_turns);
  agent.subscribe((event) => {
    accumulateUsage(usageTotals, event);
    trackToolEvents(toolResults, events, event);
    progress.onAgentEvent(event);
    if (turnBudget.note(event)) {
      events.push({ event_type: "max_turns_reached", detail: `stopped after ${turnBudget.turns} turns` });
      abort.abort(new Error("max turns reached"));
    }
  });

  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(new Error("research timeout")), limits.timeout_seconds * 1000);

  try {
    await agent.prompt("Begin the research funnel now.", { signal: abort.signal });
  } catch (error) {
    // Best-effort rescue: if the model already submitted a result, use it.
    if (submitted) {
      events.push({ event_type: "run_aborted_after_submit", detail: String(error?.message || error) });
    } else if (turnBudget.reached) {
      // Turn budget exhausted mid-loop: fall through to the rescue turn that
      // forces a best-effort submit instead of wasting the whole run.
    } else {
      throw error;
    }
  } finally {
    clearTimeout(timer);
  }

  if (!submitted) {
    // Rescue turn: force a final answer from gathered evidence. Bounded so a
    // stalling model cannot hang the worker past the run budget.
    const rescueAbort = new AbortController();
    const rescueTimer = setTimeout(() => rescueAbort.abort(new Error("rescue timeout")), RESCUE_TIMEOUT_MS);
    try {
      await agent.prompt(
        "The research budget has been reached. Stop all tool calls and submit your best-effort result now using the submit_discovery_result tool with the evidence gathered so far. If evidence is insufficient for a field, use null.",
        { signal: rescueAbort.signal },
      );
    } catch (error) {
      events.push({ event_type: "rescue_failed", detail: String(error?.message || error) });
    } finally {
      clearTimeout(rescueTimer);
    }
  }

  if (!submitted) {
    const error = new Error("The agent finished without submitting a structured result.");
    error.retryable = false;
    progress.flush();
    throw error;
  }

  progress.finalize();

  return {
    status: "completed",
    result: submitted,
    output_text: "",
    model: modelId,
    tool_results: toolResults,
    events,
    usage: {
      input_tokens: usageTotals.input_tokens,
      output_tokens: usageTotals.output_tokens,
      total_tokens: usageTotals.total_tokens,
      web_search_calls: counters.webSearches,
      deep_search_calls: counters.deepResearch,
      tool_cost_usd: estimateToolCost(counters, gateway),
      model_cost_usd: 0,
      total_cost_usd: estimateToolCost(counters, gateway),
      model_endpoint: env("OPENAI_BASE_URL"),
    },
  };
}

export function buildUserPrompt(request, limits) {
  return [
    `Analysis date: ${new Date().toISOString().slice(0, 10)}`,
    "",
    "PORTFOLIO_CONTEXT (already loaded; call internal portfolio tools for details):",
    safeJson(request.context || {}),
    "",
    `Budgets: max ${limits.max_turns} turns, max ${limits.max_web_search_calls} web searches, at most 1 deep research call (${limits.deep_effort} effort).`,
    "Internal tools are free and preferred. Finish by calling submit_discovery_result with the full result JSON. Fields unavailable from evidence must be null, never invented.",
  ].join("\n");
}

export function accumulateUsage(totals, event) {
  const usage = event?.usage || event?.message?.usage;
  if (!usage) return;
  for (const key of Object.keys(totals)) {
    if (typeof usage[key] === "number") totals[key] += usage[key];
  }
}

export function trackToolEvents(toolResults, events, event) {
  const type = event?.type;
  if (type === "tool_execution_end") {
    toolResults.push({
      tool_name: event.toolName,
      status: event.isError ? "error" : "completed",
      tool_call_id: event.toolCallId,
    });
  }
  if (type === "agent_end") {
    events.push({ event_type: "agent_end", detail: `messages=${event.messages?.length ?? 0}` });
  }
}

function estimateToolCost(counters, gateway) {
  // Exa search ~$0.007/call; deep effort fixed cost handled by the backend
  // from actual provider reporting. This is the sidecar-side estimate only.
  return Number((counters.webSearches * 0.007).toFixed(6));
}
