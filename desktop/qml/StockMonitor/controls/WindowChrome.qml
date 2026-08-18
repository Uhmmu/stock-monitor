pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import StockMonitor

Item {
    id: chrome
    property string title: "Stock Monitor"
    property bool interactive: true
    property Item backdropSource: null
    implicitHeight: Theme.compact ? 48 : 54

    GlassSurface {
        anchors.fill: parent
        material: "regular"
        backdropSource: chrome.backdropSource
        cornerRadius: 0
    }

    DragHandler {
        target: null
        enabled: chrome.interactive
        acceptedButtons: Qt.LeftButton
        onActiveChanged: {
            if (active && chrome.Window.window)
                chrome.Window.window.startSystemMove();
        }
    }
    TapHandler {
        enabled: chrome.interactive
        acceptedButtons: Qt.LeftButton
        onDoubleTapped: {
            const window = chrome.Window.window;
            if (!window)
                return;
            if (window.visibility === Window.Maximized)
                window.showNormal();
            else
                window.showMaximized();
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Space.lg
        anchors.rightMargin: Space.md
        spacing: Space.md
        Row {
            spacing: Space.sm
            Repeater {
                model: ["close", "minimize", "maximize"]
                delegate: Rectangle {
                    required property string modelData
                    width: 22
                    height: 22
                    radius: 11
                    color: buttonHover.hovered ? Theme.hover : "transparent"
                    border.width: Theme.contrast ? 2 : 0
                    border.color: Theme.textPrimary
                    Accessible.role: Accessible.Button
                    Accessible.name: modelData
                    Label {
                        anchors.centerIn: parent
                        text: parent.modelData === "close" ? "×" : parent.modelData === "minimize" ? "−" : "□"
                        color: Theme.textSecondary
                        font.pixelSize: parent.modelData === "maximize" ? 10 : 14
                    }
                    HoverHandler { id: buttonHover }
                    TapHandler {
                        enabled: chrome.interactive
                        onTapped: {
                            const window = chrome.Window.window;
                            if (!window)
                                return;
                            if (parent.modelData === "close")
                                window.close();
                            else if (parent.modelData === "minimize")
                                window.showMinimized();
                            else if (window.visibility === Window.Maximized)
                                window.showNormal();
                            else
                                window.showMaximized();
                        }
                    }
                }
            }
        }
        Label {
            Layout.fillWidth: true
            text: chrome.title
            color: Theme.textSecondary
            font.family: Type.family
            font.pixelSize: Type.callout
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
        }
        Item { Layout.preferredWidth: 82 }
    }
}
