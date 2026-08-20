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

function env(name, fallback = "") {
  const value = process.env[name];
  return value === undefined || value === "" ? fallback : value;
}

// ---------------------------------------------------------------------------
// Backend gateway client
// ---------------------------------------------------------------------------

export class BackendGateway {
  constructor({ baseUrl, token, runId, userId }) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.token = token;
    this.runId = runId;
    this.userId = userId;
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
    const { status, payload } = await this.fetchJson("/api/agent/v1/tools");
    if (status !== 200 || !Array.isArray(payload?.tools)) {
      throw new Error(`agent gateway /tools failed (HTTP ${status})`);
    }
    return payload.tools;
  }

  async executeTool(name, arguments_) {
    const { status, payload } = await this.fetchJson("/api/agent/v1/execute", {
      method: "POST",
      body: { run_id: this.runId, user_id: this.userId, tool: name, arguments: arguments_ },
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

  const gateway = new BackendGateway({ baseUrl: backendBaseUrl, token: agentToken, runId, userId });
  await gateway.reportProgress({ event_type: "research_started", detail: "agent loop starting", funnel_stats: {} });

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

  agent.subscribe((event) => {
    accumulateUsage(usageTotals, event);
    trackToolEvents(toolResults, events, event);
  });

  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(new Error("research timeout")), limits.timeout_seconds * 1000);

  try {
    await agent.prompt("Begin the research funnel now.", { signal: abort.signal });
  } catch (error) {
    // Best-effort rescue: if the model already submitted a result, use it.
    if (!submitted) {
      throw error;
    }
    events.push({ event_type: "run_aborted_after_submit", detail: String(error?.message || error) });
  } finally {
    clearTimeout(timer);
  }

  if (!submitted) {
    // Rescue turn: force a final answer from gathered evidence.
    try {
      await agent.prompt(
        "The research budget has been reached. Stop all tool calls and submit your best-effort result now using the submit_discovery_result tool with the evidence gathered so far. If evidence is insufficient for a field, use null.",
        { signal: AbortSignal.any ? AbortSignal.any([]) : undefined },
      );
    } catch (error) {
      events.push({ event_type: "rescue_failed", detail: String(error?.message || error) });
    }
  }

  if (!submitted) {
    const error = new Error("The agent finished without submitting a structured result.");
    error.retryable = false;
    throw error;
  }

  await gateway.reportProgress({ event_type: "finalized", detail: "result submitted", funnel_stats: {} });

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
