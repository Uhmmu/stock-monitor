import QtQuick
import QtQuick.Controls
import StockMonitor

ToolTip {
    id: control
    delay: 500
    timeout: 5000
    padding: Space.sm
    contentItem: Label {
        text: control.text
        color: Theme.textPrimary
        font.family: Type.family
        font.pixelSize: Type.caption
    }
    background: GlassSurface {
        material: "elevated"
        cornerRadius: Radius.compactControl
    }
}
