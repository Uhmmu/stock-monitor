import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import {
  CandidateStatusBadge,
  DataDiscrepancies,
  DiscoveryRunMetadata,
  RawCandidatePanel,
  chooseCandidateGroup,
  discoveryStatusText,
  visibleCandidateMetrics,
  type DiscoveryCandidate,
} from './OpportunityDiscovery'

describe('机会发现候选展示', () => {
  it('隐藏空指标且最多展示六项', () => {
    const rows=visibleCandidateMetrics({market_cap:100,pe_trailing:20,pe_forward:18,revenue_growth:.2,free_cash_flow:null as never,operating_margin:.3,price_to_sales:5,gross_margin:.6})
    expect(rows.map(row=>row.key)).not.toContain('free_cash_flow')
    expect(rows).toHaveLength(6)
  })

  it('切换到指定候选分组，并在无匹配时回到首组', () => {
    const groups=[{id:'core',name:'优质核心资产',type:'quality_core',summary:'',candidates:[]},{id:'gap',name:'组合补缺',type:'portfolio_complement',summary:'',candidates:[]}]
    expect(chooseCandidateGroup(groups,'gap').id).toBe('gap')
    expect(chooseCandidateGroup(groups,'missing').id).toBe('core')
  })

  it('用中文同时表达原始候选的本地状态', () => {
    expect(renderToStaticMarkup(<CandidateStatusBadge status="already_held"/>)).toContain('已持有')
    expect(renderToStaticMarkup(<CandidateStatusBadge status="rejected"/>)).toContain('已过滤')
  })

  it('渲染运行成本与工具调用元数据', () => {
    const result={
      id:1,status:'completed',stage:'completed',trigger:'manual',requested_at:'2026-07-24T00:00:00Z',started_at:'2026-07-24T00:00:01Z',completed_at:'2026-07-24T00:01:00Z',analysis_date:'2026-07-24',next_scheduled_at:null,
      model_requested:'openai/gpt-5.4-mini',model_used:'openai/gpt-5.4-mini',prompt_version:'stock-discovery-prompt-v0.4',schema_version:'stock-discovery-schema-v0.4',filter_version:'stock-discovery-filter-v0.4',warnings:[],failure_code:null,failure_reason:null,previous_successful_run_id:null,
      usage:{input_tokens:100,output_tokens:200,total_tokens:300,finance_search_calls:3,web_search_calls:1,tool_cost_usd:.02,model_cost_usd:.01,total_cost_usd:.03},
      market_context:{},portfolio_diagnosis:{overweight:[],missing:[],strength:[],vulnerability:[]},capital_flows:{strong:[],early:[]},groups:[],raw_candidates:[],filtered_candidates:[],counts:{raw:0,accepted:0,watch_only:0,rejected:0},portfolio_actions:[],limitations:[],
    }
    const html=renderToStaticMarkup(<DiscoveryRunMetadata result={result}/>)
    expect(html).toContain('金融搜索次数')
    expect(html).toContain('$0.0300')
    expect(discoveryStatusText(result.status)).toBe('已完成')
  })

  it('在原始候选区保留本地过滤状态', () => {
    const candidate={id:7,raw_ticker:'APP',normalized_ticker:'APP',company_name:'AppLovin',priority:'low',
      display_status:'watch_only',groups:[{id:'hot',name:'过热观察',type:'watch_only',reason:'动量过热'}]} as DiscoveryCandidate
    const html=renderToStaticMarkup(<RawCandidatePanel items={[candidate]} onDetail={()=>undefined}/>)
    expect(html).toContain('原始候选')
    expect(html).toContain('APP')
    expect(html).toContain('仅观察')
  })

  it('明确并列展示来源冲突值', () => {
    const html=renderToStaticMarkup(<DataDiscrepancies items={[{metric:'pe_forward',values:[
      {source:'perplexity_finance',value:28,period:'FY2026'},
      {source:'yfinance',value:34,period:'2026-07-24'},
    ]}]}/>)
    expect(html).toContain('发现数据差异')
    expect(html).toContain('perplexity_finance 28')
    expect(html).toContain('yfinance 34')
  })
})
