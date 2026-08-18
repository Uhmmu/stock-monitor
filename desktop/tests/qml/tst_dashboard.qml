import QtQuick
import QtTest
import StockMonitor

TestCase {
    id: testCase
    name: "DashboardPage"
    when: windowShown
    width: 1100
    height: 720

    ListModel {
        id: quoteFixture
        ListElement {
            ticker: "AAPL"
            quantity: 10
            currency: "USD"
            price: 230.5
            changePercent: 1.2
            hasLive: true
            hasData: true
        }
    }

    QtObject {
        id: dashboardStub
        property bool active: false
        property bool busy: false
        property bool loaded: true
        property bool hasData: quoteFixture.count > 0
        property bool stale: false
        property string error: ""
        property string streamStatus: "connected"
        property int freshnessAgeSeconds: 30
        property string baseCurrency: "USD"
        property int positionCount: 1
        property int pricedCount: 1
        property real totalMarketValue: 2305
        property real netAssetValue: 2505
        property real cash: 200
        property real totalUnrealizedPnl: 100
        property bool hasUnpricedPositions: false
        property bool hasUnconvertedPositions: false
        property var quotes: quoteFixture
        property var recentEvents: [{symbol: "AAPL", eventType: "volume_spike", severity: "info"}]
        function setActive(value) { active = value }
        function refresh() { }
    }

    Component {
        id: pageComponent
        DashboardPage { dashboard: dashboardStub }
    }

    function test_responsiveInstantiation() {
        const page = createTemporaryObject(pageComponent, testCase, {width: 1050, height: 680})
        verify(page)
        page.visible = false
        tryCompare(dashboardStub, "active", false)
        page.width = 620
        wait(0)
        compare(page.width, 620)
    }
}
