pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1280
    height: 720
    minimumWidth: 1040
    minimumHeight: 640
    visible: true
    title: "Stock Monitor · Liquid Glass Showcase"
    color: Theme.canvas
    flags: customChrome ? Qt.Window | Qt.FramelessWindowHint : Qt.Window

    readonly property bool customChrome: Application.arguments.indexOf("--custom-chrome") >= 0
    property int selectedNav: 0
    property bool showPopover: true
    property bool inspectorOpen: true
    property var positions: [
        { symbol: "NVDA", name: "NVIDIA", price: "$182.36", change: "+2.14%", value: "$8,924", positive: true },
        { symbol: "MSFT", name: "Microsoft", price: "$506.91", change: "+0.82%", value: "$6,110", positive: true },
        { symbol: "AMZN", name: "Amazon", price: "$231.42", change: "−0.38%", value: "$4,288", positive: false },
        { symbol: "V", name: "Visa", price: "$351.08", change: "+0.44%", value: "$3,594", positive: true }
    ]

    Component.onCompleted: {
        const args = Application.arguments;
        const themeIndex = args.indexOf("--theme");
        const densityIndex = args.indexOf("--density");
        if (themeIndex >= 0 && themeIndex + 1 < args.length)
            Theme.previewMode = args[themeIndex + 1];
        if (densityIndex >= 0 && densityIndex + 1 < args.length)
            Theme.previewDensity = args[densityIndex + 1];
        Theme.previewContrast = args.indexOf("--high-contrast") >= 0 ? 1 : -1;
        Theme.previewReducedMotion = args.indexOf("--reduced-motion") >= 0 ? 1 : -1;
        Theme.previewReducedTransparency = args.indexOf("--reduced-transparency") >= 0 ? 1 : -1;
    }

    Shortcut {
        sequence: "Ctrl+K"
        onActivated: globalSearch.activate()
    }

    Rectangle {
        id: backdrop
        anchors.fill: parent
        color: Theme.canvas
        Rectangle {
            width: parent.width * 0.64
            height: parent.height * 0.8
            x: parent.width * 0.1
            y: -height * 0.54
            radius: width / 2
            color: Theme.ambientTint
        }
        Rectangle {
            width: 430
            height: 430
            x: parent.width - 260
            y: parent.height - 210
            radius: width / 2
            color: Theme.dark ? "transparent" : Qt.rgba(0.12, 0.52, 0.36, 0.06)
        }
    }

    WindowChrome {
        id: windowChrome
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        title: "Stock Monitor"
        backdropSource: backdrop
    }

    GlassSurface {
        id: sidebar
        x: Space.md
        y: windowChrome.height + Space.sm
        width: Theme.compact ? 200 : 220
        height: parent.height - y - Space.md
        material: "regular"
        backdropSource: backdrop
        cornerRadius: Radius.panel
        padding: Theme.compact ? Space.md : Space.lg

        ColumnLayout {
            anchors.fill: parent
            spacing: Theme.compact ? Space.xs : Space.sm
            Label {
                text: "Workspace"
                color: Theme.textPrimary
                font.pixelSize: Type.title
                font.weight: Font.DemiBold
            }
            Label {
                text: "Market open · 4h 12m"
                color: Theme.positive
                font.pixelSize: Type.caption
            }
            Item { Layout.preferredHeight: Space.md }
            Label {
                text: "OVERVIEW"
                color: Theme.textTertiary
                font.pixelSize: Type.micro
                font.weight: Font.DemiBold
                font.letterSpacing: 1.2
            }
            Item {
                id: navArea
                Layout.fillWidth: true
                Layout.preferredHeight: navColumn.implicitHeight
                readonly property int rowHeight: Theme.compact ? 34 : 38

                Rectangle {
                    y: window.selectedNav * (navArea.rowHeight + Space.xs)
                    width: navArea.width
                    height: navArea.rowHeight
                    radius: Radius.control
                    color: Theme.selected
                    Behavior on y {
                        enabled: !Theme.motionReduced
                        SpringAnimation { spring: Motion.springSnappy; damping: Motion.springSnappyDamping }
                    }
                }
                Column {
                    id: navColumn
                    width: parent.width
                    spacing: Space.xs
                    Repeater {
                        model: ["Portfolio", "Watchlist", "Market"]
                        delegate: AppNavButton {
                            required property int index
                            required property string modelData
                            width: navColumn.width
                            implicitHeight: navArea.rowHeight
                            text: modelData
                            checked: false
                            onClicked: window.selectedNav = index
                        }
                    }
                }
            }
            Item { Layout.preferredHeight: Space.sm }
            Label {
                text: "RESEARCH"
                color: Theme.textTertiary
                font.pixelSize: Type.micro
                font.weight: Font.DemiBold
                font.letterSpacing: 1.2
            }
            AppNavButton { Layout.fillWidth: true; text: "Industry Pulse" }
            AppNavButton { Layout.fillWidth: true; text: "Options" }
            AppNavButton { Layout.fillWidth: true; text: "AI Research" }
            Item { Layout.fillHeight: true }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: Theme.separator
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: Space.sm
                Rectangle { implicitWidth: 28; implicitHeight: 28; radius: 14; color: Theme.selected }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    Label { text: "Jiale"; color: Theme.textPrimary; font.pixelSize: Type.callout; font.weight: Font.DemiBold }
                    Label { text: Theme.compact ? "Compact" : "Comfortable"; color: Theme.textTertiary; font.pixelSize: Type.micro }
                }
                Label { text: "⌄"; color: Theme.textSecondary; font.pixelSize: Type.body }
            }
        }
    }

    Item {
        id: content
        anchors.left: sidebar.right
        anchors.leftMargin: Space.md
        anchors.right: parent.right
        anchors.rightMargin: Space.md
        anchors.top: windowChrome.bottom
        anchors.topMargin: Space.sm
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Space.md

        GlassSurface {
            id: toolbar
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: Theme.compact ? 46 : 52
            material: "regular"
            backdropSource: backdrop
            cornerRadius: Radius.panel

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Space.lg
                anchors.rightMargin: Space.sm
                spacing: Space.sm
                Label {
                    Layout.fillWidth: true
                    text: "Portfolio"
                    color: Theme.textPrimary
                    font.pixelSize: Type.headline
                    font.weight: Font.DemiBold
                }
                AppSearchField {
                    id: globalSearch
                    expanded: true
                    expandedWidth: Theme.compact ? 248 : 290
                    placeholderText: "Stocks, news, research…"
                    backdropSource: backdrop
                }
                AppButton {
                    id: moreButton
                    text: "⋯"
                    glass: true
                    backdropSource: backdrop
                    leftPadding: Space.md
                    rightPadding: Space.md
                    onClicked: window.showPopover = !window.showPopover
                }
                AppButton {
                    text: "Add position"
                    kind: "primary"
                }
            }
        }

        GlassSurface {
            id: popover
            visible: window.showPopover
            width: 180
            height: 128
            x: content.width - width - (Theme.compact ? 250 : 272) - Space.xxl
            anchors.top: toolbar.bottom
            anchors.topMargin: Space.sm
            material: "elevated"
            backdropSource: backdrop
            cornerRadius: Radius.panel
            raised: true
            z: 10
            opacity: visible ? 1 : 0
            scale: visible || Theme.motionReduced ? 1 : 0.94
            transformOrigin: Item.TopRight
            Behavior on opacity { NumberAnimation { duration: Motion.duration(Motion.normal) } }
            Behavior on scale { NumberAnimation { duration: Motion.duration(Motion.normal); easing.type: Motion.emphasized } }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Space.sm
                spacing: Space.xs
                AppMenuItem { Layout.fillWidth: true; text: "Refresh prices" }
                AppMenuItem { Layout.fillWidth: true; text: "Export snapshot" }
                AppMenuItem { Layout.fillWidth: true; text: "Open settings" }
            }
        }

        RowLayout {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: toolbar.bottom
            anchors.topMargin: Space.md
            anchors.bottom: parent.bottom
            spacing: Space.md

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: Space.md

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.compact ? 208 : 222

                    ColumnLayout {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        spacing: 0
                        Label {
                            text: "Total portfolio"
                            color: Theme.textSecondary
                            font.pixelSize: Type.callout
                        }
                        Label {
                            text: "$28,391.52"
                            color: Theme.textPrimary
                            font.family: Type.numericFamily
                            font.pixelSize: Type.numericDisplay
                            font.weight: Font.DemiBold
                            font.letterSpacing: -0.8
                        }
                        RowLayout {
                            spacing: Space.sm
                            Label { text: "+$510.42"; color: Theme.positive; font.family: Type.numericFamily; font.pixelSize: Type.numericBody; font.weight: Font.DemiBold }
                            Label { text: "+1.82% today"; color: Theme.textSecondary; font.pixelSize: Type.caption }
                        }
                    }

                    AppSegmentedControl {
                        id: rangeControl
                        anchors.right: parent.right
                        anchors.top: parent.top
                        width: 236
                        model: ["1D", "1W", "1M", "1Y"]
                        currentIndex: 2
                        backdropSource: backdrop
                    }

                    Canvas {
                        id: chart
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.topMargin: 96
                        anchors.bottom: parent.bottom
                        antialiasing: true
                        onPaint: {
                            const ctx = getContext("2d");
                            ctx.reset();
                            const points = [0.68, 0.63, 0.66, 0.55, 0.58, 0.43, 0.48, 0.35, 0.31, 0.38, 0.25, 0.21, 0.14];
                            ctx.lineWidth = 2;
                            ctx.strokeStyle = Theme.accent;
                            ctx.beginPath();
                            points.forEach((value, index) => {
                                const x = index * width / (points.length - 1);
                                const y = value * height;
                                if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                            });
                            ctx.stroke();
                        }
                        Connections {
                            target: Theme
                            function onDarkChanged() { chart.requestPaint(); }
                        }
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: Space.sm
                        RowLayout {
                            Layout.fillWidth: true
                            Label { Layout.fillWidth: true; text: "Positions"; color: Theme.textPrimary; font.pixelSize: Type.headline; font.weight: Font.DemiBold }
                            Label { text: "4 holdings"; color: Theme.textTertiary; font.pixelSize: Type.caption }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.leftMargin: Space.md
                            Layout.rightMargin: Space.md
                            Label { Layout.preferredWidth: 180; text: "SYMBOL"; color: Theme.textTertiary; font.pixelSize: Type.micro }
                            Label { Layout.fillWidth: true; text: "PRICE"; color: Theme.textTertiary; font.pixelSize: Type.micro; horizontalAlignment: Text.AlignRight }
                            Label { Layout.preferredWidth: 86; text: "TODAY"; color: Theme.textTertiary; font.pixelSize: Type.micro; horizontalAlignment: Text.AlignRight }
                            Label { Layout.preferredWidth: 100; text: "VALUE"; color: Theme.textTertiary; font.pixelSize: Type.micro; horizontalAlignment: Text.AlignRight }
                        }
                        Repeater {
                            model: window.positions
                            delegate: Rectangle {
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.preferredHeight: Theme.compact ? 38 : 44
                                radius: Radius.compactControl
                                color: rowHover.hovered ? Theme.hover : "transparent"
                                HoverHandler { id: rowHover }
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: Space.md
                                    anchors.rightMargin: Space.md
                                    Label { Layout.preferredWidth: 180; text: parent.parent.modelData.symbol + "  " + parent.parent.modelData.name; color: Theme.textPrimary; font.pixelSize: Type.callout; font.weight: Font.DemiBold }
                                    Label { Layout.fillWidth: true; text: parent.parent.modelData.price; color: Theme.textPrimary; font.family: Type.numericFamily; font.pixelSize: Type.data; horizontalAlignment: Text.AlignRight }
                                    Label { Layout.preferredWidth: 86; text: parent.parent.modelData.change; color: parent.parent.modelData.positive ? Theme.positive : Theme.negative; font.family: Type.numericFamily; font.pixelSize: Type.data; horizontalAlignment: Text.AlignRight }
                                    Label { Layout.preferredWidth: 100; text: parent.parent.modelData.value; color: Theme.textPrimary; font.family: Type.numericFamily; font.pixelSize: Type.data; horizontalAlignment: Text.AlignRight }
                                }
                            }
                        }
                    }
                }
            }

            GlassSurface {
                id: inspector
                Layout.preferredWidth: window.inspectorOpen ? (Theme.compact ? 250 : 272) : 0
                Layout.fillHeight: true
                material: "elevated"
                backdropSource: backdrop
                cornerRadius: Radius.panel
                raised: true
                opacity: window.inspectorOpen ? 1 : 0
                visible: opacity > 0
                Behavior on Layout.preferredWidth { NumberAnimation { duration: Motion.duration(Motion.continuity); easing.type: Motion.emphasized } }
                Behavior on opacity { NumberAnimation { duration: Motion.duration(Motion.normal) } }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.compact ? Space.md : Space.lg
                    spacing: Space.md
                    RowLayout {
                        Layout.fillWidth: true
                        Label { Layout.fillWidth: true; text: "Market inspector"; color: Theme.textPrimary; font.pixelSize: Type.headline; font.weight: Font.DemiBold }
                        Label { text: "×"; color: Theme.textSecondary; font.pixelSize: 18; TapHandler { onTapped: window.inspectorOpen = false } }
                    }
                    Label { text: "S&P 500"; color: Theme.textSecondary; font.pixelSize: Type.caption }
                    Label { text: "6,482.91"; color: Theme.textPrimary; font.family: Type.numericFamily; font.pixelSize: Type.title; font.weight: Font.DemiBold }
                    Label { text: "+0.74%"; color: Theme.positive; font.family: Type.numericFamily; font.pixelSize: Type.numericBody }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.separator }
                    Label { text: "Market breadth"; color: Theme.textSecondary; font.pixelSize: Type.caption }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { Layout.fillWidth: true; text: "Advancing"; color: Theme.textPrimary; font.pixelSize: Type.callout }
                        Label { text: "68%"; color: Theme.positive; font.family: Type.numericFamily; font.pixelSize: Type.data }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 6
                        radius: 3
                        color: Theme.hover
                        Rectangle { width: parent.width * 0.68; height: parent.height; radius: 3; color: Theme.positive }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.separator }
                    Label { text: "System states"; color: Theme.textSecondary; font.pixelSize: Type.caption }
                    RowLayout {
                        Layout.fillWidth: true
                        BusyIndicator { running: true; implicitWidth: 22; implicitHeight: 22 }
                        Label { Layout.fillWidth: true; text: "Syncing prices"; color: Theme.textPrimary; font.pixelSize: Type.callout }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 72
                        radius: Radius.control
                        color: Theme.hover
                        Column {
                            anchors.centerIn: parent
                            spacing: Space.xs
                            Label { anchors.horizontalCenter: parent.horizontalCenter; text: "No alerts"; color: Theme.textPrimary; font.pixelSize: Type.callout; font.weight: Font.DemiBold }
                            Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Thresholds are quiet"; color: Theme.textTertiary; font.pixelSize: Type.micro }
                        }
                    }
                    Item { Layout.fillHeight: true }
                    Label {
                        Layout.fillWidth: true
                        text: Theme.transparencyReduced ? "Opaque accessibility material" : "Regular transient material"
                        color: Theme.textTertiary
                        font.pixelSize: Type.micro
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }

    MouseArea {
        enabled: window.customChrome
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 6
        cursorShape: Qt.SizeHorCursor
        onPressed: window.startSystemResize(Qt.LeftEdge)
    }
    MouseArea {
        enabled: window.customChrome
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 6
        cursorShape: Qt.SizeHorCursor
        onPressed: window.startSystemResize(Qt.RightEdge)
    }
    MouseArea {
        enabled: window.customChrome
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 6
        cursorShape: Qt.SizeVerCursor
        onPressed: window.startSystemResize(Qt.TopEdge)
    }
    MouseArea {
        enabled: window.customChrome
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 6
        cursorShape: Qt.SizeVerCursor
        onPressed: window.startSystemResize(Qt.BottomEdge)
    }
    MouseArea {
        enabled: window.customChrome
        anchors.left: parent.left
        anchors.top: parent.top
        width: 10
        height: 10
        cursorShape: Qt.SizeFDiagCursor
        onPressed: window.startSystemResize(Qt.LeftEdge | Qt.TopEdge)
    }
    MouseArea {
        enabled: window.customChrome
        anchors.right: parent.right
        anchors.top: parent.top
        width: 10
        height: 10
        cursorShape: Qt.SizeBDiagCursor
        onPressed: window.startSystemResize(Qt.RightEdge | Qt.TopEdge)
    }
    MouseArea {
        enabled: window.customChrome
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        width: 10
        height: 10
        cursorShape: Qt.SizeBDiagCursor
        onPressed: window.startSystemResize(Qt.LeftEdge | Qt.BottomEdge)
    }
    MouseArea {
        enabled: window.customChrome
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: 10
        height: 10
        cursorShape: Qt.SizeFDiagCursor
        onPressed: window.startSystemResize(Qt.RightEdge | Qt.BottomEdge)
    }
}
