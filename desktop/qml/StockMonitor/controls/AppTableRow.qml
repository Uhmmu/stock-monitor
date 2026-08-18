import QtQuick
import QtQuick.Controls
import StockMonitor

ItemDelegate {
    id: control
    implicitHeight: Theme.compact ? 34 : 42
    leftPadding: Space.md
    rightPadding: Space.md
    font.family: Type.family
    font.pixelSize: Type.body
    Accessible.name: text

    contentItem: Label {
        text: control.text
        color: control.enabled ? Theme.textPrimary : Theme.disabled
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        color: control.down ? Theme.pressed : control.highlighted ? Theme.selected : control.hovered ? Theme.hover : "transparent"
        radius: Radius.compactControl
        border.width: control.visualFocus ? 2 : 0
        border.color: Theme.focus
    }
}
