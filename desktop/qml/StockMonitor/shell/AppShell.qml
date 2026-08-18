pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: shell
    required property var session
    required property var dashboard

    Rectangle {
        id: backdrop
        anchors.fill: parent
        color: Theme.canvas
        Rectangle {
            width: parent.width * 0.7
            height: parent.height * 0.55
            x: parent.width * 0.18
            y: -height * 0.45
            radius: width / 2
            color: Theme.ambientTint
        }
    }

    GlassSurface {
        id: sidebar
        x: Space.md
        y: Space.md
        width: Theme.compact ? 210 : 232
        height: parent.height - Space.xxl
        material: "regular"
        backdropSource: backdrop
        cornerRadius: Radius.panel
        padding: Space.lg

        ColumnLayout {
            anchors.fill: parent
            spacing: Space.sm
            Label {
                text: "Stock Monitor"
                color: Theme.textPrimary
                font.family: Type.family
                font.pixelSize: Type.headline
                font.weight: Font.DemiBold
            }
            Label {
                text: shell.session.username + " · " + shell.session.role
                color: Theme.textTertiary
                font.pixelSize: Type.micro
            }
            Item { Layout.preferredHeight: Space.md }
            Label {
                text: "WORKSPACE"
                color: Theme.textTertiary
                font.pixelSize: Type.micro
                font.weight: Font.DemiBold
                font.letterSpacing: 1.1
            }
            Item {
                id: navigation
                Layout.fillWidth: true
                Layout.preferredHeight: navColumn.implicitHeight

                Rectangle {
                    x: 0
                    y: pages.currentIndex * ((Theme.compact ? 34 : 40) + Space.xs)
                    width: navigation.width
                    height: Theme.compact ? 34 : 40
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
                        model: ["总览", "自选股", "研究"]
                        delegate: AppNavButton {
                            required property int index
                            required property string modelData
                            width: navColumn.width
                            text: modelData
                            checked: pages.currentIndex === index
                            focus: index === 0
                            Accessible.name: modelData
                            onClicked: pages.currentIndex = index
                        }
                    }
                }
            }
            Item { Layout.fillHeight: true }
            AppButton {
                text: "退出登录"
                glass: true
                Layout.fillWidth: true
                onClicked: shell.session.logout()
            }
        }
    }

    Item {
        id: contentArea
        anchors.left: sidebar.right
        anchors.leftMargin: Space.md
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom

        GlassSurface {
            id: toolbar
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Space.md
            height: Theme.compact ? 48 : 54
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
                    text: ["总览", "自选股", "研究"][pages.currentIndex]
                    color: Theme.textPrimary
                    font.pixelSize: Type.headline
                    font.weight: Font.DemiBold
                }
                AppSearchField {
                    placeholderText: "搜索股票、新闻与研究"
                    backdropSource: backdrop
                }
                AppButton {
                    text: "⋯"
                    glass: true
                    backdropSource: backdrop
                    leftPadding: Space.md
                    rightPadding: Space.md
                    Accessible.name: "更多"
                }
            }
        }

        StackLayout {
            id: pages
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: toolbar.bottom
            anchors.bottom: parent.bottom
            currentIndex: 0

            DashboardPage {
                dashboard: shell.dashboard
            }

            Repeater {
                model: [
                    { title: "自选股", note: "Phase 5 接入现有 watchlist API。" },
                    { title: "研究", note: "后续复用 research/v1 数据边界。" }
                ]
                delegate: Pane {
                    id: destination
                    required property var modelData
                    padding: Space.xxxl
                    background: Rectangle { color: "transparent" }
                    ColumnLayout {
                        spacing: Space.sm
                        Label {
                            text: destination.modelData.title
                            color: Theme.textPrimary
                            font.pixelSize: Type.largeTitle
                            font.weight: Font.DemiBold
                        }
                        Label {
                            text: destination.modelData.note
                            color: Theme.textSecondary
                            font.pixelSize: Type.body
                        }
                    }
                }
            }
        }
    }
}
