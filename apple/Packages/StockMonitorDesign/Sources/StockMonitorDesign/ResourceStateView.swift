import SwiftUI

public enum ResourcePresentationState: String, CaseIterable, Sendable {
    case idle, loading, ready, refreshing, stale, empty, error, permissionDenied, offline
}

public struct ResourceStateView<Content: View>: View {
    private let state: ResourcePresentationState
    private let content: Content

    public init(state: ResourcePresentationState, @ViewBuilder content: () -> Content) {
        self.state = state
        self.content = content()
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
            switch state {
            case .idle, .loading:
                ProgressView("正在加载")
            case .ready:
                content
            case .refreshing:
                content.overlay(alignment: .topTrailing) { ProgressView().controlSize(.small) }
            case .stale:
                Label("显示上次有效数据", systemImage: "clock.badge.exclamationmark")
                    .foregroundStyle(.secondary)
                content
            case .error:
                ContentUnavailableView("暂时无法加载", systemImage: "exclamationmark.triangle", description: Text("请检查网络后重试"))
            case .empty:
                ContentUnavailableView("暂无数据", systemImage: "tray")
            case .permissionDenied:
                ContentUnavailableView("没有权限", systemImage: "lock", description: Text("权限由服务端账户角色决定"))
            case .offline:
                ContentUnavailableView("当前离线", systemImage: "wifi.slash", description: Text("连接恢复后会自动刷新"))
            }
        }
        .accessibilityElement(children: .contain)
    }
}
