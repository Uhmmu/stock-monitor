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
            AIChatWorkspaceView(service: service, activeSymbol: navigation.selectedSymbol)
        } else if let descriptor = GoalM5Catalog().descriptor(for: route, isAdministrator: navigation.isAdministrator) {
            if route == .settings {
                SettingsWorkspaceView(descriptor: descriptor, service: service)
            } else {
                ServerWorkspaceView(descriptor: descriptor, service: service)
            }
        } else {
            ContentUnavailableView("未找到工作台", systemImage: "exclamationmark.triangle")
        }
    }
}

private struct SettingsWorkspaceView: View {
    let descriptor: WorkspaceDescriptor
    let service: GoalM5Service
    @AppStorage("interface-density") private var density = InterfaceDensity.comfortable.rawValue
    @AppStorage("appearance") private var appearance = "system"

    var body: some View {
        VStack(spacing: 0) {
            Form {
                Picker("外观", selection: $appearance) {
                    Text("跟随系统").tag("system"); Text("浅色").tag("light"); Text("深色").tag("dark")
                }
                Picker("数据密度", selection: $density) {
                    ForEach(InterfaceDensity.allCases) { Text($0.title).tag($0.rawValue) }
                }
            }.formStyle(.grouped).frame(height: 150).padding(.horizontal)
            Divider()
            ServerWorkspaceView(descriptor: descriptor, service: service)
        }.navigationTitle("设置")
    }
}

/// R2.0 后的 M5 工作台：payload 先经过 typed presentation model，再进入语义页面；
/// raw JSON 只存在于折叠的诊断区。状态与 mutation 反馈遵循 R2.2 统一规范。
private struct ServerWorkspaceView: View {
    let descriptor: WorkspaceDescriptor
    let service: GoalM5Service
    @State private var selection: WorkspaceEndpoint.ID?
    @State private var payload: JSONValue?
    @State private var previousPayload: JSONValue?
    @State private var loading = false
    @State private var error: String?
    @State private var pendingAction: WorkspaceAction?
    @State private var mutation: MutationFeedbackPhase = .idle
    @State private var parametersExpanded = false
    @State private var contextValues: [String: String] = [
        "instrument_id": "1", "asset_id": "1", "job_id": "1", "run_id": "1",
        "candidate_id": "1", "history_id": "1",
    ]

    /// 查询参数的中文标签；输入仍以服务端 ID 为准，但不再向用户展示 snake_case。
    static let parameterLabels: [String: String] = [
        "instrument_id": "标的 ID", "asset_id": "资产 ID", "job_id": "任务 ID",
        "run_id": "运行 ID", "candidate_id": "候选 ID", "history_id": "历史批次 ID",
    ]

    private var endpoint: WorkspaceEndpoint? {
        descriptor.endpoints.first { $0.id == selection } ?? descriptor.endpoints.first
    }

    private var visiblePayload: JSONValue? {
        payload ?? previousPayload
    }

    var body: some View {
        NavigationSplitView {
            List(descriptor.endpoints, selection: $selection) { endpoint in
                Label(endpoint.title, systemImage: "rectangle.stack").tag(endpoint.id)
            }
            .navigationSplitViewColumnWidth(min: 170, ideal: 220, max: 270)
        } detail: {
            detailColumn
                .navigationTitle(descriptor.title)
        }
        .task(id: selection) { await reload() }
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
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(endpoint?.title ?? descriptor.title).font(.title2.bold())
                    Text(descriptor.summary).foregroundStyle(.secondary).font(.callout)
                }
                Spacer()
                if loading, visiblePayload != nil {
                    ProgressView().controlSize(.small).help("正在刷新")
                }
                Button("刷新", systemImage: "arrow.clockwise") { Task { await reload() } }.disabled(loading)
                if !descriptor.actions.isEmpty {
                    Menu("操作", systemImage: "ellipsis.circle") {
                        ForEach(descriptor.actions) { action in
                            Button(action.title, role: action.destructive ? .destructive : nil) {
                                if action.requiresConfirmation {
                                    pendingAction = action
                                } else {
                                    Task { await perform(action) }
                                }
                            }
                        }
                    }
                }
            }
            if let notice = descriptor.securityNotice {
                Label(notice, systemImage: "lock.shield")
                    .font(.callout).foregroundStyle(.secondary)
                    .accessibilityLabel("安全边界：\(notice)")
            }
            if let endpoint, !endpoint.placeholders.isEmpty {
                parameterBar(endpoint)
            }
            if mutation != .idle {
                MutationFeedbackView(phase: mutation)
            }
        }
        .padding(StockMonitorSpacing.medium)
        .background(.regularMaterial)
    }

    /// 查询参数默认折叠：普通用户页面不常驻展示内部 ID 输入。
    private func parameterBar(_ endpoint: WorkspaceEndpoint) -> some View {
        DisclosureGroup(isExpanded: $parametersExpanded) {
            HStack(spacing: StockMonitorSpacing.small) {
                ForEach(endpoint.placeholders, id: \.self) { field in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(Self.parameterLabels[field] ?? field)
                            .stockMonitorTypography(.microAnnotation)
                        TextField("", text: Binding(
                            get: { contextValues[field, default: "1"] },
                            set: { contextValues[field] = $0 }
                        ))
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 120)
                    }
                }
                Button("应用") { Task { await reload() } }
            }
            .padding(.top, StockMonitorSpacing.small)
        } label: {
            Text("查询参数（\(endpoint.placeholders.count) 项）")
                .font(.callout)
                .foregroundStyle(.secondary)
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
                SemanticWorkspaceContentView(
                    title: endpoint?.title ?? descriptor.title,
                    summary: nil,
                    presentation: presentation
                )
            }
        }
        .accessibilityIdentifier("workspace.content")
    }

    @MainActor private func reload() async {
        guard let endpoint else { return }
        loading = true; error = nil
        if let payload {
            previousPayload = payload
        }
        do { payload = try await service.load(endpoint.resolving(contextValues)) }
        catch { self.error = "读取失败：\(error.localizedDescription)" }
        loading = false
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

    var body: some View {
        NavigationSplitView {
            List(conversations, selection: $conversationID) { row in
                Text(row.title).lineLimit(2).tag(row.id)
            }
            .navigationTitle("会话")
            .toolbar { Button("新建", systemImage: "square.and.pencil") { Task { await createConversation() } } }
            .navigationSplitViewColumnWidth(min: 190, ideal: 240, max: 310)
        } detail: {
            VStack(spacing: 0) {
                chatToolbar
                Divider()
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        if let messages {
                            AIConversationMessagesView(messages: messages)
                        }
                        if !stream.answer.isEmpty {
                            GroupBox("正在生成") { Text(stream.answer).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                        }
                        if let progress = stream.progressMessage {
                            Label(progress, systemImage: "magnifyingglass")
                        }
                        if !stream.activeTools.isEmpty {
                            Label("工具活动 \(stream.activeTools.count)", systemImage: "hammer")
                        }
                        if let error {
                            InlineError(message: error)
                        }
                    }.padding(22).frame(maxWidth: .infinity, alignment: .leading)
                }
                Divider()
                composer
            }.navigationTitle("AI Chat")
        }
        .task { await loadConversations() }
        .task(id: conversationID) { await recoverConversation() }
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
            Picker("搜索", selection: $webMode) {
                Text("关闭").tag("off"); Text("普通搜索").tag("search")
                Text("深度·极简").tag("deep_minimal")
                Text("深度·低").tag("deep_low")
                Text("深度·中").tag("deep_medium")
                Text("深度·高").tag("deep_high")
                Text("深度·极高").tag("deep_xhigh")
            }.frame(width: 190)
            TextField("模型（留空用服务端默认）", text: $model).frame(width: 210)
            if let activeSymbol {
                Label(activeSymbol, systemImage: "building.2")
            }
            Spacer()
            Button("引用", systemImage: "quote.bubble") { citationsPresented = true }.disabled(stream.citations.isEmpty)
            if isStreaming {
                Button("停止", systemImage: "stop.fill", role: .destructive) { Task { await stop() } }
            }
        }.padding(12).background(.regularMaterial)
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("向服务端研究助手提问", text: $prompt, axis: .vertical).lineLimit(1 ... 6)
                .textFieldStyle(.roundedBorder).onSubmit { requestSend() }
            Button("发送", systemImage: "arrow.up.circle.fill") { requestSend() }.buttonStyle(.borderedProminent)
                .disabled(prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || conversationID == nil || isStreaming)
        }.padding(14)
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
            } catch is CancellationError {}
            catch {
                await MainActor.run { self.error = "流连接中断，正在回读服务端状态。" }
                await recoverConversation()
            }
        }
    }

    @MainActor private func stop() async {
        guard let conversationID else { return }
        streamTask?.cancel()
        do { _ = try await service.stop(conversationID: conversationID) }
        catch { self.error = "停止请求失败：\(error.localizedDescription)" }
        await recoverConversation()
    }
}
