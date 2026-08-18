pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import StockMonitor

ApplicationWindow {
    id: window
    required property var environment
    required property var session
    required property var dashboard
    width: 1120
    height: 720
    minimumWidth: 760
    minimumHeight: 520
    visible: true
    title: "Stock Monitor"
    color: Theme.canvas

    Loader {
        anchors.fill: parent
        sourceComponent: window.session.authenticated ? shellComponent : connectionComponent
    }

    Component {
        id: connectionComponent
        ConnectionPage {
            environment: window.environment
            session: window.session
        }
    }
    Component {
        id: shellComponent
        AppShell {
            session: window.session
            dashboard: window.dashboard
        }
    }
}
