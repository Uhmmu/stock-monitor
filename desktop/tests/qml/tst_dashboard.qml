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
            company: "Apple"
            price: 230.5
            changePercent: 1.2
            volumeLabel: "正常"
            source: "alpaca:iex"
            updatedAtMs: 1787104800000
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
        property bool marketOpen: true
        property string error: ""
        property string streamStatus: "connected"
        property date marketCheckedAt: new Date("2026-08-19T02:00:00Z")
        property int freshnessAgeSeconds: 30
        property int requestCount: 1
        property var quotes: quoteFixture
        property var recentEvents: [{symbol: "AAPL", eventType: "volume_spike", severity: "info"}]
        function setActive(value) { active = value }
        function refresh() { requestCount += 1 }
    }

    Component {
        id: pageComponent
        DashboardPage { dashboard: dashboardStub }
    }

    function test_responsiveInstantiation() {
        const page = createTemporaryObject(pageComponent, testCase, {width: 1050, height: 680})
        verify(page)
        compare(dashboardStub.active, true)
        page.width = 620
        wait(0)
        compare(page.width, 620)
    }
}
