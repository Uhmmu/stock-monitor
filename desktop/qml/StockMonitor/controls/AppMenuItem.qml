import QtQuick
import QtQuick.Controls
import StockMonitor

MenuItem {
    id: control
    implicitHeight: 38
    leftPadding: Space.md
    rightPadding: Space.md
    contentItem: Label {
        text: control.text
        color: control.enabled ? Theme.textPrimary : Theme.disabled
        font.pixelSize: Type.body
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        color: control.down ? Theme.pressed : control.highlighted ? Theme.hover : "transparent"
        radius: Radius.small
        border.width: control.visualFocus ? 2 : 0
        border.color: Theme.focus
    }
}
