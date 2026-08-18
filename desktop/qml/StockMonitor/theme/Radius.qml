pragma Singleton

import QtQuick

QtObject {
    readonly property int window: 24
    readonly property int panel: 20
    readonly property int control: 12
    readonly property int compactControl: 9
    readonly property int capsule: 999

    readonly property int small: compactControl
    readonly property int medium: control
    readonly property int large: panel
    readonly property int pill: capsule

    function inset(outerRadius, insetAmount) {
        return Math.max(compactControl, outerRadius - insetAmount);
    }
}
