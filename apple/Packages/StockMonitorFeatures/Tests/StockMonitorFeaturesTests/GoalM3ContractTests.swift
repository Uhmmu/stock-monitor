import Foundation
import StockMonitorFeatures
import Testing

@Test func goalM3RoutesAreBoundToNativeScreens() {
    #expect(AppRoute.overview.isGoalM3Route)
    #expect(AppRoute.watchlist.isGoalM3Route)
    #expect(AppRoute.alerts.isGoalM3Route)
    #expect(AppRoute.news.isGoalM3Route)
    #expect(AppRoute.calendar.isGoalM3Route)
    #expect(AppRoute.reports.isGoalM3Route)
    #expect(!AppRoute.fundamentals.isGoalM3Route)
}

@Test func dashboardContractDecodesMissingFinancialDataWithoutInventingValues() throws {
    let data = Data(#"""
    {
      "market":{"is_open":false,"session":null,"checked_at":"2026-09-05T12:00:00+00:00"},
      "stocks":[{
        "ticker":"AAPL","price":null,"previous_close":200.0,"price_source":"yfinance",
        "updated_at":null,"volume":null,"volume_ratio":null,"volume_label":null,"company_name":"Apple"
      }]
    }
    """#.utf8)
    let value = try JSONDecoder().decode(DashboardSnapshot.self, from: data)
    #expect(value.stocks.first?.price == nil)
    #expect(value.stocks.first?.changePercent == nil)
}

@Test func watchlistThresholdPatchCanExplicitlyClearServerOverrides() throws {
    let request = WatchlistUpdateRequest(
        threshold20m: nil, threshold1h: nil, thresholdDay: nil, includeThresholds: true
    )
    let object = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: Any])
    #expect(object.keys.contains("threshold_20m"))
    #expect(object["threshold_20m"] is NSNull)
    #expect(object.keys.contains("threshold_1h"))
    #expect(object.keys.contains("threshold_day"))
    #expect(!object.keys.contains("alert_enabled"))
}

@Test func pagedContentContractsDecodeFreshnessAndSourceState() throws {
    let news = Data(#"""
    {
      "items":[{
        "id":1,"ticker":null,"provider":"finnhub","title":"Market","translated_title":null,
        "url":"https://example.com/a","source":"wire","summary":null,"topic":"macro","published_at":null,
        "found_at":"2026-09-05T12:00:00+00:00","ai_summary":null,"ai_analysis":null,
        "ai_summary_status":"pending","ai_summary_generated_at":null
      }],
      "total":1,"generated_at":"2026-09-05T12:01:00+00:00","last_updated_at":"2026-09-05T12:00:00+00:00","sources":["finnhub"]
    }
    """#.utf8)
    let page = try JSONDecoder().decode(MarketNewsPage.self, from: news)
    #expect(page.items.first?.displayTitle == "Market")
    #expect(page.sources == ["finnhub"])

    let calendar = Data(#"""
    {
      "items":[{
        "id":2,"event_type":"earnings","symbol":"AAPL","company_name":"Apple","title":"财报","description":null,
        "event_date":"2026-09-10","event_time":null,"time_status":"unknown","is_confirmed":false,
        "is_estimated":true,"confidence":0.7,"impact_level":"high","primary_source":"yahoo","has_conflict":false,
        "portfolio_relevance":true,"watchlist_relevance":true,"fetched_at":"2026-09-05T12:00:00+00:00",
        "stale":true,"warning":"当前展示最近一次有效缓存。"
      }],
      "total":1,"next_cursor":null,"generated_at":"2026-09-05T12:01:00+00:00"
    }
    """#.utf8)
    let events = try JSONDecoder().decode(CalendarPage.self, from: calendar)
    #expect(events.items.first?.stale == true)
    #expect(events.items.first?.primarySource == "yahoo")
}
