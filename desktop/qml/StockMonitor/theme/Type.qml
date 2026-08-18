pragma Singleton

import QtQuick

QtObject {
    readonly property string family: Application.font.family
    readonly property string numericFamily: "monospace"
    readonly property int display: 40
    readonly property int largeTitle: 30
    readonly property int title: 22
    readonly property int headline: 15
    readonly property int body: 14
    readonly property int callout: 13
    readonly property int caption: 12
    readonly property int micro: 10
    readonly property int numericDisplay: 38
    readonly property int numericBody: 15
    readonly property int data: 12
    readonly property int numeric: numericBody
}
