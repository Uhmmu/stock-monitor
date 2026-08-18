import QtQuick
import QtQuick.Controls
import StockMonitor

Switch {
    id: control
    spacing: Space.md
    font.family: Type.family
    font.pixelSize: Type.body
    Accessible.name: text

    contentItem: Label {
        leftPadding: control.indicator.width + control.spacing
        text: control.text
        color: control.enabled ? Theme.textPrimary : Theme.disabled
        verticalAlignment: Text.AlignVCenter
    }
    indicator: Rectangle {
        x: 0
        y: (control.height - height) / 2
        implicitWidth: 42
        implicitHeight: 24
        radius: Radius.pill
        color: control.checked ? Theme.accent : Theme.hover
        border.width: control.visualFocus || Theme.contrast ? 2 : 0
        border.color: control.visualFocus ? Theme.focus : Theme.textPrimary

        Rectangle {
            width: 18
            height: 18
            radius: 9
            x: control.checked ? parent.width - width - 3 : 3
            anchors.verticalCenter: parent.verticalCenter
            color: control.checked ? "white" : Theme.textSecondary
            Behavior on x {
                enabled: !Theme.motionReduced
                SpringAnimation { spring: Motion.springSnappy; damping: Motion.springSnappyDamping }
            }
        }
    }
}
