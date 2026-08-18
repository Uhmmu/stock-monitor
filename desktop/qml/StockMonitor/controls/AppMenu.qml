import QtQuick
import QtQuick.Controls
import StockMonitor

Menu {
    id: control
    padding: Space.xs
    delegate: AppMenuItem {}
    background: GlassSurface {
        material: "elevated"
        cornerRadius: Radius.panel
    }
}
