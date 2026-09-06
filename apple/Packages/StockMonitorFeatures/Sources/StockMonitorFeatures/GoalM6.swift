import Foundation
import Observation
import StockMonitorCore
import SwiftUI
import UniformTypeIdentifiers

public struct ParityEntry: Equatable, Sendable {
    public let macRoute: AppRoute
    public let webSurface: String
    public let administratorOnly: Bool

    public init(_ macRoute: AppRoute, webSurface: String, administratorOnly: Bool = false) {
        self.macRoute = macRoute
        self.webSurface = webSurface
        self.administratorOnly = administratorOnly
    }
}

public enum GoalM6ParityCatalog {
    /// Every native route is tied to its authoritative Web surface. Some Web
    /// surfaces are nested tabs; the Mac promotes them to first-class routes.
    public static let entries: [ParityEntry] = [
        .init(.overview, webSurface: "?tab=overview"),
        .init(.watchlist, webSurface: "?tab=watchlist"),
        .init(.holdings, webSurface: "?tab=holdings"),
        .init(.ai, webSurface: "/ai/new"),
        .init(.decisions, webSurface: "/investment-decisions"),
        .init(.calendar, webSurface: "?tab=calendar"),
        .init(.discovery, webSurface: "?tab=discovery"),
        .init(.options, webSurface: "?tab=options"),
        .init(.mood, webSurface: "?tab=mood"),
        .init(.moodLab, webSurface: "?tab=mood-lab", administratorOnly: true),
        .init(.alerts, webSurface: "?tab=alerts"),
        .init(.news, webSurface: "?tab=news"),
        .init(.macro, webSurface: "?tab=macro"),
        .init(.industry, webSurface: "?tab=industry"),
        .init(.fundamentals, webSurface: "?tab=fundamentals"),
        .init(.financials, webSurface: "?tab=financials"),
        .init(.valuation, webSurface: "?tab=crossmodel"),
        .init(.compare, webSurface: "?tab=compare"),
        .init(.technical, webSurface: "?tab=technical"),
        .init(.sec, webSurface: "?tab=sec"),
        .init(.ownership, webSurface: "SEC > 13F ownership"),
        .init(.congress, webSurface: "Settings > public figures"),
        .init(.reports, webSurface: "?tab=reports"),
        .init(.journal, webSurface: "?tab=journal"),
        .init(.settings, webSurface: "?tab=settings"),
        .init(.administration, webSurface: "Settings > admin operations", administratorOnly: true),
        .init(.ibkr, webSurface: "/ibkr"),
        .init(.ibkrAdmin, webSurface: "/admin/integrations/ibkr", administratorOnly: true),
        .init(.cryptoResearch, webSurface: "/crypto > research"),
        .init(.quantBacktests, webSurface: "/crypto > quant"),
        .init(.paper, webSurface: "/crypto > internal PAPER"),
    ]
}

@MainActor
@Observable
public final class ClientCompatibilityModel {
    public private(set) var decision: ClientCompatibilityDecision?
    public private(set) var checking = false
    private let service: ClientCompatibilityService
    private let currentVersion: String

    public init(client: APIClient, currentVersion: String) {
        service = ClientCompatibilityService(client: client)
        self.currentVersion = currentVersion
    }

    public func check() async {
        guard !checking else { return }
        checking = true
        decision = await service.check(currentVersion: currentVersion)
        checking = false
    }
}

public struct ClientCompatibilityGateView<Content: View>: View {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast
    @State private var model: ClientCompatibilityModel
    private let content: Content

    public init(
        client: APIClient, currentVersion: String,
        @ViewBuilder content: () -> Content
    ) {
        _model = State(initialValue: ClientCompatibilityModel(client: client, currentVersion: currentVersion))
        self.content = content()
    }

    public var body: some View {
        Group {
            switch model.decision {
            case let .updateRequired(minimum, recommended):
                ContentUnavailableView {
                    Label("需要更新 Stock Monitor", systemImage: "arrow.down.app")
                } description: {
                    Text("服务端要求至少使用 \(minimum)；建议版本为 \(recommended)。当前版本不会继续读取私有数据。")
                }
                .accessibilityIdentifier("compatibility.update-required")
            case let .serverIncompatible(missing):
                ContentUnavailableView {
                    Label("服务端尚不兼容", systemImage: "server.rack")
                } description: {
                    Text("缺少 \(missing.count) 项客户端能力。请先更新服务端，再重新连接。")
                } actions: {
                    Button("重新检查") { Task { await model.check() } }
                }
                .accessibilityIdentifier("compatibility.server-incompatible")
            default:
                content
                    .safeAreaInset(edge: .top, spacing: 0) {
                        compatibilityNotice
                    }
            }
        }
        .task { await model.check() }
    }

    @ViewBuilder private var compatibilityNotice: some View {
        switch model.decision {
        case .legacyServer:
            notice("服务端尚未提供版本握手；当前按兼容模式运行。", systemImage: "clock.arrow.circlepath")
        case .unavailable:
            notice("暂时无法检查服务端版本；数据请求仍按各自安全策略处理。", systemImage: "wifi.exclamationmark")
        default:
            EmptyView()
        }
    }

    private func notice(_ message: String, systemImage: String) -> some View {
        HStack(spacing: 10) {
            Label(message, systemImage: systemImage)
            Spacer()
            Button("重试") { Task { await model.check() } }
        }
        .font(.callout)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background {
            if reduceTransparency {
                Rectangle().fill(.background)
            } else {
                Rectangle().fill(.regularMaterial)
            }
        }
        .overlay(alignment: .bottom) {
            if contrast == .increased {
                Divider().background(.primary)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("compatibility.notice")
    }
}

public struct SupportDiagnosticsDocument: FileDocument {
    public static var readableContentTypes: [UTType] {
        [.plainText]
    }

    public var text: String

    public init(text: String) {
        self.text = text
    }

    public init(configuration: ReadConfiguration) throws {
        text = String(data: configuration.file.regularFileContents ?? Data(), encoding: .utf8) ?? ""
    }

    public func fileWrapper(configuration _: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: Data(text.utf8))
    }
}

public struct SupportDiagnosticsSection: View {
    private let metrics: NetworkMetrics
    @State private var document = SupportDiagnosticsDocument(text: "")
    @State private var exporting = false
    @State private var exportError: String?

    public init(metrics: NetworkMetrics) {
        self.metrics = metrics
    }

    public var body: some View {
        Section("支持与诊断") {
            LabeledContent("隐私范围", value: "仅版本、系统与匿名运行计数")
            Button("导出支持诊断…", systemImage: "square.and.arrow.up") {
                Task { await prepareExport() }
            }
            .accessibilityHint("导出不包含令牌、用户名、持仓、对话、IBKR 标识或请求内容")
            if let exportError {
                Label(exportError, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.orange)
            }
        }
        .fileExporter(
            isPresented: $exporting,
            document: document,
            contentType: .plainText,
            defaultFilename: "stock-monitor-diagnostics"
        ) { result in
            if case let .failure(error) = result {
                exportError = "导出失败：\(error.localizedDescription)"
            }
        }
    }

    @MainActor private func prepareExport() async {
        let snapshot = await metrics.snapshot()
        let bundle = Bundle.main
        #if arch(arm64)
            let architecture = "arm64"
        #else
            let architecture = "unsupported"
        #endif
        let diagnostics = SupportDiagnostics(
            appVersion: bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "unknown",
            buildNumber: bundle.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "unknown",
            operatingSystem: ProcessInfo.processInfo.operatingSystemVersionString,
            architecture: architecture,
            compatibilityState: "handshake-enabled",
            metrics: snapshot
        )
        document = SupportDiagnosticsDocument(text: diagnostics.text)
        exportError = nil
        exporting = true
    }
}
