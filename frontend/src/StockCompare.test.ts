import { describe, expect, it } from 'vitest'
import { buildCompareConclusion, filterCompareMetrics, formatCompareValue, type CompareMetric } from './StockCompare'

const metric=(overrides:Partial<CompareMetric>={}):CompareMetric=>({
  definition:{key:'roic',label:'ROIC',category:'资本效率',unit:'%',format:'percent',source:'valuation_snapshot',direction:'higher_better',sortable:true,supports_rank:true,supports_percentile:true,supports_history:true,cross_industry_comparable:false,comparison_mode:'percentage_point',missing_policy:'show',description:'投入资本回报率'},
  cells:{A:{value:20,status:'available',source:'valuation_snapshot',as_of:'2026-08-10',period:'FY2025',rank:1,percentile:100,is_best:true,is_worst:false,relative:null,trend:'improving'}},
  available_count:1,dispersion:.2,is_differentiator:true,period_mismatch:false,comparison_warning:null,...overrides,
})

describe('Stock Compare 指标展示',()=>{
  it('按分类、搜索和明显差异筛选 registry 指标',()=>{
    const rows=[metric(),metric({definition:{...metric().definition,key:'price',label:'当前价格',category:'行情'},is_differentiator:false})]
    expect(filterCompareMetrics(rows,'roic','all',false,false).map(row=>row.definition.key)).toEqual(['roic'])
    expect(filterCompareMetrics(rows,'','资本效率',false,false)).toHaveLength(1)
    expect(filterCompareMetrics(rows,'','all',false,true).map(row=>row.definition.key)).toEqual(['roic'])
  })

  it('隐藏全缺失指标，但保留部分缺失指标',()=>{
    expect(filterCompareMetrics([metric({available_count:0})],'','all',true,false)).toHaveLength(0)
    expect(filterCompareMetrics([metric({available_count:1})],'','all',true,false)).toHaveLength(1)
  })

  it('按照 definition 的格式而不是 metric key 渲染',()=>{
    expect(formatCompareValue(18.25,{format:'percent',unit:'%'})).toBe('18.3%')
    expect(formatCompareValue(2.5,{format:'number',unit:'multiple'})).toBe('2.5×')
    expect(formatCompareValue(null,{format:'number',unit:'number'})).toBe('数据不足')
  })

  it('用最新已存价格计算目标空间，并对非美元估值隐藏未校验结论',()=>{
    const row=(key:string,value:number)=>metric({
      definition:{...metric().definition,key},
      cells:{A:{...metric().cells.A,value}},
    })
    const rows=[row('price',110),row('consensus_fair_value',121),row('dcf_base_value',99),row('return_3m_pct',12)]
    const usd=buildCompareConclusion(rows,'A','USD')
    expect(usd.targetDistance).toBeCloseTo(10)
    expect(usd.dcfDistance).toBeCloseTo(-10)
    expect(usd.quarter).toBe(12)
    expect(buildCompareConclusion(rows,'A','JPY').target).toBeNull()
  })
})
