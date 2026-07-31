import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import {
  MarketSnapshotContent,
  MarketSnapshotState,
  priceRangePosition,
  type PriceSnapshot,
} from './MarketSnapshot'

const snapshot:PriceSnapshot={
  id:1,symbol:'MSFT',exchange:'NASDAQ',currency:'USD',source_type:'price_snapshot',
  provider:'yfinance',provider_symbol:'MSFT',provider_role:'market_data_aggregator',
  last_price:105,open_price:101,day_high:110,day_low:100,previous_close:102,
  price_change:3,price_change_percent:2.9412,day_volume:18_000_000,
  average_volume_10d:19_000_000,average_volume_20d:20_000_000,
  relative_volume_20d:.9,relative_volume_basis:'full_day_average',
  market_timestamp:'2026-07-31T03:59:27Z',trading_date:'2026-07-30',
  market_session:'closed',snapshot_market_session:'after_hours',timestamp_source:'provider',
  fetched_at:'2026-07-31T04:00:00Z',persisted_at:'2026-07-31T04:00:01Z',
  is_delayed:true,delay_seconds:900,is_stale:false,age_seconds:42,
  stale_after_seconds:900,age_basis:'market_timestamp',
}

describe('persisted market snapshot',()=>{
  it('renders price, source, exact times, and volume basis',()=>{
    const html=renderToStaticMarkup(<MarketSnapshotContent snapshot={snapshot}/>)
    expect(html).toContain('MSFT')
    expect(html).toContain('Yahoo Finance')
    expect(html).toContain('市场数据聚合商')
    expect(html).toContain('对比完整交易日均量')
    expect(html).toMatch(/GMT|UTC/)
  })

  it('renders missing optional fields without NaN or Infinity',()=>{
    const html=renderToStaticMarkup(<MarketSnapshotContent snapshot={{...snapshot,day_high:null,day_low:null,open_price:null,relative_volume_20d:null}}/>)
    expect(html).toContain('--')
    expect(html).not.toContain('NaN')
    expect(html).not.toContain('Infinity')
  })

  it('handles a flat range and clamps out-of-range prices',()=>{
    expect(priceRangePosition({...snapshot,last_price:100,day_low:100,day_high:100})).toBeNull()
    expect(priceRangePosition({...snapshot,last_price:120,day_low:100,day_high:110})).toBe(100)
    expect(priceRangePosition({...snapshot,last_price:90,day_low:100,day_high:110})).toBe(0)
  })

  it('shows stale and all async states',()=>{
    expect(renderToStaticMarkup(<MarketSnapshotContent snapshot={{...snapshot,is_stale:true}}/>)).toContain('数据可能已过期')
    expect(renderToStaticMarkup(<MarketSnapshotState state="loading"/>)).toContain('正在读取')
    expect(renderToStaticMarkup(<MarketSnapshotState state="error"/>)).toContain('读取失败')
    expect(renderToStaticMarkup(<MarketSnapshotState state="empty"/>)).toContain('暂无')
  })
})
