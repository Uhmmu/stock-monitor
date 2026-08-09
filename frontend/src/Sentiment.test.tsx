import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { compactNumber, SentimentContent, SentimentSkeleton, sentimentTone, type StockSentiment } from './Sentiment'

const data:StockSentiment = {
  symbol:'AAPL',
  company_name:'Apple Inc.',
  period_days:7,
  average_buzz:72.5,
  bullish_average:63.2,
  source_alignment:'Bullish alignment',
  available_sources:2,
  sources:[
    {source:'reddit',label:'Reddit',company_name:'Apple Inc.',buzz_score:80,bullish_pct:68,trend:'rising',metric_label:'Mentions',metric_value:12400},
    {source:'polymarket',label:'Polymarket',company_name:'Apple Inc.',buzz_score:65,bullish_pct:null,trend:null,metric_label:'Trades',metric_value:320},
  ],
}

describe('舆情板块',()=>{
  it('展示聚合值、中文共识和实际来源覆盖',()=>{
    const html=renderToStaticMarkup(<SentimentContent data={data}/>)
    expect(html).toContain('AAPL')
    expect(html).toContain('多源偏多')
    expect(html).toContain('2<small> / 4</small>')
    expect(html).toContain('最近 7 天')
  })

  it('明确保留缺失的看多数据，不伪造数值',()=>{
    const html=renderToStaticMarkup(<SentimentContent data={data}/>)
    expect(html).toContain('数据不足')
    expect(html).toContain('趋势不足')
  })

  it('紧凑预览用四个圆环分别展示固定来源',()=>{
    const html=renderToStaticMarkup(<SentimentContent data={data} compact/>)
    expect(html).toContain('AAPL')
    expect(html).toContain('最近 7 天')
    expect(html).not.toContain('讨论温度与方向')
    expect(html.match(/sentiment-preview-source/g)).toHaveLength(4)
    expect(html).toContain('Reddit')
    expect(html).toContain('Polymarket')
    expect(html).toContain('数据不足')
  })

  it('按看多比例提供稳定的语义色阶',()=>{
    expect(sentimentTone(70)).toBe('positive')
    expect(sentimentTone(30)).toBe('negative')
    expect(sentimentTone(50)).toBe('neutral')
    expect(sentimentTone(null)).toBe('neutral')
  })

  it('加载骨架带有忙碌状态且大数字紧凑展示',()=>{
    const html=renderToStaticMarkup(<SentimentSkeleton/>)
    expect(html).toContain('aria-busy="true"')
    expect(compactNumber(12400)).toMatch(/1[.,]2万|12[.,]4K/i)
  })
})
