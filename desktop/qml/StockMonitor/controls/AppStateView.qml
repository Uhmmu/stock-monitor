import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import StockMonitor

Item {
    id: control
    property string kind: "empty"
    property string title: kind === "loading" ? "正在加载" : kind === "error" ? "加载失败" : "暂无数据"
    property string message: ""
    signal retryRequested
    implicitWidth: 260
    implicitHeight: 150

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width, 320)
        spacing: Space.sm
        BusyIndicator {
            Layout.alignment: Qt.AlignHCenter
            visible: control.kind === "loading"
            running: visible
            palette.dark: Theme.textPrimary
            palette.light: Theme.textSecondary
        }
        Label {
            Layout.fillWidth: true
            text: control.kind === "error" ? "!" : control.kind === "empty" ? "—" : ""
            visible: control.kind !== "loading"
            color: control.kind === "error" ? Theme.negative : Theme.textSecondary
            font.pixelSize: Type.title
            horizontalAlignment: Text.AlignHCenter
        }
        Label {
            Layout.fillWidth: true
            text: control.title
            color: Theme.textPrimary
            font.pixelSize: Type.body
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
        }
        Label {
            Layout.fillWidth: true
            text: control.message
            visible: text.length > 0
            color: Theme.textSecondary
            font.pixelSize: Type.caption
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
        }
        AppButton {
            Layout.alignment: Qt.AlignHCenter
            visible: control.kind === "error"
            text: "重试"
            onClicked: control.retryRequested()
        }
    }
}
