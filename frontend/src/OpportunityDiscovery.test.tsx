import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import {
  CandidateStatusBadge,
  DataDiscrepancies,
  DiscoveryRunMetadata,
  PiFunnelProgress,
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
      discovery_mode:'search_local' as const,
      usage:{input_tokens:100,output_tokens:200,total_tokens:300,finance_search_calls:0,web_search_calls:1,tool_cost_usd:.02,model_cost_usd:0,total_cost_usd:.03},
      market_context:{},portfolio_diagnosis:{overweight:[],missing:[],strength:[],vulnerability:[]},capital_flows:{strong:[],early:[]},groups:[],raw_candidates:[],filtered_candidates:[],counts:{raw:0,accepted:0,watch_only:0,rejected:0},portfolio_actions:[],limitations:[],
    }
    const html=renderToStaticMarkup(<DiscoveryRunMetadata result={result}/>)
    expect(html).toContain('Search API 请求')
    expect(html).toContain('本机端点输入 / 输出 token')
    expect(html).toContain('>0</dd>')
    expect(html).toContain('$0.0300')
    expect(discoveryStatusText(result.status)).toBe('已完成')
  })

  it('为 Exa 引擎显示 Financial Datasets 调用语义', () => {
    const result={
      id:2,status:'completed',stage:'completed',trigger:'manual',requested_at:'2026-08-07T00:00:00Z',started_at:'2026-08-07T00:00:01Z',completed_at:'2026-08-07T00:01:00Z',analysis_date:'2026-08-07',next_scheduled_at:null,
      model_requested:'exa-agent',model_used:'exa-agent',prompt_version:'stock-discovery-prompt-v0.6',schema_version:'stock-discovery-schema-v0.6',filter_version:'stock-discovery-filter-v0.4',warnings:[],failure_code:null,failure_reason:null,previous_successful_run_id:null,
      discovery_mode:'exa_finance' as const,
      usage:{input_tokens:0,output_tokens:0,total_tokens:0,finance_search_calls:3,web_search_calls:4,tool_cost_usd:.05,model_cost_usd:.5,total_cost_usd:.55},
      market_context:{},portfolio_diagnosis:{overweight:[],missing:[],strength:[],vulnerability:[]},capital_flows:{strong:[],early:[]},groups:[],raw_candidates:[],filtered_candidates:[],counts:{raw:0,accepted:0,watch_only:0,rejected:0},portfolio_actions:[],limitations:[],
    }
    const html=renderToStaticMarkup(<DiscoveryRunMetadata result={result}/>)
    expect(html).toContain('Exa Agent + Financial Datasets')
    expect(html).toContain('Financial Datasets 调用')
    expect(html).toContain('>3</dd>')
    expect(html).toContain('$0.5500')
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

  it('为 Pi Agent 引擎展示智能研究语义', () => {
    const result={
      id:3,status:'completed',stage:'completed',trigger:'manual',requested_at:'2026-08-20T00:00:00Z',started_at:'2026-08-20T00:00:01Z',completed_at:'2026-08-20T00:12:00Z',analysis_date:'2026-08-20',next_scheduled_at:null,
      model_requested:'gpt-5.6-sol',model_used:'gpt-5.6-sol',prompt_version:'stock-discovery-prompt-v0.7',schema_version:'stock-discovery-schema-v0.7',filter_version:'stock-discovery-filter-v0.4',warnings:[],failure_code:null,failure_reason:null,previous_successful_run_id:null,
      discovery_mode:'pi_agent' as const,funnel_stats:{candidates_discovered:32,candidates_promoted:9},
      usage:{input_tokens:12000,output_tokens:8000,total_tokens:20000,finance_search_calls:1,web_search_calls:6,tool_cost_usd:.14,model_cost_usd:0,total_cost_usd:.14},
      market_context:{},portfolio_diagnosis:{overweight:[],missing:[],strength:[],vulnerability:[]},capital_flows:{strong:[],early:[]},groups:[],raw_candidates:[],filtered_candidates:[],counts:{raw:12,accepted:9,watch_only:2,rejected:1},portfolio_actions:[],limitations:[],
    }
    const html=renderToStaticMarkup(<DiscoveryRunMetadata result={result}/>)
    expect(html).toContain('Pi Agent 智能研究')
    expect(html).toContain('本机端点输入 / 输出 token')
    expect(html).toContain('$0.1400')
  })

  it('Pi 漏斗进度条标记已完成与当前阶段', () => {
    const html=renderToStaticMarkup(<PiFunnelProgress stage="pi_counter_evidence" stats={{candidates_discovered:32,candidates_promoted:9}}/>)
    expect(html).toContain('研究规划')
    expect(html).toContain('反方论据')
    expect(html).toContain('发现候选 32')
    expect(html).toContain('已晋级 9')
    expect(html).toContain('done')
    expect(html).toContain('active')
  })

  it('Pi 漏斗对非 Pi 阶段不渲染', () => {
    expect(renderToStaticMarkup(<PiFunnelProgress stage="searching_market"/>)).toBe('')
  })

  it('完成后漏斗所有阶段都显示完成', () => {
    const html=renderToStaticMarkup(<PiFunnelProgress stage="completed"/>)
    expect(html).toContain('✓')
    expect(html).not.toContain('active')
  })
})
