import SwiftUI

/// Keeps feature-level navigation from becoming a nested `NavigationSplitView` on macOS.
/// Nested navigation splits compete for the window sidebar command and can replace the app sidebar
/// when a workspace route is selected. `HSplitView` preserves a native, resizable secondary pane
/// while leaving the app shell as the sole owner of window navigation.
struct SecondaryNavigationSplit<Sidebar: View, Detail: View>: View {
    private let minimumSidebarWidth: CGFloat
    private let idealSidebarWidth: CGFloat
    private let maximumSidebarWidth: CGFloat
    private let sidebar: Sidebar
    private let detail: Detail

    init(
        minimumSidebarWidth: CGFloat,
        idealSidebarWidth: CGFloat,
        maximumSidebarWidth: CGFloat,
        @ViewBuilder sidebar: () -> Sidebar,
        @ViewBuilder detail: () -> Detail
    ) {
        self.minimumSidebarWidth = minimumSidebarWidth
        self.idealSidebarWidth = idealSidebarWidth
        self.maximumSidebarWidth = maximumSidebarWidth
        self.sidebar = sidebar()
        self.detail = detail()
    }

    var body: some View {
        #if os(macOS)
            HSplitView {
                sidebar
                    .frame(
                        minWidth: minimumSidebarWidth,
                        idealWidth: idealSidebarWidth,
                        maxWidth: maximumSidebarWidth,
                        maxHeight: .infinity
                    )
                detail
                    .frame(minWidth: 420, maxWidth: .infinity, maxHeight: .infinity)
            }
        #else
            NavigationSplitView {
                sidebar
                    .navigationSplitViewColumnWidth(
                        min: minimumSidebarWidth,
                        ideal: idealSidebarWidth,
                        max: maximumSidebarWidth
                    )
            } detail: {
                detail
            }
        #endif
    }
}
