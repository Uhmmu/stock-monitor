import QtQuick
import QtQuick.Effects
import StockMonitor

Item {
    id: root
    default property alias contentData: content.data
    property string material: "regular"
    property Item backdropSource: null
    property real cornerRadius: Radius.panel
    property int padding: 0
    property bool raised: material === "elevated"
    readonly property bool usesBackdrop: backdropSource && !Theme.transparencyReduced && !Theme.contrast && material !== "opaque"
    readonly property color materialColor: material === "clear" ? Theme.glassClear
        : material === "elevated" ? Theme.glassElevated
        : material === "opaque" ? Theme.contentRaised : Theme.glassRegular

    implicitWidth: content.implicitWidth + padding * 2
    implicitHeight: content.implicitHeight + padding * 2

    Rectangle {
        visible: root.raised && !Theme.contrast
        anchors.fill: surface
        anchors.topMargin: Elevation.transientOffset
        radius: root.cornerRadius
        color: Theme.dark ? Qt.rgba(0, 0, 0, Elevation.overlay) : Qt.rgba(0.12, 0.16, 0.24, Elevation.raised)
    }

    Item {
        id: surface
        anchors.fill: parent
        clip: true

        ShaderEffectSource {
            id: backdropSample
            anchors.fill: parent
            sourceItem: root.backdropSource
            sourceRect: {
                if (!root.backdropSource)
                    return Qt.rect(0, 0, 1, 1);
                const point = root.mapToItem(root.backdropSource, 0, 0);
                return Qt.rect(point.x, point.y, root.width, root.height);
            }
            textureSize: Qt.size(Math.max(1, Math.ceil(width / 2)), Math.max(1, Math.ceil(height / 2)))
            live: root.usesBackdrop
            visible: false
        }

        MultiEffect {
            anchors.fill: parent
            source: backdropSample
            visible: root.usesBackdrop
            blurEnabled: true
            blur: root.material === "clear" ? 0.18 : 0.42
            blurMax: 24
            blurMultiplier: 0.7
            saturation: 0.14
            brightness: Theme.dark ? 0 : 0.06
            autoPaddingEnabled: false
        }

        Rectangle {
            anchors.fill: parent
            color: root.materialColor
            radius: root.cornerRadius
        }
        Rectangle {
            anchors.fill: parent
            radius: root.cornerRadius
            opacity: root.material === "opaque" || Theme.transparencyReduced || Theme.dark ? 0 : 1
            gradient: Gradient {
                GradientStop { position: 0; color: Theme.glassEdge }
                GradientStop { position: 0.08; color: "transparent" }
                GradientStop { position: 0.72; color: Theme.ambientTint }
                GradientStop { position: 1; color: Theme.dark ? Qt.rgba(0, 0, 0, 0.10) : Qt.rgba(1, 1, 1, 0.12) }
            }
        }
        Rectangle {
            anchors.fill: parent
            radius: root.cornerRadius
            color: "transparent"
            border.width: Theme.contrast ? 2 : root.material === "opaque" ? 0 : 1
            border.color: Theme.contrast ? Theme.textPrimary : Theme.glassEdge
        }
        Item {
            id: content
            anchors.fill: parent
            anchors.margins: root.padding
        }
    }
}
