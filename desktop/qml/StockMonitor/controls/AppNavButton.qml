import QtQuick
import StockMonitor

AppButton {
    id: control
    kind: "secondary"
    checkable: true
    implicitHeight: Theme.compact ? 34 : 40

    background: Rectangle {
        radius: Radius.control
        color: control.down ? Theme.pressed : control.checked ? Theme.selected : control.hovered ? Theme.hover : "transparent"
        border.width: control.visualFocus ? 2 : 0
        border.color: Theme.focus
    }
}
