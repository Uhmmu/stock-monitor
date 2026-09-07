import SwiftUI

/// 服务端异步任务（同步、回测、发现、验证）统一的可呈现阶段。
/// 与 `ResourcePresentationState` 分层：这是单条任务记录的状态，不是页面资源状态。
public enum WorkspaceJobPhase: String, CaseIterable, Sendable {
    case queued, running, completed, failed, canceled, unknown

    public init(serverStatus: String?) {
        switch (serverStatus ?? "").lowercased() {
        case "queued", "pending", "scheduled", "planned":
            self = .queued
        case "running", "processing", "importing", "reconciling", "rebuilding", "in_progress", "active", "started":
            self = .running
        case "completed", "success", "succeeded", "ready", "done", "partial_failed", "repaired":
            self = .completed
        case "failed", "error", "cancelled_error", "rejected":
            self = .failed
        case "canceled", "cancelled", "stopped", "expired", "skipped":
            self = .canceled
        default:
            self = .unknown
        }
    }

    public var title: String {
        switch self {
        case .queued: "已排队"
        case .running: "运行中"
        case .completed: "已完成"
        case .failed: "失败"
        case .canceled: "已取消"
        case .unknown: "状态未知"
        }
    }

    public var status: SemanticStatusLabel.Status {
        switch self {
        case .queued: .info
        case .running: .info
        case .completed: .live
        case .failed: .danger
        case .canceled, .unknown: .neutral
        }
    }
}

public struct JobStateBadge: View {
    private let phase: WorkspaceJobPhase
    private let detail: String?

    public init(_ phase: WorkspaceJobPhase, detail: String? = nil) {
        self.phase = phase
        self.detail = detail
    }

    public var body: some View {
        Label {
            HStack(spacing: StockMonitorSpacing.xSmall) {
                if phase == .running {
                    ProgressView().controlSize(.mini)
                }
                Text(detail.map { "\(phase.title) · \($0)" } ?? phase.title)
            }
        } icon: {
            Image(systemName: icon)
        }
        .font(StockMonitorTypographyRole.metadata.font.weight(.medium))
        .foregroundStyle(tint)
        .accessibilityLabel(accessibilityText)
        .accessibilityIdentifier("badge.job-state")
    }

    private var icon: String {
        switch phase {
        case .queued: "clock.badge.circle"
        case .running: "gearshape.2"
        case .completed: "checkmark.circle.fill"
        case .failed: "xmark.octagon"
        case .canceled: "slash.circle"
        case .unknown: "questionmark.circle"
        }
    }

    private var tint: Color {
        switch phase {
        case .queued, .running: .blue
        case .completed: .green
        case .failed: .red
        case .canceled, .unknown: .secondary
        }
    }

    private var accessibilityText: String {
        detail.map { "\(phase.title)，\($0)" } ?? phase.title
    }
}

/// mutation 的统一反馈阶段：明确动词、范围与终态，服务端回读后进入 confirmed/failed。
public enum MutationFeedbackPhase: Equatable, Sendable {
    case idle
    case pending(actionTitle: String)
    case confirmed(actionTitle: String, message: String)
    case failed(actionTitle: String, message: String)
}

public struct MutationFeedbackView: View {
    private let phase: MutationFeedbackPhase

    public init(phase: MutationFeedbackPhase) {
        self.phase = phase
    }

    public var body: some View {
        switch phase {
        case .idle:
            EmptyView()
        case let .pending(title):
            HStack(spacing: StockMonitorSpacing.regular) {
                ProgressView().controlSize(.small)
                Text("正在执行“\(title)”…").stockMonitorTypography(.metadata)
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("mutation.pending")
        case let .confirmed(title, message):
            HStack(alignment: .top, spacing: StockMonitorSpacing.regular) {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                    Text("“\(title)”已完成").font(.headline)
                    Text(message).stockMonitorTypography(.metadata).textSelection(.enabled).lineLimit(4)
                }
            }
            .padding(StockMonitorSpacing.small)
            .frame(maxWidth: .infinity, alignment: .leading)
            .stockMonitorSurface(.grouped)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("mutation.confirmed")
        case let .failed(title, message):
            InlineError("“\(title)”未完成", message: message)
                .accessibilityIdentifier("mutation.failed")
        }
    }
}
