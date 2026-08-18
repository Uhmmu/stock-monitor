import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import StockMonitor

Button {
    id: control
    property string kind: "secondary"
    property bool loading: false
    property bool glass: false
    property Item backdropSource: null

    implicitHeight: Theme.compact ? 34 : 40
    leftPadding: Space.lg
    rightPadding: Space.lg
    topPadding: Space.sm
    bottomPadding: Space.sm
    enabled: !loading
    Accessible.name: text

    contentItem: RowLayout {
        spacing: Space.sm
        BusyIndicator {
            visible: control.loading
            running: visible
            implicitWidth: 18
            implicitHeight: 18
            palette.dark: control.kind === "primary" ? "white" : Theme.textPrimary
        }
        Label {
            Layout.fillWidth: true
            text: control.text
            color: !control.enabled ? Theme.disabled : control.kind === "primary" ? "white" : control.kind === "danger" ? Theme.negative : Theme.textPrimary
            font.family: Type.family
            font.pixelSize: Type.body
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    background: Item {
        GlassSurface {
            anchors.fill: parent
            material: control.glass ? "regular" : "opaque"
            backdropSource: control.backdropSource
            cornerRadius: control.implicitHeight >= 40 ? Radius.capsule : Radius.control
        }
        Rectangle {
            anchors.fill: parent
            radius: control.implicitHeight >= 40 ? Radius.capsule : Radius.control
            color: {
                if (!control.enabled)
                    return Theme.dark ? Qt.rgba(1, 1, 1, 0.03) : Qt.rgba(0, 0, 0, 0.03);
                if (control.down)
                    return control.kind === "primary" ? Theme.accentStrong : Theme.pressed;
                if (control.checked)
                    return Theme.selected;
                if (control.hovered)
                    return control.kind === "primary" ? Theme.accentStrong : Theme.hover;
                return control.kind === "primary" ? Theme.accent : "transparent";
            }
            border.width: control.visualFocus ? 2 : control.kind === "danger" ? 1 : 0
            border.color: control.visualFocus ? Theme.focus : Theme.negative
            Behavior on color { ColorAnimation { duration: Motion.duration(Motion.fast) } }
        }
    }
}
