pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import StockMonitor

Item {
    id: page
    required property var dashboard
    readonly property int quoteColumnWidth: 112

    function number(value, digits) {
        return typeof value === "number" && isFinite(value)
                ? value.toLocaleString(Qt.locale("en_US"), "f", digits) : "数据不足"
    }
    function money(value, currency) {
        if (typeof value !== "number" || !isFinite(value))
            return "数据不足"
        const code = currency || page.dashboard.baseCurrency || "USD"
        const prefix = code === "USD" ? "$" : code + " "
        return prefix + value.toLocaleString(Qt.locale("en_US"), "f", 2)
    }
    Component.onCompleted: dashboard.setActive(visible)
    onVisibleChanged: dashboard.setActive(visible)
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
                    color: page.dashboard.loaded ? Theme.positive : Theme.textTertiary
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Space.xxs
                    Label {
                        text: !page.dashboard.loaded ? "正在读取持仓摘要"
                              : "当前持仓"
                        color: Theme.textPrimary
                        font.pixelSize: Type.headline
                        font.weight: Font.DemiBold
                    }
                    Label {
                        text: page.dashboard.positionCount + " 个持仓 · "
                              + page.dashboard.pricedCount + "/" + page.dashboard.positionCount + " 有价格"
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
                    Accessible.description: "重新读取持仓摘要"
                    onClicked: page.dashboard.refresh()
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: page.width >= 840 ? 3 : 1
                columnSpacing: Space.lg
                rowSpacing: Space.sm
                Repeater {
                    model: [
                        {label: "组合净值", value: page.dashboard.netAssetValue},
                        {label: "持仓市值", value: page.dashboard.totalMarketValue},
                        {label: "现金", value: page.dashboard.cash}
                    ]
                    delegate: ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: Space.xxs
                        Label {
                            text: modelData.label
                            color: Theme.textSecondary
                            font.pixelSize: Type.caption
                        }
                        Label {
                            text: page.money(modelData.value, page.dashboard.baseCurrency)
                            color: Theme.textPrimary
                            font.family: Type.numericFamily
                            font.pixelSize: Type.numericBody
                            font.weight: Font.DemiBold
                        }
                    }
                }
            }
            Label {
                visible: page.dashboard.hasUnpricedPositions || page.dashboard.hasUnconvertedPositions
                text: "部分持仓暂未计入组合汇总，相关金额显示为数据不足。"
                color: Theme.warning
                font.pixelSize: Type.caption
                wrapMode: Text.Wrap
                Layout.fillWidth: true
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
                            text: "当前持仓"
                            color: Theme.textPrimary
                            font.pixelSize: Type.title
                            font.weight: Font.DemiBold
                        }
                        Label {
                            text: page.dashboard.positionCount + " 项"
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
                        Label { Layout.preferredWidth: page.quoteColumnWidth; Layout.minimumWidth: page.quoteColumnWidth; Layout.maximumWidth: page.quoteColumnWidth; text: "现价"; color: Theme.textTertiary; font.pixelSize: Type.micro; horizontalAlignment: Text.AlignRight }
                        Label { Layout.preferredWidth: page.quoteColumnWidth; Layout.minimumWidth: page.quoteColumnWidth; Layout.maximumWidth: page.quoteColumnWidth; text: "今日"; color: Theme.textTertiary; font.pixelSize: Type.micro; horizontalAlignment: Text.AlignRight }
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
                        Accessible.name: "当前持仓行情"

                        delegate: ItemDelegate {
                            id: quoteRow
                            required property int index
                            required property string ticker
                            required property var quantity
                            required property string currency
                            required property var price
                            required property var changePercent
                            required property bool hasLive
                            required property bool hasData
                            width: quoteList.width
                            height: page.width >= 760 ? (Theme.compact ? 56 : 64) : (Theme.compact ? 70 : 80)
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
                                spacing: Space.lg
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: Space.xxs
                                    Label { text: quoteRow.ticker; color: Theme.textPrimary; font.pixelSize: Type.numericBody; font.weight: Font.DemiBold }
                                    Label {
                                        text: "持仓 " + page.number(quoteRow.quantity, 4) + " 股 · "
                                              + (quoteRow.currency || page.dashboard.baseCurrency || "币种未知")
                                        color: Theme.textSecondary
                                        font.pixelSize: Type.caption
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                }
                                Label {
                                    Layout.preferredWidth: page.quoteColumnWidth
                                    Layout.minimumWidth: page.quoteColumnWidth
                                    Layout.maximumWidth: page.quoteColumnWidth
                                    text: page.money(quoteRow.price, quoteRow.currency || page.dashboard.baseCurrency)
                                    color: Theme.textPrimary
                                    font.family: Type.numericFamily
                                    font.pixelSize: Type.numericBody
                                    horizontalAlignment: Text.AlignRight
                                }
                                Label {
                                    Layout.preferredWidth: page.quoteColumnWidth
                                    Layout.minimumWidth: page.quoteColumnWidth
                                    Layout.maximumWidth: page.quoteColumnWidth
                                    text: typeof quoteRow.changePercent === "number" && isFinite(quoteRow.changePercent)
                                          ? (quoteRow.changePercent >= 0 ? "+" : "") + page.number(quoteRow.changePercent, 2) + "%" : "数据不足"
                                    color: typeof quoteRow.changePercent !== "number" || !isFinite(quoteRow.changePercent)
                                           ? Theme.textTertiary : quoteRow.changePercent >= 0 ? Theme.positive : Theme.negative
                                    font.family: Type.numericFamily
                                    font.pixelSize: Type.numericBody
                                    horizontalAlignment: Text.AlignRight
                                }
                            }
                        }
                    }
                    AppStateView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        visible: !page.dashboard.hasData
                        kind: page.dashboard.busy ? "loading" : page.dashboard.error.length > 0 ? "error" : "empty"
                        title: page.dashboard.busy ? "正在加载" : page.dashboard.error.length > 0 ? "加载失败" : "还没有持仓"
                        message: kind === "empty" ? "添加第一笔持仓后，这里会显示持仓行情与实时更新。" : page.dashboard.error
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
