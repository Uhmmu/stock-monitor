import QtQuick
import QtTest
import StockMonitor

TestCase {
    id: testCase

    function test_loads_and_uses_virtualized_lists() {
        const page = createTemporaryObject(pageComponent, testCase, {
            "width": 1050,
            "height": 680
        });
        verify(page);
        compare(page.watchlist.watchlistedCount, 1);
        compare(page.watchlist.matchedCount, 1);
        page.width = 620;
        wait(0);
        compare(page.width, 620);
    }

    function test_deactivates_stream_when_hidden() {
        const page = createTemporaryObject(pageComponent, testCase, {
            "width": 900,
            "height": 600
        });
        verify(page);
        page.visible = false;
        tryCompare(watchlistStub, "active", false);
    }

    name: "WatchlistPage"
    when: windowShown
    width: 1100
    height: 720

    ListModel {
        id: watchlistedModel
        Component.onCompleted: append({
            id: 7,
            ticker: "7203.T",
            companyName: "Toyota",
            officialSector: "Consumer Cyclical",
            officialIndustry: "Auto",
            userGroupId: -1,
            price: 2500,
            changePercent: 1.2,
            hasPrice: true,
            displayOrder: 0
        })
    }

    ListModel {
        id: matchedModel
        Component.onCompleted: append({
            ticker: "MSFT",
            companyName: "Microsoft",
            peerReferencedBy: ["7203.T"]
        })
    }

    QtObject {
        id: watchlistStub

        property bool active: false
        property bool busy: false
        property bool mutationBusy: false
        property bool loaded: true
        property bool hasData: true
        property bool stale: false
        property string error: ""
        property string streamStatus: "connected"
        property int fetchedAtMs: 0
        property int watchlistedCount: watchlistedModel.count
        property int matchedCount: matchedModel.count
        property int sectionCount: 1
        property var groups: [{
            "id": 4,
            "name": "芯片",
            "displayOrder": 0
        }]
        property var watchlisted: watchlistedModel
        property var matched: matchedModel
        property string searchQuery: ""
        property bool searchBusy: false
        property string searchError: ""
        property var searchResults: []

        function setActive(value) {
            active = value;
        }

        function refresh() {
        }

        function search(value) {
            searchQuery = value;
        }

        function clearSearch() {
            searchQuery = "";
            searchResults = [];
        }

        function addSecurity(value) {
        }

        function promoteMatched(value) {
        }

        function createGroup(value) {
        }

        function renameGroup(id, value) {
        }

        function deleteGroup(id) {
        }

        function moveGroup(id, order) {
        }

        function updateWatchlist(id, fields) {
        }

        function moveWatchlist(id, order) {
        }

        function removeWatchlist(id) {
        }

    }

    Component {
        id: pageComponent

        WatchlistPage {
            watchlist: watchlistStub
        }

    }

}
