import QtQuick
import QtQuick.Controls
import StockMonitor

TextField {
    id: control
    property bool invalid: false
    property string errorText: ""
    property bool glass: false

    implicitHeight: Theme.compact ? 34 : 40
    leftPadding: Space.md
    rightPadding: Space.md
    color: enabled ? Theme.textPrimary : Theme.disabled
    placeholderTextColor: Theme.textSecondary
    selectionColor: Theme.accent
    selectedTextColor: "white"
    font.family: Type.family
    font.pixelSize: Type.body
    Accessible.name: placeholderText
    Accessible.description: invalid ? errorText : ""

    background: Item {
        GlassSurface {
            anchors.fill: parent
            material: control.glass ? "regular" : "opaque"
            cornerRadius: Radius.control
        }
        Rectangle {
            anchors.fill: parent
            radius: Radius.control
            color: "transparent"
            border.width: control.invalid || control.activeFocus || Theme.contrast ? 2 : 0
            border.color: control.invalid ? Theme.negative : control.activeFocus ? Theme.focus : Theme.textPrimary
        }
    }
}
