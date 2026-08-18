pragma Singleton

import QtQuick
import StockMonitor

QtObject {
    readonly property int fast: 100
    readonly property int normal: 220
    readonly property int slow: 360
    readonly property int continuity: 320
    readonly property int standard: Easing.OutCubic
    readonly property int emphasized: Easing.OutQuart
    readonly property real springSoft: 3.0
    readonly property real springSoftDamping: 0.32
    readonly property real springSnappy: 4.2
    readonly property real springSnappyDamping: 0.42

    function duration(value) {
        return Theme.motionReduced ? 0 : value;
    }
}
