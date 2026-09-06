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

private struct ServerWorkspaceView: View {
    let descriptor: WorkspaceDescriptor
    let service: GoalM5Service
    @State private var selection: WorkspaceEndpoint.ID?
    @State private var payload: JSONValue?
    @State private var previousPayload: JSONValue?
    @State private var loading = false
    @State private var error: String?
    @State private var pendingAction: WorkspaceAction?
    @State private var actionResult: String?
    @State private var contextValues: [String: String] = [
        "instrument_id": "1", "asset_id": "1", "job_id": "1", "run_id": "1",
        "candidate_id": "1", "history_id": "1",
    ]

    private var endpoint: WorkspaceEndpoint? {
        descriptor.endpoints.first { $0.id == selection } ?? descriptor.endpoints.first
    }

    var body: some View {
        NavigationSplitView {
            List(descriptor.endpoints, selection: $selection) { endpoint in
                Label(endpoint.title, systemImage: "rectangle.stack").tag(endpoint.id)
            }
            .navigationSplitViewColumnWidth(min: 170, ideal: 220, max: 270)
        } detail: {
            VStack(alignment: .leading, spacing: 0) {
                workspaceHeader
                Divider()
                Group {
                    if loading, payload == nil, previousPayload == nil {
                        ProgressView("正在读取服务端状态…").frame(maxWidth: .infinity, maxHeight: .infinity)
                    } else if let visible = payload ?? previousPayload {
                        ScrollView { JSONDocumentView(value: visible).padding(22).frame(maxWidth: .infinity, alignment: .leading) }
                            .overlay(alignment: .topTrailing) {
                                if loading {
                                    ProgressView().controlSize(.small).padding()
                                }
                            }
                    } else {
                        ContentUnavailableView("暂无数据", systemImage: "tray", description: Text(error ?? "服务端没有返回内容"))
                    }
                }
            }
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

    private var workspaceHeader: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(endpoint?.title ?? descriptor.title).font(.title2.bold())
                    Text("Phase \(descriptor.phase.rawValue) · \(descriptor.summary)").foregroundStyle(.secondary)
                }
                Spacer()
                Button("刷新", systemImage: "arrow.clockwise") { Task { await reload() } }.disabled(loading)
                if !descriptor.actions.isEmpty {
                    Menu("操作", systemImage: "ellipsis.circle") {
                        ForEach(descriptor.actions) { action in
                            Button(action.title, role: action.destructive ? .destructive : nil) { pendingAction = action }
                        }
                    }
                }
            }
            if let notice = descriptor.securityNotice {
                Label(notice, systemImage: "lock.shield").font(.callout).foregroundStyle(.secondary)
                    .accessibilityLabel("安全边界：\(notice)")
            }
            if let endpoint, !endpoint.placeholders.isEmpty {
                HStack {
                    ForEach(endpoint.placeholders, id: \.self) { field in
                        TextField(field.replacingOccurrences(of: "_", with: " ").capitalized, text: Binding(
                            get: { contextValues[field, default: "1"] },
                            set: { contextValues[field] = $0 }
                        )).textFieldStyle(.roundedBorder).frame(maxWidth: 150)
                    }
                    Button("应用") { Task { await reload() } }
                }
            }
            if let error {
                Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
            }
            if let actionResult {
                Text(actionResult).font(.caption).foregroundStyle(.secondary)
            }
        }.padding(20).background(.regularMaterial)
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
        pendingAction = nil; loading = true; error = nil
        do {
            let result = try await service.perform(action)
            actionResult = "“\(action.title)”已由服务端接受：\(result.displayText.prefix(160))"
            await reload()
        } catch { self.error = "操作失败：\(error.localizedDescription)"; loading = false }
    }
}

private struct JSONDocumentView: View {
    let value: JSONValue
    var key: String?

    var body: some View {
        switch value {
        case let .object(object):
            VStack(alignment: .leading, spacing: 10) {
                if let key {
                    Text(label(key)).font(.headline)
                }
                ForEach(object.keys.sorted(), id: \.self) { itemKey in
                    if let item = object[itemKey] {
                        JSONDocumentView(value: item, key: itemKey)
                    }
                }
            }
        case let .array(array):
            VStack(alignment: .leading, spacing: 8) {
                if let key {
                    Text("\(label(key)) · \(array.count)").font(.headline)
                }
                if array.isEmpty {
                    Text("数据不足").foregroundStyle(.secondary)
                }
                LazyVStack(alignment: .leading, spacing: 8) { ForEach(Array(array.enumerated()), id: \.offset) { index, item in
                    GroupBox("#\(index + 1)") { JSONDocumentView(value: item).frame(maxWidth: .infinity, alignment: .leading) }
                } }
            }
        default:
            LabeledContent(key.map(label) ?? "值") {
                Text(value.displayText).textSelection(.enabled).multilineTextAlignment(.trailing)
            }.accessibilityElement(children: .combine)
        }
    }

    private func label(_ value: String) -> String {
        value.replacingOccurrences(of: "_", with: " ").capitalized
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
                            JSONDocumentView(value: messages)
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
                            Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
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
                Text("关闭").tag("off"); Text("普通搜索").tag("search"); Text("Deep Minimal").tag("deep_minimal")
                Text("Deep Low").tag("deep_low"); Text("Deep Medium").tag("deep_medium")
                Text("Deep High").tag("deep_high"); Text("Deep X-High").tag("deep_xhigh")
            }.frame(width: 190)
            TextField("服务端默认模型", text: $model).frame(width: 210)
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
