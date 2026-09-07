import SwiftUI

public enum ResourcePresentationState: String, CaseIterable, Sendable {
    case idle, loading, ready, refreshing, partial, stale, empty, error, permissionDenied, offline
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
            case .partial:
                SemanticStatusLabel("部分数据不可用，以下为可用内容", status: .warning)
                    .accessibilityIdentifier("state.partial")
                content
            case .stale:
                FreshnessBadge("显示上次有效数据", stale: true)
                content
            case .error:
                InlineError(message: "请检查网络后重试")
            case .empty:
                EmptyState("暂无数据", description: "当前范围没有可展示的记录。")
            case .permissionDenied:
                EmptyState("没有权限", systemImage: "lock", description: "权限由服务端账户角色决定。")
            case .offline:
                EmptyState("当前离线", systemImage: "wifi.slash", description: "连接恢复后会自动刷新。")
            }
        }
        .accessibilityElement(children: .contain)
    }
}
