import Foundation
import StockMonitorFeatures
import Testing

// MARK: - 路由绑定

@Test func goalM4RoutesAreBoundToNativeScreens() {
    for route in [AppRoute.fundamentals, .financials, .valuation, .compare, .sec, .congress, .technical, .macro, .industry, .options, .mood, .moodLab] {
        #expect(route.isGoalM4Route, "M4 路由 \(route.rawValue) 应绑定原生页面")
        #expect(!route.isGoalM3Route)
    }
    #expect(!AppRoute.overview.isGoalM4Route)
    #expect(!AppRoute.holdings.isGoalM4Route)
    #expect(!AppRoute.ai.isGoalM4Route)
}

// MARK: - M4.0 公司研究契约

@Test func fundamentalsContractDecodesMetricSourcesWithoutInventingValues() throws {
    let data = Data(#"""
    {"ticker":"NVDA","metrics":[
      {"label":"P/E","value":33.72,"source":"yahoo"},
      {"label":"P/B","value":null,"source":null}
    ],"rating":{"period":"2026-08","strongBuy":12,"buy":21,"hold":6,"sell":1,"strongSell":0},
    "as_of":"2026-09-05T21:00:00+00:00","data_mode":"live",
    "source_support":{"yahoo":true,"finnhub":false}}
    """#.utf8)
    let value = try JSONDecoder().decode(FundamentalsResponse.self, from: data)
    #expect(value.ticker == "NVDA")
    #expect(value.metrics[1].value == nil)
    #expect(value.metrics[1].source == nil)
    #expect(value.sourceSupport.yahoo)
    #expect(value.rating?.hold == 6)
}

@Test func crossModelFlattensEnvelopeAndKeepsRemainingFields() throws {
    let data = Data(#"""
    {"ticker":"AAPL","company":"Apple","valuation":[{"key":"dcf","label":"DCF","value":210.5,"unit":"USD/share","status":"available"}],
     "model_signals":[{"key":"dcf","label":"DCF（现金流折现）","verdict":"低估","stars":4,"detail":"现价低于 DCF Base"}],
     "consensus":{"items":[{"key":"dcf","label":"DCF Base","value":210.5}],"value":198.2,"current":183.0},
     "model_conflict":false,"graham":{"inputs":{"eps_ttm":{"value":6.2}},"applicability":{"status":"limited"}},
     "snapshot_date":"2026-09-05","generated_at":"2026-09-05T23:31:00+00:00","ai_model":null}
    """#.utf8)
    let value = try JSONDecoder().decode(ValuationCrossModel.self, from: data)
    #expect(value.snapshotDate == "2026-09-05")
    #expect(value.generatedAt?.hasPrefix("2026-09-05T23:31") == true)
    #expect(value.aiModel == nil)
    #expect(value.fields["graham"] != nil)
    #expect(!value.fields.keys.contains("snapshot_date"))
    let metrics = try value.fields["valuation"]?.decode(as: [CrossModelMetric].self)
    #expect(metrics?.first?.value == 210.5)
    let signals = try value.fields["model_signals"]?.decode(as: [CrossModelSignal].self)
    #expect(signals?.first?.stars == 4)
    let consensus = try value.fields["consensus"]?.decode(as: CrossModelConsensus.self)
    #expect(consensus?.current == 183.0)
}

@Test func valuationHistoryContractPreservesGapAndNegativeTtmSemantics() throws {
    let syncing = Data(#"""
    {"ticker":"1578.T","metric":"pe","range":"5y","status":"syncing"}
    """#.utf8)
    let syncingValue = try JSONDecoder().decode(ValuationHistoryResponse.self, from: syncing)
    #expect(syncingValue.status == "syncing")
    #expect(syncingValue.series.isEmpty)
    #expect(syncingValue.current == nil)

    let ready = Data(#"""
    {"ticker":"NVDA","metric":"pe","range":"5y","status":"ok",
     "current":{"price":120.4,"eps_ttm":3.57,"pe":33.7,"pe_status":"ok","as_of_date":"2026-09-04"},
     "statistics":{"mean":41.2,"median":39.8,"p25":31.0,"p75":51.4,"percentile":4.7,"vs_median_pct":-15.3,"valid_points":1180},
     "history":{"first_date":"2021-01-04","last_date":"2026-09-04","years_available":5.7},
     "series":[{"date":"2024-08-27","price":119.3,"eps_ttm":2.55,"pe":46.8},{"date":"2024-08-28","price":120.9,"eps_ttm":3.71,"pe":null}]}
    """#.utf8)
    let value = try JSONDecoder().decode(ValuationHistoryResponse.self, from: ready)
    #expect(value.status == "ok")
    #expect(value.current?.pe == 33.7)
    #expect(value.statistics?.percentile == 4.7)
    #expect(value.series.count == 2)
    #expect(value.series[1].pe == nil)
}

@Test func grahamOverrideRequestOnlyEncodesProvidedValues() throws {
    let request = GrahamOverrideRequest(growthRate: 9.0, aaaYield: nil, normalizedEps: 6.2)
    let object = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: Any])
    #expect(object["growth_rate"] as? Double == 9.0)
    #expect(object["normalized_eps"] as? Double == 6.2)
    #expect(object.keys.contains("aaa_yield") == false)
}

@Test func secContractsDecodePartialDataExplicitly() throws {
    let insider = Data(#"""
    [{"id":9,"insider_name":"Jensen Huang","insider_title":"CEO","transaction_date":"2026-09-02",
      "transaction_code":"S","shares":2400000,"price":119.5,"value":286800000,
      "shares_owned_after":20862717,"flag":null,"filing_url":"https://www.sec.gov/x"}]
    """#.utf8)
    let insiderRows = try JSONDecoder().decode([SecInsiderItem].self, from: insider)
    #expect(insiderRows.first?.flag == nil)
    #expect(insiderRows.first?.value == 286_800_000)

    let holdings = Data(#"""
    {"report_period":"2026-06-30","prev_period":"2026-03-31",
     "holdings":[{"id":1,"manager_name":"Vanguard","shares":1200000,"value_usd":2000000000,"put_call":"share",
                  "share_change":50000,"is_new":false,"filing_date":"2026-08-14"},
                 {"id":2,"manager_name":"New Fund","shares":90000,"value_usd":150000000,"put_call":"share",
                  "share_change":null,"is_new":true,"filing_date":"2026-08-14"}]}
    """#.utf8)
    let page = try JSONDecoder().decode(Sec13FPage.self, from: holdings)
    #expect(page.reportPeriod == "2026-06-30")
    #expect(page.holdings[0].shareChange == 50000)
    #expect(page.holdings[1].isNew == true)
    #expect(page.holdings[1].shareChange == nil)
}

@Test func financialStatementsPageCarriesQueryFrequency() throws {
    let rows = Data(#"""
    [{"fiscal_year":2025,"fiscal_period":"FY","period_end":"2025-09-30","currency":"USD",
      "income_statement":{"Total Revenue":416000000000},"balance_sheet":null,"cash_flow":null,
      "source":"yahoo","synced_at":"2026-09-05T03:00:00+00:00"}]
    """#.utf8)
    let decoded = try JSONDecoder().decode([FinancialStatementRow].self, from: rows)
    let page = FinancialStatementPage(frequency: "annual", rows: decoded)
    #expect(page.frequency == "annual")
    #expect(page.rows.first?.balanceSheet == nil)
    #expect(page.rows.first?.incomeStatement?.objectValue["Total Revenue"]?.numberValue == 416_000_000_000)
}

@Test func compareContractDecodesCellsRankingAndWarnings() throws {
    let data = Data(#"""
    {"securities":[{"symbol":"NVDA","name":"NVIDIA","sector":"Technology","industry":"Semiconductors",
                    "currency":"USD","instrument_type":"stock"}],
     "metrics":[{"definition":{"key":"roe_pct","label":"ROE","category":"盈利能力","unit":"%","format":"percent",
                  "source":"financial_statements","direction":"higher_better","sortable":true,
                  "supports_history":false,"tooltip":"净利润相对平均股东权益"},
       "cells":{"NVDA":{"value":91.2,"status":"available","source":"financial_statements","as_of":"2026-08-28",
                  "period":"FY2026","rank":1,"percentile":100.0,"relative_to_median":68.4,
                  "is_best":true,"is_worst":false,"trend":null,
         "relative":{"kind":"percent","value":68.4,"unit":"%"}}},
       "available_count":1,"dispersion":12.5,"is_differentiator":true,"period_mismatch":true,
       "comparison_warning":"财报期间不一致"}],
     "categories":["行情与表现"],
     "highlights":[{"symbol":"NVDA","strengths":[{"key":"roe_pct","label":"ROE"}],"weaknesses":[]}],
     "category_winners":[{"category":"盈利能力","symbol":"NVDA","ties":[],"evidence":null,"tradeoffs":null}],
     "suggested_peers":null,"limitations":["所有结果只读已持久化数据。"],
     "generated_at":"2026-09-05T12:00:00+00:00"}
    """#.utf8)
    let run = try JSONDecoder().decode(CompareRun.self, from: data)
    #expect(run.securities.first?.symbol == "NVDA")
    let row = try #require(run.metrics.first)
    #expect(row.cells["NVDA"]?.isBest == true)
    #expect(row.cells["NVDA"]?.relative?.value == 68.4)
    #expect(row.comparisonWarning != nil)
    #expect(run.categoryWinners.first?.symbol == "NVDA")
}

@Test func congressFigureDetailDecodesPercentPositionsAndMoves() throws {
    let data = Data(#"""
    {"slug":"cathie-wood","display_name":"Cathie Wood","kind":"fund_manager","photo_url":null,"note":"ARK 创始人",
     "is_seed":true,
     "positions":[{"ticker":"TSLA","asset_name":"Tesla","category":"equity","value":9.4,"is_percent":true,"note":null}],
     "positions_are_percent":true,
     "trades":[{"id":31,"filer_id":"F31","filer_name":"Cathie Wood","chamber":null,"party":null,"state":null,
                "ticker":"TSLA","asset_name":"Tesla","transaction_type":"buy","transaction_date":"2026-08-30",
                "filing_date":"2026-09-02","amount_label":"$1,001 - $15,000","is_late":false}],
     "moves":{"labels":["2026-08"],"datasets":[]}}
    """#.utf8)
    let value = try JSONDecoder().decode(CongressFigureDetail.self, from: data)
    #expect(value.positionsArePercent == true)
    #expect(value.positions.first?.value == 9.4)
    #expect(value.trades.first?.isLate == false)
    #expect(value.moves != nil)
}

// MARK: - M4.1 技术分析契约

@Test func technicalAnalysisContractDecodesChartSeriesAndContext() throws {
    let data = Data(#"""
    {"symbol":"AAPL","status":"ready","company_name":"Apple","logo_url":null,
     "analysis":{"source":"fmp","trend":"up"},"data_through":"2026-09-04","generated_at":"2026-09-05T01:00:00+00:00",
     "stale":false,"chart_url":null,
     "profile":{"symbol":"AAPL","status":"ready","company_name":"Apple","sector":"Technology","currency":"USD"},
     "chart_data_status":"ready","chart_data_reason":null,"chart_data_source":"fmp",
     "chart_series":{
       "day":{"candles":[{"time":"2026-09-03","open":182.1,"high":183.9,"low":181.7,"close":183.2,"volume":42100000},
                          {"time":"2026-09-04","open":183.4,"high":184.6,"low":182.9,"close":184.1,"volume":38500000}],
              "moving_averages":{"ma20":[{"time":"2026-09-04","value":181.9}],"ma50":[{"time":"2026-09-04","value":178.4}]}},
       "week":{"candles":[],"moving_averages":{"ma20":[],"ma50":[]}},
       "month":{"candles":[],"moving_averages":{"ma20":[],"ma50":[]}}},
     "events":[{"id":"earnings:88","time":"2026-09-25","type":"earnings","label":"财报","title":"Q4 财报","href":"/?tab=calendar&symbol=AAPL"}],
     "portfolio_cost":null,
     "price_alerts":[{"id":5,"ticker":"AAPL","target_price":200.0,"direction":"above","enabled":true,"triggered_at":null,"created_at":"2026-08-01T10:00:00+00:00"}],
     "data_status":{"source":"fmp","oldest_stored_date":"2021-07-26","latest_stored_date":"2026-09-04","profile_status":"ready","analysis_status":"ready"}}
    """#.utf8)
    let value = try JSONDecoder().decode(TechnicalAnalysisDetail.self, from: data)
    #expect(value.chartDataStatus == "ready")
    let day = try #require(value.chartSeries?["day"])
    #expect(day.candles.count == 2)
    #expect(day.movingAverages["ma20"]?.first?.value == 181.9)
    #expect(value.events?.first?.type == "earnings")
    #expect(value.portfolioCost == nil)
    #expect(value.priceAlerts?.first?.targetPrice == 200.0)
}

@Test func priceAlertRequestEncodesServerFieldNames() throws {
    let request = TechnicalPriceAlertRequest(targetPrice: 199.99, direction: "below")
    let object = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: Any])
    #expect(object["target_price"] as? Double == 199.99)
    #expect(object["direction"] as? String == "below")
}

@Test func chartPreparationSortsNormalizesAndDownsamples() {
    let candles = [
        ChartCandle(time: "2026-09-04T00:00:00+00:00", open: 1, high: 2, low: 0.5, close: 1.5, volume: 10),
        ChartCandle(time: "2026-09-02", open: 1, high: 2, low: 0.5, close: 1.2, volume: 10),
        ChartCandle(time: "2026-09-03", open: 1, high: 2, low: 0.5, close: 1.3, volume: 10),
    ]
    let timed = CandlePreparation.timedCandles(from: candles)
    #expect(timed.count == 3)
    #expect(timed.map(\.date) == timed.map(\.date).sorted())
    #expect(timed.first?.candle.close == 1.2)

    var many: [ChartCandle] = []
    for index in 0 ..< 1500 {
        let day = String(format: "2024-%02d-%02d", (index / 28) % 12 + 1, index % 28 + 1)
        many.append(ChartCandle(time: day, open: 1, high: 2, low: 0.5, close: Double(index), volume: 1))
    }
    let prepared = CandlePreparation.timedCandles(from: many)
    let sampled = CandlePreparation.downsample(prepared, budget: 420)
    #expect(sampled.count <= 421)
    #expect(sampled.first == prepared.first)
    #expect(sampled.last == prepared.last)
    #expect(sampled == sampled.sorted { $0.date < $1.date })
}

@Test func chartPreparationDerivesLevelsFromVisibleWindow() {
    var candles: [ChartCandle] = []
    for index in 0 ..< 40 {
        let close = index % 2 == 0 ? Double(index) : Double(index) - 0.5
        candles.append(ChartCandle(time: "2026-08-\(String(format: "%02d", index % 28 + 1))", open: close - 1, high: close + 1, low: close - 2, close: close, volume: 1))
    }
    let timed = CandlePreparation.timedCandles(from: candles)
    let levels = CandlePreparation.swingLevels(in: timed)
    #expect(!levels.isEmpty)
    #expect(levels == levels.sorted())
    let fibonacci = CandlePreparation.fibonacciLevels(in: timed)
    #expect(fibonacci.count == 7)
    #expect(fibonacci[0].price > fibonacci[6].price)
    #expect(abs(fibonacci[3].ratio - 0.5) < 0.001)
}

// MARK: - M4.2 市场情报契约

@Test func macroContractsDecodeSeriesAndCurve() throws {
    let seriesRow = Data(#"""
    {"series_key":"us_cpi","name_zh":"美国 CPI","name_en":"US CPI","definition":"消费者价格指数",
     "current":{"observation_date":"2026-08-01","value":320.5,"is_derived":false},"previous":null,
     "observation_date":"2026-08-01","last_fetched_at":"2026-09-01T08:00:00+00:00",
     "data_status":"available","freshness":{"status":"healthy","label_zh":"正常"},"trend":null}
    """#.utf8)
    let row = try JSONDecoder().decode(MacroSeriesRow.self, from: seriesRow)
    #expect(row.id == "us_cpi")
    #expect(row.current?.objectValue["value"]?.numberValue == 320.5)

    let curve = Data(#"""
    {"maturities":["1M","3M","6M","1Y","2Y","5Y","10Y","30Y"],
     "curves":[{"label":"最新","observation_date":"2026-09-04",
                "points":[{"maturity":"1M","value":4.02},{"maturity":"30Y","value":4.55}]}],
     "spreads":{"10y_2y":0.0021},"analysis":null,
     "disclaimer":"仅为规则化市场环境摘要，不构成投资建议。"}
    """#.utf8)
    let value = try JSONDecoder().decode(MacroYieldCurve.self, from: curve)
    #expect(value.maturities.count == 8)
    #expect(value.curves.first?.points.first?.value == 4.02)
    #expect(value.disclaimer?.contains("不构成投资建议") == true)
}

@Test func industryPulseOverviewDecodesRankingAndHistory() throws {
    let data = Data(#"""
    {"as_of":"2026-09-04","range_days":30,"status":"ready",
     "sectors":[{"node_id":1,"node_key":"technology","name":"Technology","name_zh":"科技","trading_date":"2026-09-04",
       "pulse":72.4,"mood":"LEADERSHIP","regime":null,"heat":68.0,"risk":31.0,
       "change_1d":0.82,"change_5d":2.31,"change_20d":-1.2,"rank":1,"confidence":0.92,"coverage_quality":0.88,
       "direction":"up","proxy_mode":"DIRECT_ETF","constituent_count":9,"calculation_status":"READY",
       "history":[{"trading_date":"2026-09-03","pulse":70.1},{"trading_date":"2026-09-04","pulse":72.4}],
       "proxy_etfs":["XLK"],"components":null,"breadth":null},
      {"node_id":2,"node_key":"utilities","name":"Utilities","name_zh":"公用事业","pulse":null,
       "calculation_status":"INSUFFICIENT_COVERAGE","history":[],"proxy_etfs":[]}]}
    """#.utf8)
    let value = try JSONDecoder().decode(IndustryPulseOverview.self, from: data)
    #expect(value.status == "ready")
    #expect(value.sectors[0].pulse == 72.4)
    #expect(value.sectors[0].history?.count == 2)
    #expect(value.sectors[1].pulse == nil)
    #expect(value.sectors[1].calculationStatus == "INSUFFICIENT_COVERAGE")
}

@Test func optionsOverviewDecodesRankingsAndQuality() throws {
    let data = Data(#"""
    {"status":"ready","as_of":"2026-09-05T20:00:00+00:00",
     "market":[{"symbol":"NVDA","asset_type":"stock","status":"ready","provider":"tiingo",
                "quality":{"level":"HIGH","score":0.94,"coverage":0.98,"warnings":[]},"atm_iv":48.2,"put_call_volume_ratio":0.71}],
     "sectors":[{"sector":"Technology"}],
     "watchlist":[],
     "rankings":{"most_active":[{"symbol":"NVDA","activity_percentile":99.1,"quality":{"level":"MEDIUM","score":0.6,"coverage":0.7,"warnings":["partial_chain"]}}]},
     "sync":null,"limitations":["Secondary ETF signals remain distinct."]}
    """#.utf8)
    let value = try JSONDecoder().decode(OptionsOverview.self, from: data)
    #expect(value.market.first?.atmIv == 48.2)
    #expect(value.rankings["most_active"]?.first?.activityPercentile == 99.1)
    #expect(value.rankings["most_active"]?.first?.quality?.warnings?.first == "partial_chain")
}

@Test func moodOverviewAndHistoryHealthDecodeStates() throws {
    let overview = Data(#"""
    {"as_of":"2026-09-05","status":"ready","calculation_version":"mood_v1",
     "market":{"id":1,"scope_type":"market","scope_key":"US","trading_date":"2026-09-05","name":"US Market","name_zh":"美国市场",
       "state":"NEUTRAL","direction":"flat","mood_score":52.0,"confidence":0.81,"coverage":0.9,"freshness_status":"HEALTHY"},
     "sectors":[{"id":2,"scope_type":"sector","scope_key":"technology","trading_date":"2026-09-05","state":"LEADERSHIP","direction":"up","mood_score":78.3}],
     "industries":[],"ai_chain":[],"watchlist":[],
     "movers":{"improving":[]},"divergences":[],"transitions":[],"limitations":["Whole-market breadth is unavailable."],
     "report":null,"report_sections":[],"market_window":null,"range_days":20}
    """#.utf8)
    let value = try JSONDecoder().decode(MoodOverview.self, from: overview)
    #expect(value.rangeDays == 20)
    #expect(value.market?.state == "NEUTRAL")
    #expect(value.sectors.first?.moodScore == 78.3)
    #expect(value.limitations?.first?.contains("breadth") == true)

    let health = Data(#"""
    {"health_status":"HEALTHY","latest_eod":"2026-09-05","oldest_eod":"2026-01-02","history_days":160,
     "complete_days":150,"partial_days":3,"run":{"trading_date":"2026-09-05","status":"COMPLETED"},
     "calendar":[],"warnings":[],"maturity":{"matured_1d_samples":120}}
    """#.utf8)
    let healthValue = try JSONDecoder().decode(MoodHistoryHealth.self, from: health)
    #expect(healthValue.healthStatus == "HEALTHY")
    #expect(healthValue.completeDays == 150)
}

@Test func moodLabContractsDecodeRunsAndEncodeRequests() throws {
    let run = Data(#"""
    {"run_id":12,"status":"completed","progress":1.0,"created_at":"2026-09-05T09:00:00+00:00",
     "started_at":"2026-09-05T09:00:05+00:00","completed_at":"2026-09-05T09:06:00+00:00",
     "engine_version":"engine_v1","calculation_version":"mood_v1","validation_version":"val_v2",
     "parameter_set":null,"date_from":"2026-01-01","date_to":"2026-09-01","data_cutoff":"2026-09-01",
     "scope_filter":["market","sector"],"benchmark_config":null,"forward_horizons":[1,5,20],
     "coverage":{"scopes":4},"warnings":[],"error_message":null,"queued":true,"task_id":"abc123"}
    """#.utf8)
    let runValue = try JSONDecoder().decode(MoodValidationRun.self, from: run)
    #expect(runValue.runID == 12)
    #expect(runValue.queued == true)
    #expect(runValue.progress == 1.0)

    let request = MoodValidationRunRequest(
        dateFrom: "2026-01-01", dateTo: nil,
        scopes: ["market", "sector", "ai_chain", "watchlist"],
        horizons: [1, 5, 10, 20, 60]
    )
    let object = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: Any])
    #expect(object["date_from"] as? String == "2026-01-01")
    #expect(object.keys.contains("date_to") == false)
    #expect((object["horizons"] as? [Int])?.count == 5)

    let recovery = MoodRecoveryRequest(tradingDate: "2026-09-01", scopes: ["market"], reason: "补齐缺口")
    let recoveryObject = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(recovery)) as? [String: Any])
    #expect(recoveryObject["trading_date"] as? String == "2026-09-01")
    #expect(recoveryObject["reason"] as? String == "补齐缺口")
}
