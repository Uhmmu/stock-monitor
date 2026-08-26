from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# 全应用统一版本号。所有新的分析元数据（技术信号、价格区间、到达估计等）都引用它，
# 而不是各处硬编码字符串。analyzer / parameter_set / analysis_engine 三个版本目前都等于
# APP_VERSION，但在数据库里分开存储，方便将来单独演进。
APP_VERSION = "v0.4"
ANALYZER_VERSION = APP_VERSION
PARAMETER_SET_VERSION = APP_VERSION
ANALYSIS_ENGINE_VERSION = APP_VERSION


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://stock:stock@postgres:5432/stock_monitor"
    redis_url: str = "redis://redis:6379/0"
    tavily_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    model_simple: str = "gpt-5.4-mini"
    model_medium: str = "gpt-5.6-luna"
    model_important: str = "gpt-5.6-sol"
    translation_api_key: str = ""
    translation_base_url: str = "https://www.right.codes/claude-aws/v1"
    translation_model: str = "claude-haiku-4-5-20251001"
    translation_batch_size: int = 20
    translation_max_attempts: int = 3
    market_timezone: str = "America/New_York"
    price_poll_minutes: int = 5
    mood_eod_start_hour: int = 18
    mood_eod_finalize_hour: int = 23
    price_snapshot_provider_order: str = "alpaca,tiingo,finnhub,yfinance"
    price_snapshot_stale_seconds: int = 900
    # Industry/Sector Pulse is an independent, low-frequency daily pipeline.
    # Its provider order intentionally differs from live quote routing: the
    # calculation must prefer yfinance daily candles and only then fall back
    # to Finnhub historical candles.
    industry_pulse_enabled: bool = True
    industry_pulse_refresh_hours: int = 20
    industry_pulse_history_days: int = 500
    industry_pulse_backfill_days: int = 252
    industry_pulse_provider_timeout_seconds: float = 30.0
    industry_pulse_exposure_threshold: float = 0.30
    industry_pulse_constituent_confidence_threshold: float = 0.55
    industry_pulse_min_constituents: int = 5
    industry_pulse_min_effective_coverage: float = 0.60
    industry_pulse_single_stock_max_weight: float = 0.15
    industry_pulse_top_three_max_weight: float = 0.45
    industry_pulse_yfinance_batch_size: int = 50
    industry_pulse_propagation_history_days: int = 60
    industry_pulse_classification_batch_size: int = 30
    industry_pulse_metadata_hydrate_limit: int = 20
    industry_pulse_liquidity_floor: float = 0.05
    industry_pulse_sync_lock_seconds: int = 7200
    industry_pulse_ai_enabled: bool = True
    industry_pulse_score_weights: str = '{"trend":0.25,"relative_strength":0.25,"volume":0.15,"momentum":0.10,"breadth":0.15,"consensus":0.10}'
    # Bounded, low-frequency options analytics; only configured ETFs and the
    # enabled watchlist are eligible, never the full security universe.
    options_enabled: bool = True
    options_refresh_hours: int = 6
    options_provider_timeout_seconds: float = 20.0
    options_chain_cache_hours: int = 12
    options_sync_lock_seconds: int = 3600
    options_history_days: int = 365
    # Server-only realtime market data. Providers remain opt-in so missing
    # credentials never prevent the API, workers, or migrations from starting.
    alpaca_market_data_enabled: bool = False
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_trading_env: str = "paper"
    alpaca_trading_base_url: str = "https://paper-api.alpaca.markets"
    alpaca_market_data_base_url: str = "https://data.alpaca.markets"
    alpaca_market_data_stream_url: str = "wss://stream.data.alpaca.markets"
    alpaca_market_data_feed: str = "iex"
    alpaca_market_data_symbol_limit: int = 30
    tiingo_market_data_enabled: bool = False
    tiingo_api_token: str = ""
    tiingo_market_data_base_url: str = "https://api.tiingo.com"
    tiingo_market_data_stream_url: str = "wss://api.tiingo.com"
    tiingo_realtime_mode: str = "consolidated"  # consolidated / iex / auto
    realtime_provider_order: str = "alpaca,tiingo,finnhub,yfinance"
    realtime_quote_ttl_seconds: int = 180
    realtime_stale_seconds: int = 45
    realtime_subscription_refresh_seconds: int = 30
    realtime_price_divergence_warn_pct: float = 0.5
    realtime_stream_enabled: bool = False
    realtime_sse_heartbeat_seconds: int = 15
    realtime_event_cooldown_seconds: int = 300
    tiingo_news_enabled: bool = False
    tiingo_news_batch_size: int = 10
    tiingo_news_poll_minutes: int = 15
    tiingo_news_request_timeout_seconds: float = 15.0
    tiingo_news_lookback_hours: int = 48
    tiingo_news_limit: int = 100
    default_threshold_20m: float = 5.0
    default_threshold_1h: float = 5.0
    default_threshold_day: float = 5.0
    alert_cooldown_minutes: int = 60
    investigation_interval_minutes: int = 20
    investigation_duration_minutes: int = 120
    earnings_lookahead_days: int = 7
    finnhub_mcp_url: str = "http://finnhub-mcp:8125/mcp"
    finnhub_api_key: str = ""
    archive_dir: str = "/data/archive"
    news_poll_minutes: int = 15
    news_enrichment_batch_size: int = 20
    news_enrichment_max_attempts: int = 3
    news_relevance_threshold: float = 0.15
    marketaux_api_key: str = ""
    marketaux_enabled: bool = True
    marketaux_max_requests_per_day: int = 100
    marketaux_batch_size: int = 5
    market_news_enabled: bool = True
    finnhub_market_news_enabled: bool = True
    marketaux_market_news_enabled: bool = True
    market_news_poll_minutes: int = 60
    marketaux_market_requests_reserve: int = 12
    market_news_max_items: int = 20
    fmp_enabled: bool = True
    fmp_api_key: str = ""
    fmp_base_url: str = "https://financialmodelingprep.com/stable"
    fmp_news_batch_size: int = 10
    fmp_news_interval_seconds: int = 7200
    fmp_request_timeout_seconds: int = 15
    fmp_daily_call_limit: int = 200
    # FMP is restricted to cached company profiles and historical EOD prices.
    # Quota accounting resets on the UTC calendar day.
    fmp_daily_request_limit: int = 150
    fmp_request_reserve: int = 10
    fmp_sync_enabled: bool = True
    fmp_profile_sync_enabled: bool = True
    fmp_price_sync_enabled: bool = True
    fmp_translation_enabled: bool = True
    fmp_profile_refresh_days: int = 180
    technical_chart_dir: str = "/data/technical-charts"
    sec_user_agent: str = "stockMonitor/1.0 self-hosted@example.com"
    edgar_local_data_dir: str = "/data/edgar"
    sec_insider_heavy_sell_value: float = 1_000_000.0
    # 13F ticker→CUSIP 手动兜底覆盖，形如 "IREN:45840M108,ABC:012345678"
    sec_13f_cusip_overrides: str = ""
    # 13F 数据集下载页（运行时解析真实 zip 链接，避免猜文件命名）
    sec_13f_index_url: str = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
    # Manually triggered raw Perplexity Search API discovery. Search never performs
    # analysis; the configured important-tier OpenAI-compatible model does that.
    perplexity_api_key: str = ""
    perplexity_search_url: str = "https://api.perplexity.ai/search"
    perplexity_agent_url: str = "https://api.perplexity.ai/v1/agent"
    perplexity_agent_model: str = "openai/gpt-5.4"
    perplexity_max_steps: int = 5
    perplexity_max_output_tokens: int = 12000
    perplexity_enable_web_search: bool = True
    perplexity_max_monthly_budget_usd: float = 10.0
    perplexity_max_run_cost_usd: float = 1.0
    perplexity_request_timeout_seconds: int = 240
    perplexity_manual_refresh_cooldown_seconds: int = 60
    perplexity_evaluation_budget_usd: float = 2.0
    perplexity_live_evaluation_enabled: bool = False
    # Exa Agent is the deep-research discovery engine. Financial Datasets is
    # attached through Exa Connect; no separate provider credential is stored.
    exa_api_key: str = ""
    exa_agent_url: str = "https://api.exa.ai/agent/runs"
    exa_agent_beta: str = "agent-2026-05-07"
    exa_agent_effort: str = "high"
    exa_agent_poll_interval_seconds: float = 4.0
    exa_agent_timeout_seconds: int = 900
    # Pi Agent sidecar (discovery_mode="pi_agent"). The Node sidecar hosts the
    # research agent loop; it talks back to this backend over the internal
    # agent gateway with a shared service token (never exposed via nginx/Caddy).
    pi_agent_base_url: str = "http://pi-agent:3001"
    pi_agent_model: str = ""  # empty -> model_important
    pi_agent_max_turns: int = 40
    pi_agent_max_web_search_calls: int = 15
    pi_agent_deep_effort: str = "medium"  # minimal|low|medium|high|xhigh
    pi_agent_timeout_seconds: int = 900
    pi_agent_request_timeout_seconds: int = 960
    # Named capability scope resolved in app.ai_tools.scopes; the sidecar
    # passes it through on every /tools and /execute gateway call.
    pi_agent_tool_scope: str = "opportunity_research"
    agent_gateway_token: str = ""
    # Adanos is server-only. The browser calls the authenticated FastAPI proxy.
    adanos_api_key: str = ""
    adanos_api_keys: str = ""
    adanos_api_base_url: str = "https://api.adanos.org"
    adanos_proxy_url: str = ""
    adanos_request_timeout_seconds: float = 5.0

    # Crypto public market data (Binance Spot/USD-M). Public endpoints only;
    # there is no API-key setting by design. Collection jobs are additionally
    # gated by crypto_public_enabled so nothing runs before explicit setup.
    crypto_binance_spot_base_url: str = "https://api.binance.com"
    crypto_binance_usdm_base_url: str = "https://fapi.binance.com"
    crypto_binance_timeout_seconds: float = 15.0
    crypto_binance_max_retries: int = 2
    crypto_public_enabled: bool = False
    # Bounded collection universe: only these Binance symbols are synced as
    # instruments/candles. Comma-separated venue symbols per exact market.
    crypto_spot_universe: str = "BTCUSDT,ETHUSDT"
    crypto_usdm_universe: str = "BTCUSDT,ETHUSDT"
    # Candle backfill window and intervals for the bounded universe.
    crypto_candle_history_days: int = 365
    crypto_candle_sync_intervals: str = "1h,4h,1d"
    # Latest ticker cache (Redis, short TTL) with closed-candle fallback.
    crypto_latest_ttl_seconds: int = 60
    crypto_latest_stale_seconds: int = 180
    # Optional server-only CoinGecko enrichment.  Public access is keyless;
    # the key is sent only when explicitly configured and never reaches the
    # browser or Binance clients.
    crypto_coingecko_enabled: bool = False
    crypto_coingecko_base_url: str = "https://api.coingecko.com/api/v3"
    crypto_coingecko_api_key: str = ""
    crypto_coingecko_timeout_seconds: float = 15.0
    crypto_coingecko_max_retries: int = 2
    crypto_coingecko_refresh_hours: int = 24
    crypto_coingecko_universe: str = "bitcoin,ethereum"
    crypto_coingecko_manual_mappings: str = ""

    # Isolated, administrator-only, read-only IBKR integration test module.
    # Flex traffic is fail-closed through the loopback Xray/VLESS SOCKS5 proxy.
    ibkr_cp_enabled: bool = False
    ibkr_cp_base_url: str = "https://127.0.0.1:5000/v1/api"
    ibkr_cp_login_url: str = "https://localhost:5000"
    ibkr_cp_verify_ssl: bool = False
    ibkr_cp_connect_timeout_seconds: float = 5.0
    ibkr_cp_read_timeout_seconds: float = 30.0
    ibkr_username_hint: str = ""
    ibkr_credential_encryption_key: str = ""
    ibkr_login_browser_executable: str = "/usr/bin/chromium"
    ibkr_login_timeout_seconds: float = 150.0
    ibkr_flex_enabled: bool = False
    ibkr_flex_token: str = ""
    ibkr_flex_query_id: str = ""
    ibkr_flex_base_url: str = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
    ibkr_flex_timeout_seconds: float = 60.0
    ibkr_flex_auto_sync_enabled: bool = True
    ibkr_flex_auto_sync_interval_hours: int = 6
    ibkr_proxy_url: str = "socks5h://127.0.0.1:10808"

    # Server-only Alpha Vantage economic time-series integration.  The
    # provider is deliberately opt-in: missing credentials must not prevent
    # the rest of stock-monitor from starting.
    alpha_vantage_enabled: bool = False
    alpha_vantage_api_key: str = ""
    alpha_vantage_base_url: str = "https://www.alphavantage.co/query"
    alpha_vantage_daily_request_limit: int = 25
    alpha_vantage_reserved_requests: int = 3
    alpha_vantage_request_interval_seconds: float = 15.0
    alpha_vantage_timeout_seconds: float = 30.0
    alpha_vantage_max_retries: int = 3
    alpha_vantage_macro_sync_enabled: bool = True
    alpha_vantage_macro_sync_hour_utc: int = 8
    alpha_vantage_macro_history_refresh_days: int = 7

    # Read-only AI Tool Adapter layer. These limits are additionally clamped by
    # hard constants in app.ai_tools and never grant access to model providers.
    ai_tools_enabled: bool = True
    ai_tools_debug_api_enabled: bool = True
    ai_tools_batch_api_enabled: bool = True
    ai_tools_default_timeout_seconds: float = 15.0
    ai_tools_max_timeout_seconds: float = 30.0
    ai_tools_max_calls_per_batch: int = 12
    ai_tools_max_parallel_calls: int = 4
    ai_tools_compact_max_chars: int = 8000
    ai_tools_standard_max_chars: int = 24000
    ai_tools_detailed_max_chars: int = 60000
    ai_tools_hard_max_chars: int = 80000
    ai_tools_cache_enabled: bool = True
    ai_tools_audit_enabled: bool = True
    ai_tools_disabled_tools: str = ""

    # Stateless AI orchestrator. Missing credentials disable requests without
    # preventing the rest of the application from starting.
    ai_enabled: bool = True
    ai_provider: str = "openai_compatible"
    ai_model: str = "gpt-5.6-sol"
    # Empty means every assistant-compatible model configured by this project
    # (MODEL_*, TRANSLATION_MODEL, and the built-in GPT/Claude catalog). Set a
    # comma-separated value to explicitly restrict the assistant selector.
    ai_allowed_models: str = ""
    ai_api_base: str = ""
    ai_api_key: str = ""
    ai_request_timeout_seconds: float = 90.0
    ai_total_timeout_seconds: float = 120.0
    ai_connect_timeout_seconds: float = 15.0
    ai_max_retries: int = 2
    ai_max_model_rounds: int = 5
    ai_max_tool_calls: int = 12
    ai_max_tool_calls_per_round: int = 6
    ai_max_parallel_tool_calls: int = 4
    ai_max_context_chars: int = 180000
    ai_max_tool_result_chars: int = 80000
    ai_max_answer_chars: int = 30000
    ai_max_output_tokens: int = 6000
    ai_temperature: float | None = None
    ai_citation_repair_attempts: int = 1
    ai_tool_selection_max_tools: int = 18
    ai_tool_selection_hard_max_tools: int = 30
    ai_streaming_enabled: bool = True
    ai_non_streaming_enabled: bool = True
    ai_debug_api_enabled: bool = True
    ai_prefetch_portfolio_summary: bool = False

    # User-owned AI conversation persistence. Runtime cancellation is
    # intentionally process-local in this phase; deployments with multiple API
    # workers must move the registry to Redis before claiming distributed stop.
    ai_conversations_enabled: bool = True
    ai_conversation_history_max_messages: int = 16
    ai_conversation_history_max_chars: int = 60000
    ai_conversation_single_active_generation: bool = True
    ai_conversation_runtime_mode: str = "single_process"
    ai_conversation_partial_checkpoint_enabled: bool = False
    ai_conversation_partial_checkpoint_seconds: int = 3
    ai_conversation_soft_delete_enabled: bool = True
    ai_conversation_restore_enabled: bool = True
    ai_conversation_default_page_size: int = 30
    ai_conversation_max_page_size: int = 100
    ai_message_default_page_size: int = 50
    ai_message_max_page_size: int = 200

    # Versioned, deterministic rich responses. Models may only choose from
    # server-built block candidates; they never provide block payloads.
    ai_rich_content_enabled: bool = True
    ai_rich_content_schema_version: int = 1
    ai_rich_content_auto_insert_enabled: bool = True
    ai_rich_content_auto_insert_max_blocks: int = 2
    ai_rich_content_max_blocks_per_message: int = 6
    ai_rich_content_hard_max_blocks: int = 10
    ai_rich_content_max_document_chars: int = 100000
    ai_rich_content_max_block_data_chars: int = 30000
    ai_rich_content_max_chart_points: int = 500
    ai_rich_content_max_chart_series: int = 5
    ai_rich_content_max_table_rows: int = 100
    ai_rich_content_max_table_columns: int = 12
    ai_rich_content_max_timeline_items: int = 30
    ai_rich_content_max_news_sources: int = 10
    ai_rich_content_max_metrics: int = 16

    # Incremental conversation compression.
    ai_summary_enabled: bool = True
    ai_summary_automatic_enabled: bool = True
    ai_summary_provider: str = ""
    ai_summary_model: str = ""
    ai_summary_trigger_message_count: int = 20
    ai_summary_unsummarized_message_count: int = 8
    ai_summary_trigger_chars: int = 50000
    ai_summary_context_ratio: float = 0.70
    ai_summary_max_output_tokens: int = 2000
    ai_summary_timeout_seconds: float = 60.0
    ai_summary_max_retries: int = 1
    ai_summary_prompt_version: str = "1"
    ai_summary_max_snapshots_per_conversation: int = 10

    # User-controlled long-term memory. Inferred entries are proposals only.
    ai_memory_enabled: bool = True
    ai_memory_use_in_context: bool = True
    ai_memory_candidate_extraction_enabled: bool = True
    ai_memory_extraction_model: str = ""
    ai_memory_extraction_prompt_version: str = "1"
    ai_memory_explicit_save_requires_confirmation: bool = False
    ai_memory_max_candidates_per_message: int = 3
    ai_memory_max_active_items: int = 200
    ai_memory_context_max_items: int = 10
    ai_memory_context_max_chars: int = 6000
    ai_memory_sensitive_storage_enabled: bool = False

    # User-confirmed decision journal. It never executes a trade.
    ai_investment_decisions_enabled: bool = True
    # Decisions are extracted on explicit save so the model can summarize the
    # whole conversation before duplicate resolution. Regex auto-drafts remain
    # available only as a legacy opt-in.
    ai_investment_decision_draft_suggestions: bool = False
    ai_investment_decision_max_evidence: int = 30
    ai_investment_decision_review_due_enabled: bool = True

    # Server-owned Exa integration. Missing credentials disable only external
    # search; the stored-data assistant remains available.
    exa_enabled: bool = False
    exa_api_base: str = "https://api.exa.ai"
    exa_api_key: str = ""
    exa_search_enabled: bool = True
    exa_deep_search_enabled: bool = True
    exa_default_web_access_mode: str = "off"
    exa_search_default_type: str = "auto"
    exa_search_max_qps: float = 5.0
    exa_search_timeout_seconds: float = 30.0
    exa_search_max_retries: int = 2
    exa_search_default_results: int = 8
    exa_search_hard_max_results: int = 10
    exa_agent_timeout_seconds: float = 900.0
    exa_agent_poll_interval_seconds: float = 2.0
    exa_agent_max_concurrency: int = 2
    exa_deep_minimal_enabled: bool = True
    exa_deep_low_enabled: bool = True
    exa_deep_medium_enabled: bool = True
    exa_deep_high_enabled: bool = True
    exa_deep_xhigh_enabled: bool = True
    exa_deep_high_confirmation_required: bool = True
    exa_deep_xhigh_confirmation_required: bool = True
    exa_max_search_calls_per_ai_request: int = 3
    exa_max_cost_per_ai_request_usd: float = 1.25
    exa_max_cost_per_user_day_usd: float | None = None
    exa_deep_max_active_runs_per_user: int = 1
    exa_deep_max_active_runs_global: int = 2
    exa_deep_high_max_per_user_day: int | None = None
    exa_deep_xhigh_max_per_user_day: int | None = None
    exa_query_logging_enabled: bool = False
    exa_cache_enabled: bool = True
    exa_audit_enabled: bool = True
    exa_metrics_enabled: bool = True
    exa_blocked_domains: str = ""
    exa_trusted_media_domains: str = "reuters.com,bloomberg.com,apnews.com,ft.com,wsj.com,nikkei.com,cnbc.com"
    exa_allowed_roles: str = "user,admin"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
