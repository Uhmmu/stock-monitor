import { describe, expect, it } from 'vitest'
import {
  buildVolumeProfile,
  fibonacciPrices,
  prepareTechnicalChartData,
  type TechnicalMovingAverages,
  type WeeklyCandle,
} from './TechnicalChart'

const weekly:WeeklyCandle[]=[
  {time:'2026-07-13',open:100,high:108,low:98,close:106,volume:1200},
  {time:'2026-07-06',open:102,high:104,low:99,close:100,volume:1000},
]
const movingAverages:TechnicalMovingAverages={
  ma20:[{time:'2026-07-13',value:101.5}],
  ma50:[{time:'2026-07-13',value:99.5}],
}

describe('技术图表数据转换',()=>{
  it('排序周线并保留后端计算的 OHLC、成交量和均线值',()=>{
    const result=prepareTechnicalChartData(weekly,movingAverages)
    expect(result.candles.map(row=>row.time)).toEqual(['2026-07-06','2026-07-13'])
    expect(result.volume[1]).toMatchObject({time:'2026-07-13',value:1200})
    expect(result.ma20).toEqual([{time:'2026-07-13',value:101.5}])
    expect(result.ma50).toEqual([{time:'2026-07-13',value:99.5}])
  })

  it('拒绝无效或越界数据，不在前端编造 K 线与均线',()=>{
    const invalid:WeeklyCandle[]=[
      ...weekly,
      {time:'2026-07-20',open:100,high:99,low:98,close:101,volume:100},
      {time:'not-a-day',open:1,high:2,low:0,close:1,volume:1},
    ]
    const result=prepareTechnicalChartData(invalid,{
      ma20:[...movingAverages.ma20,{time:'2026-07-20',value:102}],
      ma50:[{time:'2026-07-13',value:Number.NaN}],
    })
    expect(result.candles).toHaveLength(2)
    expect(result.ma20).toHaveLength(1)
    expect(result.ma50).toEqual([])
  })

  it('手动斐波那契同时支持上升和下降锚点',()=>{
    expect(fibonacciPrices(100,200).find(item=>item.level===.5)?.price).toBe(150)
    expect(fibonacciPrices(200,100).find(item=>item.level===.618)?.price).toBeCloseTo(138.2)
  })

  it('成交量分布守恒且只使用当前缓存周期',()=>{
    const profile=buildVolumeProfile(weekly,8)
    expect(profile).toHaveLength(8)
    expect(profile.reduce((sum,item)=>sum+item.volume,0)).toBe(2200)
  })
})
