import QtQuick
import QtQuick.Controls
import StockMonitor

Popup {
    id: control
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    padding: Space.xxl
    anchors.centerIn: Overlay.overlay
    width: Math.min(480, Overlay.overlay ? Overlay.overlay.width - Space.xxxl * 2 : 480)

    Overlay.modal: Rectangle {
        color: Qt.rgba(0, 0, 0, Theme.contrast ? 0.72 : 0.5)
    }
    background: GlassSurface {
        material: "elevated"
        cornerRadius: Radius.panel
    }
    enter: Transition {
        ParallelAnimation {
            NumberAnimation {
                property: "opacity"
                from: 0
                to: 1
                duration: Motion.duration(Motion.normal)
                easing.type: Motion.standard
            }
            NumberAnimation {
                property: "scale"
                from: Theme.motionReduced ? 1 : 0.96
                to: 1
                duration: Motion.duration(Motion.normal)
                easing.type: Motion.standard
            }
        }
    }
    exit: Transition {
        ParallelAnimation {
            NumberAnimation {
                property: "opacity"
                to: 0
                duration: Motion.duration(Motion.fast)
                easing.type: Motion.standard
            }
            NumberAnimation {
                property: "scale"
                to: Theme.motionReduced ? 1 : 0.96
                duration: Motion.duration(Motion.fast)
                easing.type: Motion.standard
            }
        }
    }
}
