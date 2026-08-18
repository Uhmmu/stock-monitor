pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import StockMonitor

Item {
    id: page
    required property var dashboard

    function number(value, digits) {
        return typeof value === "number" && isFinite(value)
                ? value.toLocaleString(Qt.locale("en_US"), "f", digits) : "数据不足"
    }
    function time(value) {
        if (typeof value === "number" && value <= 0)
            return "等待首次采集"
        const date = new Date(value)
        return isNaN(date.getTime()) ? "等待首次采集" : date.toLocaleString(Qt.locale())
    }
    function freshness() {
        if (!page.dashboard.hasData)
            return "尚无缓存"
        const age = page.dashboard.freshnessAgeSeconds
        if (age < 0)
            return "时间未知"
        if (age < 60)
            return "刚刚读取"
        if (age < 3600)
            return Math.floor(age / 60) + " 分钟前读取"
        return Math.floor(age / 3600) + " 小时前读取"
    }

    Component.onCompleted: dashboard.setActive(true)
    Component.onDestruction: dashboard.setActive(false)

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Space.xl
        spacing: Space.md

        AppCard {
            Layout.fillWidth: true
            padding: Space.lg

            RowLayout {
                width: parent.width
                spacing: Space.md
                Rectangle {
                    implicitWidth: 10
                    implicitHeight: 10
                    radius: 5
                    color: !page.dashboard.loaded ? Theme.textTertiary
                          : page.dashboard.marketOpen ? Theme.positive : Theme.textTertiary
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Space.xxs
                    Label {
                        text: !page.dashboard.loaded ? "正在读取市场状态"
                              : page.dashboard.marketOpen ? "美国市场开放" : "美国市场休市"
                        color: Theme.textPrimary
                        font.pixelSize: Type.headline
                        font.weight: Font.DemiBold
                    }
                    Label {
                        text: "市场状态检查于 " + page.time(page.dashboard.marketCheckedAt)
                        color: Theme.textSecondary
                        font.pixelSize: Type.caption
                    }
                }
                Label {
                    text: page.dashboard.streamStatus === "connected"
                          ? (quoteList.count > 50 ? "实时流已连接（前 50 只）" : "实时流已连接")
                          : "持久化快照"
                    color: page.dashboard.streamStatus === "connected" ? Theme.positive : Theme.textSecondary
                    font.pixelSize: Type.caption
                }
                AppButton {
                    text: "刷新"
                    kind: "secondary"
                    loading: page.dashboard.busy
                    Accessible.description: "重新读取 Dashboard 持久化快照"
                    onClicked: page.dashboard.refresh()
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: warningText.implicitHeight + Space.md * 2
            visible: page.dashboard.stale || page.dashboard.error.length > 0
            radius: Radius.control
            color: Theme.selected
            border.width: Theme.borderWidth
            border.color: page.dashboard.error.length > 0 ? Theme.negative : Theme.warning
            Label {
                id: warningText
                anchors.fill: parent
                anchors.margins: Space.md
                text: page.dashboard.error.length > 0
                      ? page.dashboard.error + (page.dashboard.hasData ? "；继续显示上次成功读取的数据。" : "")
                      : "当前显示上次成功读取的数据，可能已经过期。"
                color: Theme.textPrimary
                font.pixelSize: Type.caption
                wrapMode: Text.Wrap
            }
        }

        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: page.width >= 780 ? 2 : 1
            columnSpacing: Space.md
            rowSpacing: Space.md

            AppCard {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 260
                Layout.preferredWidth: 680
                padding: 0

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: Space.lg
                        Label {
                            Layout.fillWidth: true
                            text: "自选股行情"
                            color: Theme.textPrimary
                            font.pixelSize: Type.title
                            font.weight: Font.DemiBold
                        }
                        Label {
                            text: page.freshness() + " · GET " + page.dashboard.requestCount
                            color: Theme.textTertiary
                            font.pixelSize: Type.micro
                        }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.separator }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: Space.lg
                        Layout.rightMargin: Space.lg
                        Layout.preferredHeight: 30
                        visible: page.width >= 760
                        Label { Layout.fillWidth: true; text: "证券"; color: Theme.textTertiary; font.pixelSize: Type.micro }
                        Label { Layout.preferredWidth: 110; text: "现价"; color: Theme.textTertiary; font.pixelSize: Type.micro; horizontalAlignment: Text.AlignRight }
                        Label { Layout.preferredWidth: 90; text: "今日"; color: Theme.textTertiary; font.pixelSize: Type.micro; horizontalAlignment: Text.AlignRight }
                        Label { Layout.preferredWidth: 150; text: "来源 / 时间"; color: Theme.textTertiary; font.pixelSize: Type.micro; horizontalAlignment: Text.AlignRight }
                    }
                    ListView {
                        id: quoteList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: page.dashboard.hasData
                        clip: true
                        activeFocusOnTab: true
                        keyNavigationEnabled: true
                        boundsBehavior: Flickable.StopAtBounds
                        model: page.dashboard.quotes
                        Accessible.name: "自选股实时行情"

                        delegate: ItemDelegate {
                            id: quoteRow
                            required property int index
                            required property string ticker
                            required property string company
                            required property var price
                            required property var changePercent
                            required property string volumeLabel
                            required property string source
                            required property var updatedAtMs
                            required property bool hasLive
                            required property bool hasData
                            width: quoteList.width
                            height: page.width >= 760 ? (Theme.compact ? 44 : 52) : (Theme.compact ? 66 : 76)
                            highlighted: ListView.isCurrentItem
                            Accessible.name: ticker + "，" + (hasData ? page.number(price, 2) : "数据不足")
                            Accessible.description: hasLive ? "实时行情" : "持久化行情快照"
                            onClicked: quoteList.currentIndex = index

                            background: Rectangle {
                                color: quoteRow.down ? Theme.pressed : quoteRow.highlighted ? Theme.selected
                                       : quoteRow.hovered ? Theme.hover : "transparent"
                                border.width: quoteRow.visualFocus ? 2 : 0
                                border.color: Theme.focus
                            }
                            contentItem: RowLayout {
                                spacing: Space.md
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: Space.xxs
                                    Label { text: quoteRow.ticker; color: Theme.textPrimary; font.pixelSize: Type.numericBody; font.weight: Font.DemiBold }
                                    Label { text: quoteRow.company || "名称数据不足"; color: Theme.textSecondary; font.pixelSize: Type.caption; elide: Text.ElideRight; Layout.fillWidth: true }
                                }
                                ColumnLayout {
                                    Layout.preferredWidth: 110
                                    spacing: Space.xxs
                                    Label { Layout.fillWidth: true; text: page.number(quoteRow.price, 2); color: Theme.textPrimary; font.family: Type.numericFamily; font.pixelSize: Type.numericBody; horizontalAlignment: Text.AlignRight }
                                    Label { Layout.fillWidth: true; visible: page.width < 760; text: quoteRow.source || "来源未知"; color: Theme.textTertiary; font.pixelSize: Type.micro; horizontalAlignment: Text.AlignRight; elide: Text.ElideLeft }
                                }
                                Label {
                                    Layout.preferredWidth: 90
                                    text: typeof quoteRow.changePercent === "number" && isFinite(quoteRow.changePercent)
                                          ? (quoteRow.changePercent >= 0 ? "+" : "") + page.number(quoteRow.changePercent, 2) + "%" : "—"
                                    color: typeof quoteRow.changePercent !== "number" || !isFinite(quoteRow.changePercent)
                                           ? Theme.textTertiary : quoteRow.changePercent >= 0 ? Theme.positive : Theme.negative
                                    font.family: Type.numericFamily
                                    font.pixelSize: Type.numericBody
                                    horizontalAlignment: Text.AlignRight
                                }
                                Item {
                                    Layout.preferredWidth: 52
                                    Layout.preferredHeight: 16
                                    visible: page.width >= 760
                                    Rectangle {
                                        anchors.centerIn: parent
                                        width: parent.width
                                        height: 2
                                        color: Theme.separator
                                    }
                                    Rectangle {
                                        readonly property real magnitude: typeof quoteRow.changePercent === "number" && isFinite(quoteRow.changePercent)
                                                                          ? Math.min(parent.width / 2, Math.abs(quoteRow.changePercent) * 6) : 0
                                        x: quoteRow.changePercent >= 0 ? parent.width / 2 : parent.width / 2 - magnitude
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: magnitude
                                        height: 4
                                        radius: 2
                                        color: quoteRow.changePercent >= 0 ? Theme.positive : Theme.negative
                                    }
                                }
                                ColumnLayout {
                                    visible: page.width >= 760
                                    Layout.preferredWidth: 150
                                    spacing: Space.xxs
                                    Label { Layout.fillWidth: true; text: quoteRow.source || "来源未知"; color: Theme.textSecondary; font.pixelSize: Type.caption; horizontalAlignment: Text.AlignRight; elide: Text.ElideLeft }
                                    Label { Layout.fillWidth: true; text: page.time(quoteRow.updatedAtMs); color: Theme.textTertiary; font.pixelSize: Type.micro; horizontalAlignment: Text.AlignRight }
                                }
                            }
                        }
                    }
                    AppStateView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: !page.dashboard.hasData
                        kind: page.dashboard.busy ? "loading" : page.dashboard.error.length > 0 ? "error" : "empty"
                        title: page.dashboard.busy ? "正在加载" : page.dashboard.error.length > 0 ? "加载失败" : "自选股为空"
                        message: kind === "empty" ? "添加第一只股票后，这里会显示持久化行情与实时更新。" : page.dashboard.error
                        onRetryRequested: page.dashboard.refresh()
                    }
                }
            }

            AppCard {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 220
                Layout.preferredWidth: 290
                padding: Space.lg

                ColumnLayout {
                    anchors.fill: parent
                    spacing: Space.sm
                    Label {
                        text: "实时事件"
                        color: Theme.textPrimary
                        font.pixelSize: Type.title
                        font.weight: Font.DemiBold
                    }
                    Label {
                        text: "仅显示本次连接收到的服务端市场事件，不补造历史告警。"
                        color: Theme.textSecondary
                        font.pixelSize: Type.caption
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    ListView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: page.dashboard.recentEvents
                        delegate: AppTableRow {
                            required property var modelData
                            width: ListView.view.width
                            text: (modelData.symbol || "市场") + " · " + (modelData.eventType || "事件")
                            Accessible.description: modelData.severity || ""
                        }
                    }
                    Label {
                        visible: page.dashboard.recentEvents.length === 0
                        text: page.dashboard.streamStatus === "connected" ? "当前连接尚无新事件。" : "连接实时流后显示新事件。"
                        color: Theme.textTertiary
                        font.pixelSize: Type.caption
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }
        }
    }
}
