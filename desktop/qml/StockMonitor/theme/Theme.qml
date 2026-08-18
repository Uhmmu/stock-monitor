pragma Singleton

import QtQuick
import QtCore

QtObject {
    id: theme

    property string mode: "system"
    property bool highContrast: false
    property bool reducedMotion: false
    property bool reducedTransparency: false
    property string density: "comfortable"

    // Preview overrides let tests/screenshots stay deterministic without changing user settings.
    property string previewMode: ""
    property int previewContrast: -1
    property int previewReducedMotion: -1
    property int previewReducedTransparency: -1
    property string previewDensity: ""

    readonly property string effectiveMode: previewMode.length > 0 ? previewMode : mode
    readonly property bool dark: effectiveMode === "dark" || (effectiveMode === "system" && Application.styleHints.colorScheme === Qt.Dark)
    readonly property bool contrast: previewContrast < 0 ? highContrast : previewContrast === 1
    readonly property bool motionReduced: previewReducedMotion < 0 ? reducedMotion : previewReducedMotion === 1
    readonly property bool transparencyReduced: previewReducedTransparency < 0 ? reducedTransparency : previewReducedTransparency === 1
    readonly property string effectiveDensity: previewDensity.length > 0 ? previewDensity : density
    readonly property bool compact: effectiveDensity === "compact"

    readonly property color canvas: contrast ? (dark ? "#000000" : "#ffffff") : (dark ? "#080a0f" : "#f1f3f7")
    readonly property color surface: contrast ? (dark ? "#0b0b0b" : "#ffffff") : (dark ? "#11141b" : "#fbfbfd")
    readonly property color contentRaised: contrast ? surface : (dark ? "#151922" : "#ffffff")
    readonly property color elevated: contrast ? (dark ? "#171717" : "#f4f4f4") : (dark ? "#202631" : "#f8f9fc")
    readonly property color textPrimary: dark ? "#f4f5f8" : "#17191f"
    readonly property color textSecondary: contrast ? (dark ? "#ffffff" : "#000000") : (dark ? "#a6acb8" : "#626873")
    readonly property color textTertiary: contrast ? textSecondary : (dark ? "#747c89" : "#8b919b")
    readonly property color accent: dark ? "#79a9ff" : "#3478f6"
    readonly property color accentStrong: dark ? "#5792fb" : "#1762d2"
    readonly property color positive: dark ? "#55d896" : "#118557"
    readonly property color negative: dark ? "#ff7b82" : "#ca3844"
    readonly property color warning: dark ? "#efbd58" : "#976100"
    readonly property color separator: contrast ? textPrimary : (dark ? Qt.rgba(1, 1, 1, 0.10) : Qt.rgba(0, 0, 0, 0.10))
    readonly property color focus: dark ? "#b4d0ff" : "#1b64d8"
    readonly property color hover: dark ? Qt.rgba(1, 1, 1, 0.07) : Qt.rgba(0, 0, 0, 0.05)
    readonly property color pressed: dark ? Qt.rgba(1, 1, 1, 0.13) : Qt.rgba(0, 0, 0, 0.10)
    readonly property color selected: dark ? Qt.rgba(0.31, 0.55, 0.95, 0.24) : Qt.rgba(0.13, 0.39, 0.86, 0.13)
    readonly property color disabled: dark ? "#626978" : "#a1a6af"
    readonly property color chromeOpaque: contrast ? surface : (dark ? "#191d26" : "#f7f8fb")
    readonly property color glassRegular: transparencyReduced ? chromeOpaque : (dark ? Qt.rgba(0.10, 0.12, 0.16, 0.82) : Qt.rgba(0.97, 0.98, 1, 0.78))
    readonly property color glassClear: transparencyReduced ? chromeOpaque : (dark ? Qt.rgba(0.14, 0.16, 0.21, 0.54) : Qt.rgba(1, 1, 1, 0.52))
    readonly property color glassElevated: transparencyReduced ? elevated : (dark ? Qt.rgba(0.13, 0.15, 0.20, 0.94) : Qt.rgba(0.98, 0.98, 1, 0.92))
    readonly property color glassEdge: contrast ? textPrimary : (dark ? Qt.rgba(1, 1, 1, 0.16) : Qt.rgba(1, 1, 1, 0.80))
    readonly property color ambientTint: dark ? "transparent" : Qt.rgba(0.33, 0.52, 0.92, 0.10)
    readonly property color chrome: glassRegular
    readonly property int borderWidth: contrast ? 2 : 0

    property Settings settings: Settings {
        category: "appearance"
        location: StandardPaths.writableLocation(StandardPaths.AppConfigLocation) + "/appearance.ini"
        property alias mode: theme.mode
        property alias highContrast: theme.highContrast
        property alias reducedMotion: theme.reducedMotion
        property alias reducedTransparency: theme.reducedTransparency
        property alias density: theme.density
    }
}
