pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import StockMonitor

FocusScope {
    id: control
    property var model: []
    property int currentIndex: 0
    property Item backdropSource: null

    implicitWidth: Math.max(180, model.length * 72 + 8)
    implicitHeight: Theme.compact ? 34 : 38
    Accessible.role: Accessible.List
    Accessible.name: "View selector"

    Keys.onLeftPressed: currentIndex = Math.max(0, currentIndex - 1)
    Keys.onRightPressed: currentIndex = Math.min(model.length - 1, currentIndex + 1)

    GlassSurface {
        anchors.fill: parent
        material: "clear"
        backdropSource: control.backdropSource
        cornerRadius: Radius.capsule
    }

    Rectangle {
        id: indicator
        x: 4 + control.currentIndex * width
        y: 4
        width: (control.width - 8) / Math.max(1, control.model.length)
        height: control.height - 8
        radius: Radius.capsule
        color: Theme.dark ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(1, 1, 1, 0.78)
        border.width: control.activeFocus && Theme.contrast ? 2 : 0
        border.color: Theme.focus
        Behavior on x {
            enabled: !Theme.motionReduced
            SpringAnimation {
                spring: Motion.springSnappy
                damping: Motion.springSnappyDamping
            }
        }
    }

    Row {
        anchors.fill: parent
        anchors.margins: 4
        Repeater {
            model: control.model
            delegate: Item {
                required property int index
                required property string modelData
                width: (control.width - 8) / Math.max(1, control.model.length)
                height: control.height - 8
                Accessible.role: Accessible.Button
                Accessible.name: modelData
                Accessible.checked: index === control.currentIndex
                Label {
                    anchors.centerIn: parent
                    text: parent.modelData
                    color: parent.index === control.currentIndex ? Theme.textPrimary : Theme.textSecondary
                    font.family: Type.family
                    font.pixelSize: Type.callout
                    font.weight: parent.index === control.currentIndex ? Font.DemiBold : Font.Normal
                }
                TapHandler {
                    onTapped: {
                        control.currentIndex = parent.index;
                        control.forceActiveFocus(Qt.MouseFocusReason);
                    }
                }
            }
        }
    }
}
