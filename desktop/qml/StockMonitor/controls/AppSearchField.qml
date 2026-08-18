import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import StockMonitor

FocusScope {
    id: control
    property bool expanded: false
    property int expandedWidth: 300
    property string placeholderText: "Search"
    property alias text: input.text
    property Item backdropSource: null
    signal accepted(string text)

    function activate() {
        expanded = true;
        Qt.callLater(input.forceActiveFocus);
    }

    implicitWidth: expanded ? expandedWidth : implicitHeight
    implicitHeight: Theme.compact ? 36 : 42
    clip: true
    Accessible.role: Accessible.EditableText
    Accessible.name: placeholderText

    Behavior on implicitWidth {
        NumberAnimation {
            duration: Motion.duration(Motion.continuity)
            easing.type: Motion.emphasized
        }
    }

    GlassSurface {
        anchors.fill: parent
        material: "regular"
        backdropSource: control.backdropSource
        cornerRadius: Radius.capsule
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Space.md
        anchors.rightMargin: Space.sm
        spacing: Space.sm
        Label {
            text: "⌕"
            color: control.expanded ? Theme.textPrimary : Theme.textSecondary
            font.pixelSize: 20
            horizontalAlignment: Text.AlignHCenter
            Layout.preferredWidth: 18
        }
        TextField {
            id: input
            Layout.fillWidth: true
            Layout.fillHeight: true
            opacity: control.expanded ? 1 : 0
            enabled: control.expanded
            placeholderText: control.placeholderText
            color: Theme.textPrimary
            placeholderTextColor: Theme.textTertiary
            selectionColor: Theme.accent
            font.family: Type.family
            font.pixelSize: Type.body
            background: null
            onAccepted: control.accepted(text)
            Keys.onEscapePressed: {
                clear();
                control.expanded = false;
                control.forceActiveFocus(Qt.BacktabFocusReason);
            }
            Behavior on opacity {
                NumberAnimation { duration: Motion.duration(Motion.normal) }
            }
        }
        Label {
            visible: control.expanded && input.text.length > 0
            text: "×"
            color: Theme.textSecondary
            font.pixelSize: 18
            Layout.preferredWidth: 24
            Accessible.role: Accessible.Button
            Accessible.name: "Clear search"
            TapHandler { onTapped: input.clear() }
        }
    }

    TapHandler {
        enabled: !control.expanded
        onTapped: control.activate()
    }
}
