pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1280
    height: 900
    minimumWidth: 900
    minimumHeight: 640
    visible: true
    title: "Stock Monitor · Design System Playground"
    color: Theme.canvas

    Component.onCompleted: {
        const args = Application.arguments;
        const themeIndex = args.indexOf("--theme");
        if (themeIndex >= 0 && themeIndex + 1 < args.length)
            Theme.previewMode = args[themeIndex + 1];
        Theme.previewContrast = args.indexOf("--high-contrast") >= 0 ? 1 : -1;
        Theme.previewReducedMotion = args.indexOf("--reduced-motion") >= 0 ? 1 : -1;
        Theme.previewReducedTransparency = args.indexOf("--reduced-transparency") >= 0 ? 1 : -1;
    }

    AppMenu {
        id: sampleMenu
        AppMenuItem {
            text: "刷新"
        }
        AppMenuItem {
            text: "导出"
        }
        AppMenuItem {
            text: "不可用"
            enabled: false
        }
    }

    AppSheet {
        id: sampleSheet
        ColumnLayout {
            width: parent.width
            spacing: Space.md
            Label {
                text: "原生 Sheet"
                color: Theme.textPrimary
                font.pixelSize: Type.title
                font.weight: Font.DemiBold
            }
            Label {
                Layout.fillWidth: true
                text: "保持焦点、Escape 关闭，并在减少动态时退化为即时状态变化。"
                color: Theme.textSecondary
                wrapMode: Text.Wrap
            }
            AppButton {
                text: "完成"
                kind: "primary"
                Layout.alignment: Qt.AlignRight
                onClicked: sampleSheet.close()
            }
        }
    }

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth

        ColumnLayout {
            width: Math.min(1120, window.width - Space.xxxl * 2)
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: Space.xl

            Item {
                Layout.preferredHeight: Space.lg
            }
            RowLayout {
                Layout.fillWidth: true
                Label {
                    Layout.fillWidth: true
                    text: "Design System Playground"
                    color: Theme.textPrimary
                    font.pixelSize: Type.display
                    font.weight: Font.DemiBold
                }
                AppButton {
                    text: "浅色"
                    checked: Theme.mode === "light"
                    checkable: true
                    onClicked: Theme.mode = "light"
                }
                AppButton {
                    text: "深色"
                    checked: Theme.mode === "dark"
                    checkable: true
                    onClicked: Theme.mode = "dark"
                }
                AppButton {
                    text: "跟随系统"
                    checked: Theme.mode === "system"
                    checkable: true
                    onClicked: Theme.mode = "system"
                }
            }

            AppCard {
                Layout.fillWidth: true
                RowLayout {
                    anchors.fill: parent
                    spacing: Space.xl
                    AppSwitch {
                        text: "高对比度"
                        checked: Theme.highContrast
                        onToggled: Theme.highContrast = checked
                    }
                    AppSwitch {
                        text: "减少动态"
                        checked: Theme.reducedMotion
                        onToggled: Theme.reducedMotion = checked
                    }
                    AppSwitch {
                        text: "减少透明度"
                        checked: Theme.reducedTransparency
                        onToggled: Theme.reducedTransparency = checked
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    Label {
                        text: Theme.dark ? "Dark" : "Light"
                        color: Theme.textSecondary
                        font.pixelSize: Type.caption
                    }
                }
            }

            Label {
                text: "Typography"
                color: Theme.textPrimary
                font.pixelSize: Type.title
                font.weight: Font.DemiBold
            }
            AppCard {
                Layout.fillWidth: true
                RowLayout {
                    anchors.fill: parent
                    spacing: Space.xxl
                    Label {
                        text: "Display 30"
                        color: Theme.textPrimary
                        font.pixelSize: Type.display
                        font.weight: Font.DemiBold
                    }
                    Label {
                        text: "Title 20"
                        color: Theme.textPrimary
                        font.pixelSize: Type.title
                    }
                    Label {
                        text: "Body 14"
                        color: Theme.textPrimary
                        font.pixelSize: Type.body
                    }
                    Label {
                        text: "Caption 12"
                        color: Theme.textSecondary
                        font.pixelSize: Type.caption
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    Label {
                        text: "$12,345.67"
                        color: Theme.positive
                        font.pixelSize: Type.numeric
                        font.family: "monospace"
                    }
                }
            }

            Label {
                text: "Buttons & Inputs"
                color: Theme.textPrimary
                font.pixelSize: Type.title
                font.weight: Font.DemiBold
            }
            AppCard {
                Layout.fillWidth: true
                RowLayout {
                    anchors.fill: parent
                    spacing: Space.md
                    AppButton {
                        text: "Primary"
                        kind: "primary"
                    }
                    AppButton {
                        text: "Secondary"
                    }
                    AppButton {
                        text: "Danger"
                        kind: "danger"
                    }
                    AppButton {
                        text: "Loading"
                        loading: true
                    }
                    AppButton {
                        text: "Disabled"
                        enabled: false
                    }
                    AppTextField {
                        Layout.fillWidth: true
                        placeholderText: "搜索证券"
                    }
                    AppTextField {
                        Layout.fillWidth: true
                        text: "INVALID"
                        invalid: true
                        errorText: "无法识别证券"
                    }
                }
            }

            Label {
                text: "Navigation, Menu & Table"
                color: Theme.textPrimary
                font.pixelSize: Type.title
                font.weight: Font.DemiBold
            }
            AppCard {
                Layout.fillWidth: true
                RowLayout {
                    anchors.fill: parent
                    spacing: Space.xl
                    ColumnLayout {
                        Layout.preferredWidth: 180
                        AppNavButton {
                            Layout.fillWidth: true
                            text: "总览"
                            checked: true
                        }
                        AppNavButton {
                            Layout.fillWidth: true
                            text: "自选股"
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        AppTableRow {
                            Layout.fillWidth: true
                            text: "NVDA   $182.36   +1.42%"
                            highlighted: true
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: Theme.borderWidth
                            color: Theme.separator
                        }
                        AppTableRow {
                            Layout.fillWidth: true
                            text: "MSFT   $506.91   −0.18%"
                        }
                    }
                    AppButton {
                        id: menuButton
                        text: "打开菜单"
                        onClicked: sampleMenu.popup(menuButton, 0, menuButton.height + Space.xs)
                        AppToolTip {
                            visible: menuButton.hovered
                            text: "菜单从触发器位置出现"
                        }
                    }
                    AppButton {
                        text: "打开 Sheet"
                        onClicked: sampleSheet.open()
                    }
                }
            }

            Label {
                text: "Loading, Empty & Error"
                color: Theme.textPrimary
                font.pixelSize: Type.title
                font.weight: Font.DemiBold
            }
            AppCard {
                Layout.fillWidth: true
                RowLayout {
                    anchors.fill: parent
                    AppStateView {
                        Layout.fillWidth: true
                        kind: "loading"
                        message: "读取缓存与远端状态"
                    }
                    AppStateView {
                        Layout.fillWidth: true
                        kind: "empty"
                        message: "筛选条件下没有结果"
                    }
                    AppStateView {
                        Layout.fillWidth: true
                        kind: "error"
                        message: "连接失败，可安全重试"
                    }
                }
            }
            Item {
                Layout.preferredHeight: Space.xxxl
            }
        }
    }
}
