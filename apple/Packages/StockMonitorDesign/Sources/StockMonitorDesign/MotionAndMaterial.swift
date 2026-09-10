import SwiftUI

// MARK: - R6.1 材质分层与微交互策略

/// 材质只允许出现在 chrome/transient 层；正文、图表和数据表留在 content layer。
public enum MaterialPolicyLayer: String, CaseIterable, Sendable {
    case content, chrome, transient

    public var title: String {
        switch self {
        case .content: "内容层（禁止材质）"
        case .chrome: "chrome 层（sidebar/toolbar，系统材质）"
        case .transient: "transient 层（popover/tooltip，系统材质）"
        }
    }
}

/// 材质使用审计目录：每个使用材质的表面必须登记，且不允许出现在内容层。
public struct MaterialPolicyEntry: Identifiable, Equatable, Sendable {
    public let surface: String
    public let layer: MaterialPolicyLayer
    public let usesSystemMaterial: Bool
    public let note: String

    public var id: String {
        surface
    }

    public init(surface: String, layer: MaterialPolicyLayer, usesSystemMaterial: Bool, note: String) {
        self.surface = surface; self.layer = layer; self.usesSystemMaterial = usesSystemMaterial; self.note = note
    }
}

public enum MaterialPolicyCatalog {
    /// 全 App 的材质表面清单；内容层为空是硬约束。
    public static let entries: [MaterialPolicyEntry] = [
        .init(surface: "sidebar（NavigationSplitView 系统侧栏）", layer: .chrome, usesSystemMaterial: true, note: "系统控件自带材质，不叠加自定义玻璃。"),
        .init(surface: "toolbar（系统工具栏）", layer: .chrome, usesSystemMaterial: true, note: "系统控件自带材质。"),
        .init(surface: "K 线十字光标 tooltip（CandleTooltip）", layer: .transient, usesSystemMaterial: true, note: "regularMaterial；transient 层唯一材质使用点。"),
        .init(surface: "系统菜单/popover/确认弹窗", layer: .transient, usesSystemMaterial: true, note: "全部由系统控件提供，无自定义玻璃。"),
        .init(surface: "正文卡片（stockMonitorSurface）", layer: .content, usesSystemMaterial: false, note: "不透明或低透明 surface + 分隔线，Reduce Transparency 下完全不透明。"),
        .init(surface: "图表与数据表", layer: .content, usesSystemMaterial: false, note: "普通 surface，不用材质做层级。"),
    ]

    /// 硬门禁：任何自定义材质表面都不得登记为内容层。
    public static var contentLayerUsesSystemMaterial: [MaterialPolicyEntry] {
        entries.filter { $0.layer == .content && $0.usesSystemMaterial }
    }
}

public extension StockMonitorMotion {
    /// Reduce Motion 下的状态切换：短 cross-fade，不做空间位移。
    static let stateChange = Animation.easeInOut(duration: 0.12)

    /// hover 高亮亮度（状态反馈，非位移动画，Reduce Motion 下保留）。
    static let hoverHighlightOpacity: Double = 0.05
}

/// 轻微 hover 高亮：只提升亮度，不位移、不缩放；应用于自定义可点击卡片/行。
public struct SubtleHoverHighlight: ViewModifier {
    @State private var hovering = false

    public func body(content: Content) -> some View {
        content
            .background(
                hovering ? Color.primary.opacity(StockMonitorMotion.hoverHighlightOpacity) : Color.clear,
                in: RoundedRectangle(cornerRadius: StockMonitorCornerRadius.control)
            )
            .onHover { hovering = $0 }
    }
}

public extension View {
    func subtleHoverHighlight() -> some View {
        modifier(SubtleHoverHighlight())
    }
}

/// 立即按压反馈：按下瞬间轻微下沉，无弹簧延迟；高频操作不做慢动画。
public struct ImmediatePressButtonStyle: ButtonStyle {
    public init() {}

    public func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(configuration.isPressed ? 0.72 : 1)
            .brightness(configuration.isPressed ? -0.04 : 0)
    }
}

/// R6.1 动效审计：高频路径零装饰动画，转场可中断。
public enum StockMonitorMotionAudit: Equatable, Sendable {
    public struct Surface: Equatable, Sendable {
        public let name: String
        public let animated: Bool
        public let interruptible: Bool
        public let reduceMotionFallback: String

        public init(name: String, animated: Bool, interruptible: Bool, reduceMotionFallback: String) {
            self.name = name; self.animated = animated; self.interruptible = interruptible
            self.reduceMotionFallback = reduceMotionFallback
        }
    }

    /// 高频路径（表格排序、快捷键导航、路由切换、列宽拖动）必须零动画。
    public static let highFrequencySurfaces: [Surface] = [
        .init(name: "表格列排序", animated: false, interruptible: true, reduceMotionFallback: "无动画，本就直接切换"),
        .init(name: "路由/导航切换", animated: false, interruptible: true, reduceMotionFallback: "系统 NavigationSplitView 行为"),
        .init(name: "Command-K 搜索与键盘导航", animated: false, interruptible: true, reduceMotionFallback: "无动画"),
        .init(name: "表格列宽拖动", animated: false, interruptible: true, reduceMotionFallback: "实时跟随，无弹簧"),
        .init(name: "watchlist 选中与刷新", animated: false, interruptible: true, reduceMotionFallback: "即时状态切换"),
    ]

    /// 有动画的表面必须使用共享 spring token（可中断）并声明 Reduce Motion 降级。
    public static let animatedSurfaces: [Surface] = [
        .init(name: "密度切换（compact/comfortable）", animated: true, interruptible: true, reduceMotionFallback: "StockMonitorMotion.stateChange cross-fade"),
        .init(name: "阅读进度展开/收起（DisclosureGroup）", animated: true, interruptible: true, reduceMotionFallback: "系统 DisclosureGroup Reduce Motion 行为"),
        .init(name: "Design Lab 拖拽演示", animated: true, interruptible: true, reduceMotionFallback: "reduceMotion 时 nil 动画，直接跟手"),
    ]

    public static var animatedSurfacesMissingFallback: [Surface] {
        animatedSurfaces.filter(\.reduceMotionFallback.isEmpty)
    }

    public static var highFrequencySurfacesWithAnimation: [Surface] {
        highFrequencySurfaces.filter(\.animated)
    }
}
