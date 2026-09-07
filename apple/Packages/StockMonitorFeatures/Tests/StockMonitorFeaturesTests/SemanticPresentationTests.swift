import Foundation
import StockMonitorDesign
@testable import StockMonitorFeatures
import Testing

// MARK: - R2.0 typed presentation contract fixtures

/// 断言展示层不再向用户暴露 snake_case 字段名。
private func assertNoSnakeCase(_ labels: [String], source: String) {
    for label in labels {
        #expect(
            label.range(of: #"[a-z]_[a-z]"#, options: .regularExpression) == nil,
            "\(source) 泄漏了服务端字段名：\(label)"
        )
    }
}

private func decode(_ json: String) throws -> JSONValue {
    try JSONDecoder().decode(JSONValue.self, from: Data(json.utf8))
}

@Test func portfolioSummaryPresentationMapsSummaryMetricsAndPositionsList() throws {
    let payload = try decode(
        #"""
        {
          "base_currency": "USD",
          "position_count": 2,
          "priced_count": 2,
          "total_market_value": 251234.56,
          "total_cost": 180000.0,
          "total_unrealized_pnl": 71234.56,
          "total_unrealized_pnl_percent": 0.3957,
          "data_completeness": 0.94,
          "latest_sync_at": "2026-09-08T02:31:00Z",
          "account_data_source": "ibkr_flex",
          "mystery_field": "should-go-to-diagnostics",
          "positions": [
            {"symbol": "NVDA", "currency": "USD", "total_quantity": 120.5, "current_price": 234.12,
             "base_currency_market_value": 28211.46, "base_currency_unrealized_pnl": 6120.10, "portfolio_weight": 0.45},
            {"symbol": "1578.T", "currency": "JPY", "total_quantity": 20, "current_price": 5100.0,
             "base_currency_market_value": 680.20, "base_currency_unrealized_pnl": 45.30, "portfolio_weight": 0.02}
          ]
        }
        """#
    )
    let presentation = SemanticPresentationBuilder.presentation(
        title: "组合摘要",
        spec: GoalM5PresentationCatalog.spec(semanticKey: "portfolio.summary"),
        payload: payload
    )

    #expect(!presentation.isEmpty)
    #expect(presentation.baseCurrency == "USD")
    let summaryLabels = presentation.summary.map(\.label)
    #expect(summaryLabels.contains("总市值（基础币种）"))
    #expect(summaryLabels.contains("总浮动盈亏"))
    assertNoSnakeCase(summaryLabels, source: "portfolio.summary summary")
    let totalValue = presentation.summary.first { $0.key == "total_market_value" }
    #expect(totalValue?.display.text.contains("USD") == true)

    let list = try #require(presentation.list)
    #expect(list.total == 2)
    #expect(list.columns.first?.label == "代码")
    assertNoSnakeCase(list.columns.map(\.label), source: "portfolio.summary columns")
    #expect(list.rows.first?.identity == "NVDA")
    #expect(presentation.diagnostics.contains("mystery_field"))
    #expect(presentation.provenance.contains { $0.label == "账户数据来源" })
}

@Test func bareArrayEndpointsPresentAsSemanticLists() throws {
    let positions = try decode(
        #"""
        [{"symbol":"AAPL","currency":"USD","total_quantity":10,"current_price":224.5,
          "base_currency_market_value":2245.0,"base_currency_unrealized_pnl":120.0,"portfolio_weight":0.31},
         {"symbol":"MSFT","currency":"USD","total_quantity":5,"current_price":412.2,
          "base_currency_market_value":2061.0,"base_currency_unrealized_pnl":-40.0,"portfolio_weight":0.29}]
        """#
    )
    let positionsPresentation = SemanticPresentationBuilder.presentation(
        title: "持仓", spec: GoalM5PresentationCatalog.spec(semanticKey: "portfolio.positions"), payload: positions
    )
    #expect(positionsPresentation.list?.rows.count == 2)
    #expect(positionsPresentation.list?.columns.first?.label == "代码")

    let users = try decode(
        #"""
        [{"id":1,"username":"jiale","role":"admin","status":"active","created_at":"2026-05-01T10:00:00Z","note":null},
         {"id":2,"username":"reader","role":"user","status":"active","created_at":"2026-06-11T08:00:00Z","note":"只读"}]
        """#
    )
    let usersPresentation = SemanticPresentationBuilder.presentation(
        title: "用户", spec: GoalM5PresentationCatalog.spec(semanticKey: "admin.users"), payload: users
    )
    let columns = usersPresentation.list?.columns.map(\.label) ?? []
    #expect(columns.contains("用户名"))
    #expect(columns.contains("角色"))
    assertNoSnakeCase(columns, source: "admin.users columns")
    #expect(usersPresentation.list?.rows.first?.identity == "jiale")
}

@Test func paginatedEndpointsUnwrapItemsIntoLists() throws {
    let payload = try decode(
        #"""
        {"items":[{"id":41,"status":"completed","strategy_key":"dual_ma","interval":"1h","created_at":"2026-09-01T12:00:00Z"},
                  {"id":42,"status":"running","strategy_key":"dual_ma","interval":"1h","created_at":"2026-09-07T09:00:00Z"}],
         "total":2,"limit":50,"offset":0}
        """#
    )
    let presentation = SemanticPresentationBuilder.presentation(
        title: "回测", spec: GoalM5PresentationCatalog.spec(semanticKey: "quant.backtests"), payload: payload
    )
    let list = try #require(presentation.list)
    #expect(list.total == 2)
    assertNoSnakeCase(list.columns.map(\.label), source: "quant.backtests columns")
    // 分页包装键不进入诊断（被显式消费）
    #expect(!presentation.diagnostics.contains("total"))
    #expect(!presentation.diagnostics.contains("offset"))
}

@Test func cryptoStringPricesAreParsedAndSummarized() throws {
    let payload = try decode(
        #"""
        {"instrument_id":1,"display_label":"BTCUSDT","source":"ticker_cache","stale":false,
         "last_price":"80360.10","high_price_24h":"81200.50","low_price_24h":"79100.00",
         "quote_volume_24h":"1520000000.5","age_seconds":42,"warning":null}
        """#
    )
    let presentation = SemanticPresentationBuilder.presentation(
        title: "最新行情", spec: GoalM5PresentationCatalog.spec(semanticKey: "crypto.latest"), payload: payload
    )
    let last = presentation.summary.first { $0.key == "last_price" }
    #expect(last?.display.text.contains("80,360.1") == true)
    let age = presentation.summary.first { $0.key == "age_seconds" }
    #expect(age?.display.text == "42 秒")
    assertNoSnakeCase(presentation.summary.map(\.label), source: "crypto.latest summary")
}

@Test func ibkrStatusSectionsAndJobPhaseStaySemantic() throws {
    let payload = try decode(
        #"""
        {"configured":true,"read_only":true,
         "latest_sync":{"id":3,"account_id_masked":"***1234","status":"completed","stage":"done",
                        "trigger_type":"manual","warning_count":0,
                        "section_counts":{"Trade":[{"Blotter":120}]}},
         "current_or_last_attempt":{"id":3,"status":"completed"}}
        """#
    )
    let presentation = SemanticPresentationBuilder.presentation(
        title: "状态", spec: GoalM5PresentationCatalog.spec(semanticKey: "ibkr.status"), payload: payload
    )
    #expect(presentation.sections.contains { $0.title == "最近同步运行" })
    let summaryLabels = presentation.summary.map(\.label)
    #expect(summaryLabels.contains("只读模式"))
    assertNoSnakeCase(summaryLabels + presentation.sections.map(\.title), source: "ibkr.status")
}

@Test func discoveryLatestMapsSummaryRunAndLimitations() throws {
    let payload = try decode(
        #"""
        {"current_run":{"id":14,"status":"completed","discovery_mode":"pi_agent",
                        "progress":100,"requested_at":"2026-08-21T10:00:00Z","completed_at":"2026-08-21T10:07:01Z"},
         "result":{"counts":{"raw":13,"accepted":8},"limitations":["候选由模型生成，需自行核实"],
                   "groups":[{"id":1,"name":"AI 电力链","candidates":[]}],"usage":{"total_cost_usd":0.34686}},
         "using_previous_result":false,"api_key_configured":true,"discovery_mode":"pi_agent",
         "monthly_spend_usd":3.82,"monthly_budget_usd":10.0}
        """#
    )
    let presentation = SemanticPresentationBuilder.presentation(
        title: "最新结果", spec: GoalM5PresentationCatalog.spec(semanticKey: "discovery.latest"), payload: payload
    )
    #expect(presentation.summary.contains { $0.key == "monthly_budget_usd" && $0.display.text.contains("USD 10") })
    #expect(presentation.sections.contains { $0.key == "current_run" })
    #expect(presentation.sections.contains { $0.key == "result" })
    #expect(presentation.limitations == ["候选由模型生成，需自行核实"])
    #expect(presentation.jobPhase == .completed)
}

@Test func paperAccountAndOrdersStayInsidePaperBoundary() throws {
    let account = try decode(
        #"""
        {"account":{"id":9,"status":"active","execution_mode":"PAPER","base_currency":"USDT",
                    "cash":"1000.00","nav":"1015.20","equity":"1015.20","gross_exposure":"15.20",
                    "exposure_ratio":0.015,"positions":[],"performance":{"win_rate":0.62}}}
        """#
    )
    let accountPresentation = SemanticPresentationBuilder.presentation(
        title: "账户", spec: GoalM5PresentationCatalog.spec(semanticKey: "paper.account"), payload: account
    )
    #expect(accountPresentation.sections.contains { $0.title == "账户" })
    assertNoSnakeCase(accountPresentation.sections.map(\.title), source: "paper.account")

    let orders = try decode(
        #"""
        {"items":[{"id":7,"instrument_symbol":"BTCUSDT","side":"buy","status":"filled",
                   "intended_quantity":"0.124","avg_fill_price":"80360.10","fee":"4.98"}],
         "total":1,"limit":50,"offset":0}
        """#
    )
    let ordersPresentation = SemanticPresentationBuilder.presentation(
        title: "订单", spec: GoalM5PresentationCatalog.spec(semanticKey: "paper.orders"), payload: orders
    )
    let columns = ordersPresentation.list?.columns.map(\.label) ?? []
    #expect(columns.contains("方向"))
    #expect(columns.contains("成交均价"))
    assertNoSnakeCase(columns, source: "paper.orders columns")
}

@Test func everyCatalogEndpointResolvesASemanticSpecAndStaysOffRawJSON() {
    let catalog = GoalM5Catalog()
    let descriptors = [
        catalog.decisions, catalog.discovery, catalog.portfolio, catalog.journal,
        catalog.ibkr, catalog.ibkrAdmin, catalog.cryptoResearch, catalog.quant,
        catalog.paper, catalog.settings, catalog.administration,
    ]
    var semanticKeys = Set<String>()
    for endpoint in descriptors.flatMap(\.endpoints) {
        #expect(endpoint.semantic != nil, "端点缺少 semantic key：\(endpoint.title) \(endpoint.path)")
        if let key = endpoint.semantic {
            semanticKeys.insert(key)
        }
        // resolving 后 semantic key 必须保留（用于详情页）。
        let resolved = endpoint.resolving(["run_id": "5", "candidate_id": "5", "history_id": "5", "job_id": "5", "instrument_id": "2", "asset_id": "2"])
        #expect(resolved.semantic == endpoint.semantic)
    }
    for key in semanticKeys {
        let spec = GoalM5PresentationCatalog.spec(semanticKey: key)
        let domain = GoalM5PresentationCatalog.domain(for: key)
        #expect(domain != nil, "semantic key 没有对应业务域：\(key)")
        #expect(spec.domain == domain)
        #expect(spec.emptyHint?.isEmpty == false, "spec 缺少中文空态提示：\(key)")
    }
}

@Test func endpointDetailPresentationSurvivesUnresolvablePlaceholders() throws {
    // 详情端点在 ID 无效时通常返回 404/错误；数据为空对象时也必须给出语义空态而不是 JSON 树。
    let empty = try decode(#"{}"#)
    let presentation = SemanticPresentationBuilder.presentation(
        title: "运行详情", spec: GoalM5PresentationCatalog.spec(semanticKey: "discovery.run-detail"), payload: empty
    )
    #expect(presentation.isEmpty)
    #expect(presentation.emptyHint == "运行不存在。")
}

// MARK: - R2.1 字段目录与证据分层

@Test func everyDomainCatalogHasEntriesAndBusinessOrder() {
    for domain in SemanticFieldDomain.allCases {
        let fields = SemanticDomainCatalog.fields(for: domain)
        #expect(!fields.isEmpty, "\(domain) 字段目录为空")
        #expect(!SemanticKeyDictionary.primaryKeys(for: domain).isEmpty, "\(domain) 缺少业务排序")
        let labels = fields.values.map(\.label)
        #expect(Set(labels).count == labels.count, "\(domain) 存在重复中文名称")
        for spec in fields.values {
            #expect(!spec.label.isEmpty)
            #expect(spec.label.range(of: #"[a-z]_[a-z]"#, options: .regularExpression) == nil, "\(domain) 字段 \(spec.key) 的名称不是中文目录：\(spec.label)")
        }
    }
}

@Test func sharedDictionaryKeysNeverLeakServerNames() {
    for (key, spec) in SemanticKeyDictionary.shared {
        #expect(spec.key == key)
        #expect(!spec.label.isEmpty)
    }
    // 同名同义字段跨域解析一致。
    let global = SemanticKeyDictionary.shared["created_at"]?.label
    let inPortfolio = SemanticKeyDictionary.resolve(key: "created_at", domain: .portfolio)?.label
    #expect(global == inPortfolio)
}

@Test func macroEvidenceUsesCatalogOrderAndProgressiveDisclosure() throws {
    let interpretation = try decode(
        #"""
        {"why_it_matters":"联邦基金利率直接影响估值贴现率。",
         "rising_interpretation":"利率上升通常压制成长股估值。",
         "falling_interpretation":"利率下降利好久期资产。",
         "bullish_scenarios":["通胀快速回落"],
         "bearish_scenarios":["通胀反复"],
         "context_notes":["公布为初值，可能修正"],
         "unknown_future_field":123}
        """#
    )
    let model = SemanticPresentationBuilder.evidence(interpretation, domain: .macro)
    #expect(model.primary.first?.label == "为何重要")
    #expect(model.primary.contains { $0.label == "上升解读" })
    #expect(model.unrecognizedKeys == ["unknown_future_field"])
    #expect(!model.primary.contains { $0.key == "unknown_future_field" })

    // 超过首层上限的已知字段进入次级层（页面上折叠为"更多字段"）。
    let manyFields = (0 ..< 14).reduce(into: [String: JSONValue]()) { dict, index in
        let keys = ["why_it_matters", "rising_interpretation", "falling_interpretation", "state", "label_zh",
                    "confidence", "status", "age_days", "latest", "previous", "observation_date", "value",
                    "unit", "frequency"]
        dict[keys[index]] = .number(Double(index))
    }
    let layered = SemanticPresentationBuilder.evidence(.object(manyFields), domain: .macro)
    #expect(layered.primary.count == SemanticPresentationBuilder.evidencePrimaryLimit)
    #expect(layered.secondary.count == 14 - SemanticPresentationBuilder.evidencePrimaryLimit)
}

@Test func missingDataKeepsDistinctSemantics() throws {
    let object = try decode(
        #"""
        {"margin_of_safety":null,"growth_rate":"not_applicable","eps_ttm":"provider_failed",
         "book_value_per_share":"insufficient","aaa_yield":"stale","status":"数据不足"}
        """#
    ).objectValue
    let domain = SemanticFieldDomain.valuation

    func qualifier(_ key: String) -> String? {
        let spec = SemanticKeyDictionary.resolve(key: key, domain: domain)
        let raw = object[key] ?? .null
        return SemanticFieldFormatter.display(
            .null, spec: .init(key, spec?.label ?? key, .decimal(precision: 2)), baseCurrency: nil
        ).qualifier
    }

    // 哨兵值映射为互不相同的缺失语义。
    #expect(SemanticMissingSemantics.state(fromString: "not_applicable") == .notApplicable)
    #expect(SemanticMissingSemantics.state(fromString: "provider_failed") == .providerFailed)
    #expect(SemanticMissingSemantics.state(fromString: "insufficient") == .missing)
    #expect(SemanticMissingSemantics.state(fromString: "stale") == .stale)
    #expect(FinancialValueFormatter.missing(.notApplicable).qualifier == "不适用")
    #expect(FinancialValueFormatter.missing(.notCollected).qualifier == "尚未采集")
    #expect(FinancialValueFormatter.missing(.providerFailed).qualifier == "数据源失败")
    #expect(FinancialValueFormatter.missing(.stale).qualifier == "旧数据")

    // 证据模型把 null 渲染为"数据不足"而不是整块消失。
    let evidence = SemanticPresentationBuilder.evidence(.object(object), domain: domain)
    let safety = evidence.primary.first { $0.key == "margin_of_safety" }
    #expect(safety?.display.text == "—")
    #expect(safety?.display.qualifier == "数据不足")

    // 同级 status=数据源失败 时，块内缺失值归因为数据源失败。
    let providerFailed = SemanticMissingSemantics.state(
        for: .null, in: ["status": .string("provider_failed")]
    )
    #expect(providerFailed == .providerFailed)
}

@Test func technicalEvidenceRendersCamelCaseCatalog() throws {
    let analysis = try decode(
        #"""
        {"generatedAt":"2026-09-08T01:20:00Z","dataThrough":"2026-09-05",
         "latestClose":234.12,"weeklyTrend":"bullish","rsi14":61.4,
         "nearestSupport":{"low":220.0,"high":224.0,"center":222.0,"type":"pivot"},
         "omittedReasons":["数据长度不足"],"source":"fmp","analysisVersion":"ta-v1"}
        """#
    )
    let model = SemanticPresentationBuilder.evidence(analysis, domain: .technical)
    let labels = model.primary.map(\.label)
    #expect(labels.contains("生成时间"))
    #expect(labels.contains("最新收盘"))
    #expect(labels.contains("周线趋势"))
    assertNoSnakeCase(labels + model.secondary.map(\.label), source: "technical evidence")
    let rsi = (model.primary + model.secondary).first { $0.key == "rsi14" }
    #expect(rsi?.display.text == "61.4")
}

// MARK: - R2.2 状态与反馈

@Test func jobPhasesMapServerStatusesConsistently() {
    #expect(WorkspaceJobPhase(serverStatus: "pending") == .queued)
    #expect(WorkspaceJobPhase(serverStatus: "QUEUED") == .queued)
    #expect(WorkspaceJobPhase(serverStatus: "running") == .running)
    #expect(WorkspaceJobPhase(serverStatus: "importing") == .running)
    #expect(WorkspaceJobPhase(serverStatus: "completed") == .completed)
    #expect(WorkspaceJobPhase(serverStatus: "success") == .completed)
    #expect(WorkspaceJobPhase(serverStatus: "partial_failed") == .completed)
    #expect(WorkspaceJobPhase(serverStatus: "failed") == .failed)
    #expect(WorkspaceJobPhase(serverStatus: "canceled") == .canceled)
    #expect(WorkspaceJobPhase(serverStatus: nil) == .unknown)
    #expect(WorkspaceJobPhase(serverStatus: "banana") == .unknown)
    for phase in WorkspaceJobPhase.allCases {
        #expect(!phase.title.isEmpty)
    }
    #expect(ResourcePresentationState.allCases.contains(.partial))
    #expect(ResourcePresentationState.partial.rawValue == "partial")
}

@Test func mutationFeedbackPhasesAreDeterministic() {
    let idle: MutationFeedbackPhase = .idle
    #expect(idle == .idle)
    #expect(MutationFeedbackPhase.pending(actionTitle: "重建持仓") != .idle)
    #expect(MutationFeedbackPhase.confirmed(actionTitle: "对账", message: "ok") == .confirmed(actionTitle: "对账", message: "ok"))
    #expect(MutationFeedbackPhase.failed(actionTitle: "对账", message: "bad") != .confirmed(actionTitle: "对账", message: "bad"))
}

@Test func onlyIrreversibleOrCostlyActionsRequireConfirmation() {
    let catalog = GoalM5Catalog()
    let allActions = [
        catalog.decisions, catalog.discovery, catalog.portfolio, catalog.journal,
        catalog.ibkr, catalog.ibkrAdmin, catalog.cryptoResearch, catalog.quant,
        catalog.paper, catalog.settings, catalog.administration,
    ].flatMap(\.actions)

    // 不可逆 / 产生外部费用的操作必须确认。
    for action in allActions where action.destructive {
        #expect(action.requiresConfirmation, "\(action.title) 是破坏性操作，必须确认")
    }
    let costly = allActions.filter { $0.path.contains("discovery/refresh") || $0.path.contains("signals/generate") }
    let allCostlyConfirm = costly.allSatisfy { action in action.requiresConfirmation }
    #expect(allCostlyConfirm)

    // 可逆的日常操作（暂停/恢复/对账/处理撮合/创建模拟账户/同步）不弹确认，直接执行并回读。
    let reversibleTitles = ["暂停", "恢复", "对账", "处理撮合", "创建模拟账户", "同步 Flex", "同步 Client Portal"]
    for action in allActions where reversibleTitles.contains(action.title) {
        #expect(!action.requiresConfirmation, "\(action.title) 可逆，不应强制确认")
    }
}
