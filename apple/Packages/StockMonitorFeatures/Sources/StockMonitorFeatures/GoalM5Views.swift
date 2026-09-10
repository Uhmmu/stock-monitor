import StockMonitorCore
import StockMonitorDesign
import SwiftUI

public struct GoalM5RouteView: View {
    public let route: AppRoute
    public let navigation: AppNavigationModel
    public let service: GoalM5Service

    public init(route: AppRoute, navigation: AppNavigationModel, service: GoalM5Service) {
        self.route = route; self.navigation = navigation; self.service = service
    }

    public var body: some View {
        if route == .ai {
            AIChatWorkspaceView(service: service, activeSymbol: navigation.selectedSymbol, navigation: navigation)
        } else if route == .journal {
            JournalWorkspaceView(service: service, navigation: navigation)
        } else if let descriptor = GoalM5Catalog().descriptor(for: route, isAdministrator: navigation.isAdministrator) {
            if route == .settings {
                SettingsWorkspaceView(descriptor: descriptor, service: service, navigation: navigation)
            } else {
                ServerWorkspaceView(route: route, descriptor: descriptor, service: service, navigation: navigation)
            }
        } else {
            ContentUnavailableView("未找到工作台", systemImage: "exclamationmark.triangle")
        }
    }
}

private struct JournalWorkspaceView: View {
    let service: GoalM5Service
    let navigation: AppNavigationModel
    @State private var entries: [TradeLogDraft] = []
    @State private var selection: Int?
    @State private var draft: TradeLogDraft?
    @State private var loading = false
    @State private var error: String?
    @State private var mutation: MutationFeedbackPhase = .idle
    @State private var summaryConfirmation = false

    var body: some View {
        SecondaryNavigationSplit(
            minimumSidebarWidth: 190,
            idealSidebarWidth: 240,
            maximumSidebarWidth: 310
        ) {
            List(entries, selection: $selection) { entry in
                VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                    Text(entry.ticker.isEmpty ? "组合复盘" : entry.ticker).font(.headline)
                    Text("\(entry.tradeDate) · \(entry.direction.isEmpty ? "复盘" : entry.direction)")
                        .stockMonitorTypography(.metadata)
                }
                .tag(entry.id)
            }
            .overlay {
                if entries.isEmpty, !loading {
                    EmptyState("暂无交易日志", systemImage: "book.closed", description: "手动记录与 IBKR 对账草稿会显示在这里。")
                }
            }
            .accessibilityLabel("交易日志列表")
        } detail: {
            if let draft {
                journalEditor(draft)
            } else if loading {
                ProgressView("正在读取交易日志…")
            } else if let error {
                InlineError(message: error).padding(StockMonitorSpacing.large)
            } else {
                EmptyState("选择一条日志", systemImage: "book.pages", description: "交易事实与复盘正文会在右侧分层显示。")
            }
        }
        .task { await load() }
        .onChange(of: selection) { _, newValue in
            draft = entries.first { $0.id == newValue }
            mutation = .idle
            navigation.rememberSelection(newValue.map(String.init), for: .journal)
        }
        .confirmationDialog("生成 AI 总结", isPresented: $summaryConfirmation, titleVisibility: .visible) {
            Button("确认并生成") { Task { await summarize() } }
            Button("取消", role: .cancel) {}
        } message: {
            Text("只会把当前日志证据发送给服务端已配置模型；可能产生模型费用。")
        }
    }

    private func journalEditor(_ value: TradeLogDraft) -> some View {
        PageScaffold(width: StockMonitorContentWidth.readable) {
            PageHeader(value.ticker.isEmpty ? "组合复盘" : "\(value.ticker) 交易复盘", eyebrow: "交易日志", summary: value.tradeDate) {
                SemanticStatusLabel(value.status, status: value.status == "draft" ? .warning : .live)
            }
        } content: {
            JournalReadingGuide()
            if value.sourceType == "ibkr_sync" {
                Label("交易事实来自 IBKR 同步，只能编辑复盘正文和附件。", systemImage: "lock.shield")
                    .stockMonitorTypography(.metadata)
            }
            Form {
                Section("交易事实") {
                    TextField("日期", text: draftBinding(\.tradeDate)).disabled(value.sourceType == "ibkr_sync")
                    TextField("证券", text: draftBinding(\.ticker)).disabled(value.sourceType == "ibkr_sync")
                    TextField("方向", text: draftBinding(\.direction)).disabled(value.sourceType == "ibkr_sync")
                    TextField("数量", value: draftBinding(\.quantity), format: .number).disabled(value.sourceType == "ibkr_sync")
                    TextField("价格", value: draftBinding(\.price), format: .number).disabled(value.sourceType == "ibkr_sync")
                }
                Section("简要复盘") {
                    TextEditor(text: draftBinding(\.note)).frame(minHeight: 80)
                }
                Section("复盘正文") {
                    TextEditor(text: draftBinding(\.content)).frame(minHeight: 150)
                }
                if let summary = value.aiSummary, !summary.isEmpty {
                    Section("AI 总结 · 模型生成") { R5MarkdownContent(text: summary) }
                }
            }
            .formStyle(.grouped)
            if mutation != .idle {
                MutationFeedbackView(phase: mutation)
            }
            HStack {
                Button("生成 AI 总结", systemImage: "sparkles") { summaryConfirmation = true }
                Spacer()
                Button("保存复盘", systemImage: "checkmark") { Task { await save() } }
                    .buttonStyle(.borderedProminent)
            }
        }
        .navigationTitle(value.ticker.isEmpty ? "交易日志" : value.ticker)
    }

    private func draftBinding<Value>(_ keyPath: WritableKeyPath<TradeLogDraft, Value>) -> Binding<Value> {
        Binding(
            get: { draft![keyPath: keyPath] },
            set: { draft![keyPath: keyPath] = $0 }
        )
    }

    @MainActor private func load() async {
        loading = true
        error = nil
        do {
            let payload = try await service.tradeLogs()
            entries = (payload.objectValue["items"]?.arrayValue ?? payload.arrayValue).compactMap(TradeLogDraft.init)
            if selection == nil,
               let saved = navigation.state(for: .journal).selectedIdentifier.flatMap(Int.init),
               entries.contains(where: { $0.id == saved })
            {
                selection = saved
            }
            if selection == nil {
                selection = entries.first?.id
            }
            draft = entries.first { $0.id == selection }
        } catch {
            self.error = "日志加载失败：\(error.localizedDescription)"
        }
        loading = false
    }

    @MainActor private func save() async {
        guard let draft else { return }
        mutation = .pending(actionTitle: "保存复盘")
        do {
            let updated = try await service.updateTradeLog(draft)
            if let fresh = TradeLogDraft(payload: updated) {
                self.draft = fresh
                if let index = entries.firstIndex(where: { $0.id == fresh.id }) {
                    entries[index] = fresh
                }
            }
            mutation = .confirmed(actionTitle: "保存复盘", message: "服务端回读已确认。")
        } catch {
            mutation = .failed(actionTitle: "保存复盘", message: error.localizedDescription)
        }
    }

    @MainActor private func summarize() async {
        guard let draft else { return }
        mutation = .pending(actionTitle: "生成 AI 总结")
        do {
            let updated = try await service.summarizeTradeLog(id: draft.id)
            if let fresh = TradeLogDraft(payload: updated) {
                self.draft = fresh
            }
            mutation = .confirmed(actionTitle: "生成 AI 总结", message: "总结已由服务端生成并回读。")
        } catch {
            mutation = .failed(actionTitle: "生成 AI 总结", message: error.localizedDescription)
        }
    }
}

private struct SettingsWorkspaceView: View {
    let descriptor: WorkspaceDescriptor
    let service: GoalM5Service
    let navigation: AppNavigationModel
    @AppStorage("interface-density") private var density = InterfaceDensity.comfortable.rawValue
    @AppStorage("appearance") private var appearance = "system"

    var body: some View {
        VStack(spacing: 0) {
            WebInspiredHero("设置", eyebrow: "Preferences", summary: "外观和密度只影响此 Mac；服务端配置保存后会立即回读确认。") {
                SemanticStatusLabel("本机与服务端分层", status: .info)
            } actions: {
                EmptyView()
            }
            .padding(StockMonitorSpacing.medium)
            Form {
                Section("客户端外观") {
                    Picker("外观", selection: $appearance) {
                        Text("跟随系统").tag("system"); Text("浅色").tag("light"); Text("深色").tag("dark")
                    }
                    Picker("数据密度", selection: $density) {
                        ForEach(InterfaceDensity.allCases) { Text($0.title).tag($0.rawValue) }
                    }
                }
                Section {
                    Label("服务端密钥不会显示或缓存到此 Mac。", systemImage: "lock.shield")
                        .foregroundStyle(.secondary)
                }
            }
            .formStyle(.grouped)
            .frame(height: 190)
            .padding(.horizontal)
            Divider()
            ServerWorkspaceView(route: .settings, descriptor: descriptor, service: service, navigation: navigation)
        }.navigationTitle("设置")
    }
}

/// R2.0 后的 M5 工作台：payload 先经过 typed presentation model，再进入语义页面；
/// raw JSON 只存在于折叠的诊断区。状态与 mutation 反馈遵循 R2.2 统一规范。
private struct ServerWorkspaceView: View {
    let route: AppRoute
    let descriptor: WorkspaceDescriptor
    let service: GoalM5Service
    let navigation: AppNavigationModel
    @State private var selection: WorkspaceEndpoint.ID?
    @State private var payload: JSONValue?
    @State private var previousPayload: JSONValue?
    @State private var loading = false
    @State private var error: String?
    @State private var pendingAction: WorkspaceAction?
    @State private var mutation: MutationFeedbackPhase = .idle
    @State private var contextValues: [String: String] = [:]
    @State private var contextOptions: [String: [R5EntityOption]] = [:]
    @State private var contextLoading = false

    private var endpoint: WorkspaceEndpoint? {
        descriptor.endpoints.first { $0.id == selection }
            ?? descriptor.endpoints.first { $0.placeholders.isEmpty }
            ?? descriptor.endpoints.first
    }

    private var navigationSections: [R5NavigationSection] {
        R5WorkspaceBlueprint.visibleSections(for: descriptor, contextValues: contextValues)
    }

    private var contextFingerprint: String {
        contextValues.sorted { $0.key < $1.key }.map { "\($0.key)=\($0.value)" }.joined(separator: "&")
    }

    private var visiblePayload: JSONValue? {
        payload ?? previousPayload
    }

    var body: some View {
        SecondaryNavigationSplit(
            minimumSidebarWidth: 170,
            idealSidebarWidth: 220,
            maximumSidebarWidth: 270
        ) {
            List(selection: $selection) {
                ForEach(navigationSections) { section in
                    Section(section.title) {
                        ForEach(section.endpoints) { endpoint in
                            Label(endpoint.title, systemImage: R5WorkspaceBlueprint.icon(for: endpoint.semantic))
                                .tag(endpoint.id)
                        }
                    }
                }
            }
            .accessibilityLabel("工作区功能")
        } detail: {
            detailColumn
                .navigationTitle(descriptor.title)
        }
        .task(id: selection) { await reload() }
        .task {
            if let saved = navigation.state(for: route).selectedIdentifier,
               descriptor.endpoints.contains(where: { $0.id == saved })
            {
                selection = saved
            }
            await loadContextOptions()
        }
        .onChange(of: selection) { _, value in
            navigation.rememberSelection(value, for: route)
        }
        .task(id: contextFingerprint) {
            if endpoint?.placeholders.isEmpty == false {
                await reload()
            }
        }
        .confirmationDialog(
            pendingAction?.title ?? "确认操作", isPresented: Binding(
                get: { pendingAction != nil }, set: {
                    if !$0 {
                        pendingAction = nil
                    }
                }
            ), titleVisibility: .visible
        ) {
            if let action = pendingAction {
                Button(action.title, role: action.destructive ? .destructive : nil) { Task { await perform(action) } }
                Button("取消", role: .cancel) { pendingAction = nil }
            }
        } message: { Text(pendingAction?.confirmation ?? "") }
    }

    private var detailColumn: some View {
        VStack(alignment: .leading, spacing: 0) {
            workspaceChrome
            Divider()
            Group {
                if let visible = visiblePayload {
                    contentArea(visible)
                } else if loading {
                    ProgressView("正在读取服务端状态…")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if let error {
                    InlineError(message: error)
                        .padding(StockMonitorSpacing.large)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    EmptyState("暂无数据", systemImage: "tray", description: "服务端没有返回内容。")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
        }
        .accessibilityIdentifier("workspace.server")
    }

    private var workspaceChrome: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
            HStack {
                contextPickers
                Spacer(minLength: StockMonitorSpacing.medium)
                if loading, visiblePayload != nil {
                    ProgressView().controlSize(.small).help("正在刷新")
                }
                Button("刷新", systemImage: "arrow.clockwise") { Task { await reload() } }.disabled(loading)
                if !descriptor.actions.isEmpty {
                    Menu("操作", systemImage: "ellipsis.circle") {
                        Section("可用操作") {
                            ForEach(descriptor.actions.filter { !$0.destructive }) { action in
                                Button(action.title) {
                                    if action.requiresConfirmation {
                                        pendingAction = action
                                    } else {
                                        Task { await perform(action) }
                                    }
                                }
                            }
                        }
                        if descriptor.actions.contains(where: \.destructive) {
                            Section("危险操作") {
                                ForEach(descriptor.actions.filter(\.destructive)) { action in
                                    Button(action.title, role: .destructive) { pendingAction = action }
                                }
                            }
                        }
                    }
                }
            }
            if let notice = securityNoticeText {
                Label(notice, systemImage: "lock.shield")
                    .font(.callout).foregroundStyle(.secondary)
                    .accessibilityLabel("安全边界：\(notice)")
            }
            if mutation != .idle {
                MutationFeedbackView(phase: mutation)
            }
        }
        .padding(StockMonitorSpacing.medium)
        .background(.regularMaterial)
    }

    private var securityNoticeText: String? {
        if descriptor.title == "IBKR", endpoint?.semantic != "ibkr.status" {
            return "连接、凭据与代理由服务端安全管理。"
        }
        return descriptor.securityNotice
    }

    @ViewBuilder private var contextPickers: some View {
        let fields = R5WorkspaceBlueprint.contextualFields(for: descriptor)
        if contextLoading {
            ProgressView("读取可选对象…").controlSize(.small)
        } else {
            ForEach(fields, id: \.self) { field in
                if let options = contextOptions[field], !options.isEmpty {
                    Picker(R5WorkspaceBlueprint.fieldLabel(field), selection: Binding(
                        get: { contextValues[field, default: options[0].id] },
                        set: { contextValues[field] = $0 }
                    )) {
                        ForEach(options) { option in
                            Text(option.secondary.map { "\(option.label) · \($0)" } ?? option.label).tag(option.id)
                        }
                    }
                    .labelsHidden()
                    .frame(maxWidth: 250)
                    .accessibilityLabel(R5WorkspaceBlueprint.fieldLabel(field))
                }
            }
        }
    }

    private func contentArea(_ visible: JSONValue) -> some View {
        let spec = GoalM5PresentationCatalog.spec(semanticKey: endpoint?.semantic)
        let presentation = SemanticPresentationBuilder.presentation(
            title: endpoint?.title ?? descriptor.title, spec: spec, payload: visible
        )
        return ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                if error != nil {
                    InlineError("读取失败", message: "服务端请求未完成，以下仍显示上次有效数据。")
                        .padding(.bottom, StockMonitorSpacing.regular)
                }
                if let endpoint {
                    R5WorkspaceContentView(
                        descriptor: descriptor, endpoint: endpoint,
                        payload: visible, presentation: presentation
                    )
                }
            }
        }
        .accessibilityIdentifier("workspace.content")
    }

    @MainActor private func reload() async {
        guard let endpoint else { return }
        guard endpoint.placeholders.allSatisfy({ contextValues[$0]?.isEmpty == false }) else { return }
        loading = true; error = nil
        if let payload {
            previousPayload = payload
        }
        do { payload = try await service.load(endpoint.resolving(contextValues)) } catch {
            self.error = "读取失败：\(error.localizedDescription)"
        }
        loading = false
    }

    @MainActor private func loadContextOptions() async {
        let fields = R5WorkspaceBlueprint.contextualFields(for: descriptor)
        guard !fields.isEmpty else { return }
        contextLoading = true
        defer { contextLoading = false }
        var sourcePayloads: [WorkspaceEndpoint.ID: JSONValue] = [:]
        for field in fields {
            guard let source = R5WorkspaceBlueprint.contextSource(for: field, descriptor: descriptor) else { continue }
            do {
                let sourcePayload: JSONValue
                if let cached = sourcePayloads[source.id] {
                    sourcePayload = cached
                } else {
                    sourcePayload = try await service.load(source)
                    sourcePayloads[source.id] = sourcePayload
                }
                let options = R5EntityOptionExtractor.options(for: field, payload: sourcePayload)
                contextOptions[field] = options
                if contextValues[field] == nil {
                    contextValues[field] = options.first?.id
                }
            } catch {
                contextOptions[field] = []
            }
        }
    }

    @MainActor private func perform(_ action: WorkspaceAction) async {
        pendingAction = nil
        mutation = .pending(actionTitle: action.title)
        do {
            _ = try await service.perform(action)
            await reload()
            mutation = .confirmed(
                actionTitle: action.title,
                message: "服务端已接受请求；上方内容为回读后的最新状态。"
            )
        } catch {
            mutation = .failed(actionTitle: action.title, message: error.localizedDescription)
            loading = false
        }
    }
}

private struct ConversationRow: Identifiable {
    let id: Int
    let title: String
}

private struct AIChatWorkspaceView: View {
    let service: GoalM5Service
    let activeSymbol: String?
    let navigation: AppNavigationModel
    @State private var conversations: [ConversationRow] = []
    @State private var conversationID: Int?
    @State private var messages: JSONValue?
    @State private var prompt = ""
    @State private var model = ""
    @State private var webMode = "off"
    @State private var stream = AIStreamSnapshot()
    @State private var streamTask: Task<Void, Never>?
    @State private var error: String?
    @State private var citationsPresented = false
    @State private var deepConfirmationPrompt: String?
    @State private var advancedPresented = false

    var body: some View {
        SecondaryNavigationSplit(
            minimumSidebarWidth: 190,
            idealSidebarWidth: 240,
            maximumSidebarWidth: 310
        ) {
            List(conversations, selection: $conversationID) { row in
                Text(row.title).lineLimit(2).tag(row.id)
            }
            .toolbar { Button("新建", systemImage: "square.and.pencil") { Task { await createConversation() } } }
            .accessibilityLabel("会话列表")
        } detail: {
            VStack(spacing: 0) {
                chatToolbar
                Divider()
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: StockMonitorSpacing.medium) {
                        if let messages {
                            AIConversationMessagesView(messages: messages)
                        }
                        if !stream.answer.isEmpty {
                            AIStreamingResponseView(stream: stream)
                        }
                        if let error {
                            InlineError(message: error)
                        }
                    }
                    .frame(maxWidth: StockMonitorContentWidth.readable, alignment: .leading)
                    .padding(StockMonitorSpacing.large)
                    .frame(maxWidth: .infinity, alignment: .top)
                }
                Divider()
                composer
            }.navigationTitle("AI Chat")
        }
        .task { await loadConversations() }
        .task(id: conversationID) { await recoverConversation() }
        .onChange(of: conversationID) { _, value in
            navigation.rememberSelection(value.map(String.init), for: .ai)
        }
        .sheet(isPresented: $citationsPresented) {
            NavigationStack {
                List(stream.citations, id: \.self) { Text($0).textSelection(.enabled) }
                    .navigationTitle("引用")
                    .toolbar { Button("关闭") { citationsPresented = false } }
            }.frame(minWidth: 520, minHeight: 420)
        }
        .confirmationDialog(
            "确认 Deep Search 预算", isPresented: Binding(
                get: { deepConfirmationPrompt != nil },
                set: {
                    if !$0 {
                        deepConfirmationPrompt = nil
                    }
                }
            ), titleVisibility: .visible
        ) {
            Button("确认并开始") {
                if let pending = deepConfirmationPrompt {
                    deepConfirmationPrompt = nil; send(pending, confirmed: true)
                }
            }
            Button("取消", role: .cancel) { deepConfirmationPrompt = nil }
        } message: { Text("高强度 Deep Search 可能产生较高外部费用；实际预算、进度和终态由服务端控制并记录。") }
        .onDisappear { streamTask?.cancel() }
    }

    private var chatToolbar: some View {
        HStack {
            if let activeSymbol {
                Label(activeSymbol, systemImage: "building.2")
            }
            SemanticStatusLabel(webModeLabel, status: webMode == "off" ? .neutral : .info)
            Spacer()
            Button("对话设置", systemImage: "slider.horizontal.3") { advancedPresented.toggle() }
                .popover(isPresented: $advancedPresented, arrowEdge: .bottom) {
                    VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
                        Text("模型与搜索").font(.headline)
                        Picker("搜索模式", selection: $webMode) {
                            Text("关闭").tag("off"); Text("普通搜索").tag("search")
                            Text("深度·极简").tag("deep_minimal"); Text("深度·低").tag("deep_low")
                            Text("深度·中").tag("deep_medium"); Text("深度·高").tag("deep_high")
                            Text("深度·极高").tag("deep_xhigh")
                        }
                        TextField("模型（留空使用服务端默认）", text: $model)
                            .textFieldStyle(.roundedBorder)
                        Text("高强度 Deep Search 会在发送前单独确认预算。")
                            .stockMonitorTypography(.metadata)
                    }
                    .padding(StockMonitorSpacing.medium)
                    .frame(width: 320)
                }
            Button("引用", systemImage: "quote.bubble") { citationsPresented = true }.disabled(stream.citations.isEmpty)
            if isStreaming {
                Button("停止", systemImage: "stop.fill", role: .destructive) { Task { await stop() } }
            }
        }.padding(12).background(.regularMaterial)
    }

    private var webModeLabel: String {
        switch webMode {
        case "off": "不联网"
        case "search": "普通搜索"
        case "deep_minimal": "Deep Search · 极简"
        case "deep_low": "Deep Search · 低"
        case "deep_medium": "Deep Search · 中"
        case "deep_high": "Deep Search · 高"
        case "deep_xhigh": "Deep Search · 极高"
        default: webMode
        }
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: StockMonitorSpacing.small) {
            TextField("向服务端研究助手提问", text: $prompt, axis: .vertical).lineLimit(1 ... 6)
                .textFieldStyle(.roundedBorder).onSubmit { requestSend() }
            Button("发送", systemImage: "arrow.up.circle.fill") { requestSend() }.buttonStyle(.borderedProminent)
                .disabled(prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || conversationID == nil || isStreaming)
        }
        .frame(maxWidth: StockMonitorContentWidth.readable)
        .padding(StockMonitorSpacing.regular)
        .frame(maxWidth: .infinity)
    }

    private var isStreaming: Bool {
        if case .streaming = stream.phase {
            true
        } else {
            false
        }
    }

    @MainActor private func loadConversations() async {
        do {
            let value = try await service.conversations()
            let items = value.objectValue["items"]?.arrayValue ?? value.arrayValue
            conversations = items.compactMap { item in
                guard let id = item.objectValue["id"]?.intValue else { return nil }
                return ConversationRow(id: id, title: item.objectValue["title"]?.stringValue ?? "会话 #\(id)")
            }
            if conversationID == nil,
               let saved = navigation.state(for: .ai).selectedIdentifier.flatMap(Int.init),
               conversations.contains(where: { $0.id == saved })
            {
                conversationID = saved
            }
            if conversationID == nil {
                conversationID = conversations.first?.id
            }
        } catch { self.error = "会话加载失败：\(error.localizedDescription)" }
    }

    @MainActor private func createConversation() async {
        do {
            let value = try await service.createConversation()
            if let id = value.objectValue["id"]?.intValue {
                conversationID = id
            }
            await loadConversations()
        } catch { self.error = "创建失败：\(error.localizedDescription)" }
    }

    @MainActor private func recoverConversation() async {
        guard let conversationID else { return }
        error = nil
        do {
            async let loaded = service.messages(conversationID: conversationID)
            async let active = service.activeGeneration(conversationID: conversationID)
            messages = try await loaded
            let generation = try await active
            if generation.objectValue["active"]?.boolValue == true {
                stream.phase = .streaming
            }
        } catch { self.error = "恢复服务端状态失败：\(error.localizedDescription)" }
    }

    private func requestSend() {
        let value = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return }
        if webMode == "deep_high" || webMode == "deep_xhigh" {
            deepConfirmationPrompt = value
        } else {
            send(value, confirmed: false)
        }
    }

    private func send(_ value: String, confirmed: Bool) {
        guard let conversationID else { return }
        prompt = ""; stream = AIStreamSnapshot(); error = nil
        streamTask?.cancel()
        streamTask = Task {
            do {
                let events = try await service.streamMessage(
                    conversationID: conversationID, message: value,
                    model: model.isEmpty ? nil : model, webAccessMode: webMode,
                    activeSymbol: activeSymbol, deepSearchConfirmed: confirmed
                )
                var machine = AIStreamStateMachine()
                for try await event in events {
                    guard !Task.isCancelled else { return }
                    let next = machine.consume(event)
                    await MainActor.run { stream = next }
                }
                machine.finishTransport()
                await MainActor.run { stream = machine.snapshot }
                await recoverConversation()
            } catch is CancellationError {
                return
            } catch {
                await MainActor.run { self.error = "流连接中断，正在回读服务端状态。" }
                await recoverConversation()
            }
        }
    }

    @MainActor private func stop() async {
        guard let conversationID else { return }
        streamTask?.cancel()
        do { _ = try await service.stop(conversationID: conversationID) } catch {
            self.error = "停止请求失败：\(error.localizedDescription)"
        }
        await recoverConversation()
    }
}
