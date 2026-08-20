import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, patch, post } from './api'
import { Sheet } from './Sheet'

export type DiscoveryUsage = {input_tokens:number;output_tokens:number;total_tokens:number;finance_search_calls:number;web_search_calls:number;tool_cost_usd:number;model_cost_usd:number;total_cost_usd:number}
export type DiscoveryMode = 'search_local'|'agent_finance'|'exa_finance'|'pi_agent'
export type DiscoveryRunMeta = {id:number;status:string;stage:string;trigger:string;discovery_mode?:DiscoveryMode;requested_at:string;started_at:string|null;completed_at:string|null;analysis_date:string|null;next_scheduled_at:string|null;model_requested:string;model_used:string|null;prompt_version:string;schema_version:string;filter_version:string;warnings:string[];failure_code:string|null;failure_reason:string|null;previous_successful_run_id:number|null;usage?:DiscoveryUsage|null;funnel_stats?:Record<string,number>|null}
export type CandidateGroupRef = {id:string;name:string;type:string;reason:string}
export type CandidateMetric = Record<string,number|string>
export type EvidenceItem = {claim:string;source_type:string;url_or_reference:string|null;date:string|null;confidence:number|null}
export type DiscoveryCandidate = {
  id:number;raw_ticker:string;normalized_ticker:string|null;company_name:string;exchange:string|null;country:string|null;raw_rank:number|null;final_rank:number|null;priority:string
  symbol_match_status:string;symbol_match_reason:string|null;filter_status:string;display_status:string;filter_reasons:string[];filter_details:Record<string,unknown>
  verification_status:string;dismissed:boolean;researched:boolean;groups:CandidateGroupRef[];discovery_reason:string|null;portfolio_fit:string|null
  diversification_effect:string|null;overlap_with_existing_holdings:string[];business_quality_summary:string|null;investment_thesis:string[]
  bear_case:string[];evidence:EvidenceItem[];research_depth:string
  capital_flow_context:string|null;valuation_context:string|null;why_now:string|null;quality_level:string;valuation_level:string;momentum_state:string;confidence:number|null
  financial_snapshot:CandidateMetric;source_badges:string[];source_count:number;data_discrepancies:{metric:string;values:{source:string;value:number|string;period:string|null}[]}[]
  major_risks:string[];thesis_breakers:string[];reconsideration_condition?:string|null
}
export type DiscoveryCandidateDetail = DiscoveryCandidate & {raw_analysis:Record<string,unknown>;local_verification:Record<string,unknown>;sources:{title:string;url:string;source_type:string;origin:string}[];facts_to_verify_locally:string[];verified_at:string|null}
export type DiscoveryResult = DiscoveryRunMeta & {
  market_context:Record<string,unknown>
  portfolio_diagnosis:Record<'overweight'|'missing'|'strength'|'vulnerability',{name:string;exposure_type:string|null;level:string;reasoning:string;suggested_action:string}[]>
  capital_flows:{strong:CapitalFlow[];early:CapitalFlow[]}
  groups:{id:string;name:string;type:string;summary:string;candidates:DiscoveryCandidate[]}[]
  raw_candidates:DiscoveryCandidate[];filtered_candidates:DiscoveryCandidate[]
  counts:{raw:number;accepted:number;watch_only:number;rejected:number}
  portfolio_actions:{action:string;priority:string;reason:string}[];limitations:string[]
  agent_events?:{event_type:string;detail:string;created_at:string|null}[]
}
type CapitalFlow = {direction:string;strength?:string;current_attention?:string;evidence?:string;sustainability?:string;catalyst?:string;long_term_case?:string;what_could_trigger_repricing?:string[];risks:string[];related_tickers:string[]}
type LatestDiscovery = {current_run:DiscoveryRunMeta|null;result:DiscoveryResult|null;using_previous_result:boolean;api_key_configured:boolean;discovery_mode:DiscoveryMode;monthly_spend_usd:number;monthly_budget_usd:number}
export type OpportunityItem = {title:string;ticker:string;category:string[];summary:string;why_now:string[];evidence:{type:'financial'|'news'|'market';content:string}[];catalysts:string[];risks:string[];valuation_view:string;confidence:number;action:string[]}
export type OpportunityHistory = {id:number;run_id:number;created_at:string;market_condition:string;model_version:string;search_source:string;opportunities:OpportunityItem[];tickers:string[];categories:string[];max_confidence:number;sources?:{title:string;url:string;origin:string}[]}
export type DiscoverySettings = {discovery_mode:DiscoveryMode;analysis_model:string;agent_model:string;exa_agent_model:string;exa_agent_effort:string;exa_finance_provider:string;search_source:string;max_output_tokens:number;monthly_budget_usd:number;max_run_cost_usd:number;min_market_cap:number;exclude_current_holdings:boolean;exclude_watchlist:boolean;require_positive_fcf:boolean;max_trailing_pe:number;max_forward_pe:number;max_price_to_sales:number;filter_extreme_momentum:boolean;missing_data_policy:'warn'|'watch_only'|'reject';api_key_configured:boolean;exa_api_key_configured:boolean;analysis_api_key_configured:boolean;prompt_version:string;schema_version:string;filter_version:string;pi_agent_ready?:boolean;pi_agent_model?:string;pi_agent_max_turns?:number;pi_agent_max_web_search_calls?:number;pi_agent_deep_effort?:string}

const statusLabel:Record<string,string> = {pending:'等待生成',running:'正在生成',completed:'已完成',completed_with_warnings:'部分完成',failed:'运行失败',blocked_by_budget:'预算已阻止'}
const stageLabel:Record<string,string> = {preparing_portfolio:'正在整理持仓',preparing_local_data:'正在读取本地数据',budget_check:'正在检查预算',searching_market:'Perplexity Search 正在检索',analyzing_with_local_ai:'GPT-5.6-sol 正在生成机会',running_finance_agent:'Perplexity Finance Search + GPT-5.4 正在生成机会',running_exa_finance_agent:'Exa Agent + Financial Datasets 正在深度研究',pi_planning:'Pi Agent 正在规划研究',pi_discovering:'Pi Agent 正在探索主题与候选',pi_internal_verification:'Pi Agent 正在做内部数据筛选',pi_external_research:'Pi Agent 正在补充外部研究',pi_counter_evidence:'Pi Agent 正在寻找反方论据',pi_portfolio_fit:'Pi Agent 正在评估组合适配',pi_synthesizing:'Pi Agent 正在生成最终结果',normalizing_candidates:'正在生成候选',local_verification:'正在进行本地验证',applying_filters:'正在应用过滤规则',retrying:'请求受限，准备重试',completed:'已完成',failed:'运行失败'}
const engineLabel:Record<string,string>={search_local:'GPT-5.6-sol + Perplexity Search',agent_finance:'Perplexity Finance Search + GPT-5.4',exa_finance:'Exa Agent + Financial Datasets',pi_agent:'Pi Agent 智能研究'}
const filterLabel:Record<string,string> = {accepted:'已保留',accepted_with_warning:'保留但有警告',watch_only:'仅观察',rejected:'已过滤',insufficient_data:'数据不足',duplicate:'重复候选',already_held:'已持有',already_watched:'已在自选',unsupported_symbol:'无法识别'}
const levelLabel:Record<string,string> = {high:'高',medium:'中',low:'低',uncertain:'不确定',cheap:'便宜',reasonable:'合理',elevated:'偏高',extreme:'极高',cold:'冷',neutral:'中性',improving:'改善',strong:'强',euphoric:'过热',verified:'已验证',partial:'部分验证',pending:'待验证',failed:'待验证',positive:'增加分散',negative:'重复敞口'}
const metricLabels:Record<string,string> = {market_cap:'市值',pe_trailing:'PE',pe_forward:'预期 PE',price_to_sales:'市销率',revenue_growth:'营收增长',earnings_growth:'盈利增长',free_cash_flow:'自由现金流',free_cash_flow_margin:'FCF 利润率',return_on_invested_capital:'ROIC',operating_margin:'经营利润率',gross_margin:'毛利率',price:'价格',average_volume:'平均成交量'}

// 数据出处统一映射：Pi 来源按证据类型细分（SEC 文件/公司 IR/…），不再统一显示 "pi agent"。
// 旧的 pi_agent / pi_agent_evidence 行（历史数据）也在这里映射，保证旧 run 可读。
const sourceOriginLabels:Record<string,string> = {
  pi_sec_filing:'SEC 文件', pi_company_ir:'公司 IR', pi_earnings_call:'财报电话会',
  pi_reputable_news:'权威新闻', pi_web_source:'网络来源', pi_internal_data:'内部数据',
  pi_model_inference:'模型推断', pi_evidence:'Pi 证据', pi_agent_evidence:'Pi 证据链', pi_agent:'Pi 报告值',
  perplexity_search:'Perplexity Search', perplexity_finance:'Perplexity Finance', perplexity_web:'Perplexity Web',
  exa_financial_datasets:'Exa Financial Datasets', exa_grounding:'Exa Grounding', exa_finance:'Exa Finance', exa_web:'Exa Web',
  yfinance:'Yahoo', local_calculation:'本地计算',
}
export const discoverySourceLabel=(origin:string)=>sourceOriginLabels[origin]||origin
const searchSourceLabels:Record<string,string> = {
  pi_agent:'Pi Agent 智能研究', perplexity_search:'GPT-5.6-sol + Perplexity Search',
  perplexity_finance_agent:'Perplexity Finance Agent', exa_agent_financial_datasets:'Exa Agent + Financial Datasets',
}
export const discoverySearchSourceLabel=(source:string)=>searchSourceLabels[source]||engineLabel[source]||source
const percentMetrics = new Set(['revenue_growth','earnings_growth','free_cash_flow_margin','return_on_invested_capital','operating_margin','gross_margin'])

export function visibleCandidateMetrics(snapshot:CandidateMetric, limit=6) {
  const order=['market_cap','pe_trailing','pe_forward','revenue_growth','free_cash_flow_margin','free_cash_flow','return_on_invested_capital','operating_margin','price_to_sales']
  return order.filter(key=>snapshot[key]!=null).slice(0,limit).map(key=>({key,value:snapshot[key]}))
}
export const discoveryStatusText=(status:string)=>statusLabel[status]||status
export const shouldPollDiscovery=(data:LatestDiscovery|undefined)=>Boolean(data?.current_run&&['pending','running'].includes(data.current_run.status))
export function chooseCandidateGroup(groups:DiscoveryResult['groups'], activeId:string) {
  return groups.find(group=>group.id===activeId)||groups[0]
}
const formatMetric=(key:string,value:number|string)=>{
  if(typeof value!=='number')return value
  if(key==='market_cap'||key==='free_cash_flow') return new Intl.NumberFormat('zh-CN',{notation:'compact',maximumFractionDigits:1}).format(value)
  if(percentMetrics.has(key)) return `${(Math.abs(value)<=2?value*100:value).toFixed(1)}%`
  return value.toLocaleString('zh-CN',{maximumFractionDigits:2})
}
const formatTime=(value:string|null|undefined)=>value?new Date(value).toLocaleString('zh-CN'):'—'
const money=(value:number|null|undefined)=>value==null?'—':`$${value.toFixed(4)}`

export function CandidateStatusBadge({status}:{status:string}) {
  return <span className={`discovery-status status-${status}`}>{filterLabel[status]||status}</span>
}

const funnelSteps:{stage:string;label:string}[] = [
  {stage:'pi_planning',label:'研究规划'},
  {stage:'pi_discovering',label:'主题与候选发现'},
  {stage:'pi_internal_verification',label:'内部数据筛选'},
  {stage:'pi_external_research',label:'外部研究'},
  {stage:'pi_counter_evidence',label:'反方论据'},
  {stage:'pi_portfolio_fit',label:'组合适配'},
  {stage:'pi_synthesizing',label:'最终生成'},
]

export function PiFunnelProgress({stage,stats}:{stage:string;stats?:Record<string,number>|null}) {
  const activeIndex=funnelSteps.findIndex(step=>step.stage===stage)
  const done=activeIndex<0&&stage==='completed'
  if(activeIndex<0&&!done)return null
  return <div className="pi-funnel-progress" aria-label="研究漏斗进度">
    {funnelSteps.map((step,index)=>{
      const state=done||index<activeIndex?'done':index===activeIndex?'active':'pending'
      return <div key={step.stage} className={`pi-funnel-step ${state}`}><em>{done||index<activeIndex?'✓':index+1}</em><span>{step.label}</span></div>
    })}
    {!!stats&&Object.keys(stats).length>0&&<small className="pi-funnel-stats">{Object.entries(stats).map(([key,value])=>`${funnelStatLabel(key)||key} ${value}`).join(' · ')}</small>}
  </div>
}

const funnelStatLabel:(key:string)=>string|undefined=(key)=>({
  candidates_discovered:'发现候选',
  candidates_screened:'已筛选',
  candidates_rejected:'已排除',
  candidates_promoted:'已晋级',
  web_searches:'外部检索',
} as Record<string,string>)[key]

const evidenceSourceLabel=(sourceType:string)=>{
  const labels:Record<string,string>={sec_filing:'SEC 文件',company_ir:'公司 IR',earnings_call:'财报电话会',reputable_news:'权威新闻',web_source:'网络来源',internal_data:'内部数据',model_inference:'模型推断'}
  return labels[sourceType]||sourceType
}

function CandidateMetricRow({snapshot}:{snapshot:CandidateMetric}) {
  const metrics=visibleCandidateMetrics(snapshot)
  if(!metrics.length)return <p className="candidate-data-gap">关键指标待本地验证</p>
  return <dl className="candidate-metrics">{metrics.map(({key,value})=><div key={key}><dt>{metricLabels[key]||key}</dt><dd>{formatMetric(key,value)}</dd></div>)}</dl>
}

function CandidateCard({candidate,onDetail,onAction}:{candidate:DiscoveryCandidate;onDetail:(id:number)=>void;onAction:(kind:'watchlist'|'researched'|'dismiss',id:number)=>void}) {
  const ticker=candidate.normalized_ticker||candidate.raw_ticker
  return <article className="candidate-card" id={`candidate-${ticker}`}>
    <div className="candidate-card-top"><div><b>{ticker}</b><span>{candidate.company_name}</span></div><div><span className={`candidate-priority priority-${candidate.priority}`}>{levelLabel[candidate.priority]||candidate.priority}优先级</span><CandidateStatusBadge status={candidate.display_status}/></div></div>
    <p className="candidate-reason"><b>推荐原因</b>{candidate.discovery_reason||'原始说明待补充'}</p>
    <p className="candidate-fit"><b>组合作用</b>{candidate.portfolio_fit||'待结合本地持仓验证'}</p>
    <CandidateMetricRow snapshot={candidate.financial_snapshot}/>
    <div className="candidate-tags"><span>质量：{levelLabel[candidate.quality_level]||'不确定'}</span><span>估值：{levelLabel[candidate.valuation_level]||'不确定'}</span><span>动量：{levelLabel[candidate.momentum_state]||'不确定'}</span><span>验证：{levelLabel[candidate.verification_status]||'待验证'}</span></div>
    {!!candidate.filter_reasons.length&&<p className="candidate-warning">{candidate.filter_reasons.join('；')}</p>}
    <div className="candidate-sources">{candidate.source_badges.slice(0,4).map(source=><span key={source}>{discoverySourceLabel(source)}</span>)}</div>
    <div className="candidate-actions"><button onClick={()=>onDetail(candidate.id)}>查看详情</button><details><summary aria-label={`${ticker} 更多操作`}>•••</summary><div><button onClick={()=>onAction('watchlist',candidate.id)}>加入自选</button><button onClick={()=>onAction('researched',candidate.id)}>标记已研究</button><button onClick={()=>onAction('dismiss',candidate.id)}>忽略</button></div></details></div>
  </article>
}

function PortfolioExposureCard({title,items}:{title:string;items:DiscoveryResult['portfolio_diagnosis']['overweight']}) {
  return <article className="exposure-card"><h3>{title}</h3>{items.slice(0,4).map((item,index)=><div key={`${item.name}-${index}`}><span className={`exposure-level level-${item.level}`}>{levelLabel[item.level]||'中'}</span><div><b>{item.name}</b><p>{item.reasoning}</p>{item.suggested_action&&<small>研究方向：{item.suggested_action}</small>}</div></div>)}{!items.length&&<p className="candidate-data-gap">本次没有形成明确结论</p>}</article>
}

function CapitalFlowColumn({title,items,onTicker}:{title:string;items:CapitalFlow[];onTicker:(ticker:string)=>void}) {
  return <section className="flow-column"><h3>{title}</h3>{items.map((item,index)=><article key={`${item.direction}-${index}`}><div><b>{item.direction}</b><span>{levelLabel[item.strength||item.current_attention||'uncertain']||'不确定'}</span></div><p>{item.evidence||item.long_term_case}</p>{item.sustainability&&<small>持续性：{levelLabel[item.sustainability]||item.sustainability}</small>}{item.catalyst&&<small>可能催化：{item.catalyst}</small>}{!!item.what_could_trigger_repricing?.length&&<small>重估条件：{item.what_could_trigger_repricing.join('；')}</small>}{!!item.risks?.length&&<small>主要风险：{item.risks.join('；')}</small>}<div className="flow-tickers">{item.related_tickers?.map(ticker=><button key={ticker} onClick={()=>onTicker(ticker)}>{ticker}</button>)}</div></article>)}</section>
}

export function RawCandidatePanel({items,onDetail}:{items:DiscoveryCandidate[];onDetail:(id:number)=>void}) {
  return <details className="raw-candidate-panel"><summary><span><b>原始候选</b><small>机会发现引擎返回、本地过滤前的股票</small></span><em>{items.length} 只</em></summary><div>{items.map(item=><button key={item.id} onClick={()=>onDetail(item.id)}><b>{item.raw_ticker}</b><span>{item.groups[0]?.name||'原始候选'}</span><small>{levelLabel[item.priority]||'中'}优先级</small><CandidateStatusBadge status={item.display_status}/></button>)}</div></details>
}

function FilteredCandidateList({items,onDetail}:{items:DiscoveryCandidate[];onDetail:(id:number)=>void}) {
  return <details className="filtered-candidates"><summary><span><b>已过滤与过热候选</b><small>保留过滤原因与重新评估条件</small></span><em>{items.length} 只</em></summary><div>{items.map(item=><button key={item.id} onClick={()=>onDetail(item.id)}><span><b>{item.normalized_ticker||item.raw_ticker}</b><small>{item.company_name}</small></span><span>{item.groups[0]?.name||'原始候选'}</span><span>{item.filter_reasons.join('；')||'已从主要候选隐藏'}</span><CandidateStatusBadge status={item.display_status}/></button>)}</div></details>
}

export function DiscoveryRunMetadata({result}:{result:DiscoveryResult}) {
  const usage=result.usage
  const agent=result.discovery_mode==='agent_finance'
  const exa=result.discovery_mode==='exa_finance'
  return <details className="discovery-run-metadata"><summary><span><b>本次运行</b><small>引擎、调用与成本明细</small></span></summary><dl><div><dt>机会发现引擎</dt><dd>{engineLabel[result.discovery_mode||'search_local']}</dd></div><div><dt>开始时间</dt><dd>{formatTime(result.started_at)}</dd></div><div><dt>完成时间</dt><dd>{formatTime(result.completed_at)}</dd></div><div><dt>{exa?'Financial Datasets 调用':'Finance Search 调用'}</dt><dd>{usage?.finance_search_calls??'—'}</dd></div><div><dt>{agent||exa?'Agent Web Search 调用':'Search API 请求'}</dt><dd>{usage?.web_search_calls??'—'}</dd></div><div><dt>{exa?'Exa Agent token（如上游提供）':agent?'Perplexity 模型 token':'本机端点输入 / 输出 token'}</dt><dd>{usage?(agent||exa?usage.total_tokens:`${usage.input_tokens} / ${usage.output_tokens}`):'—'}</dd></div><div><dt>工具成本</dt><dd>{money(usage?.tool_cost_usd)}</dd></div><div><dt>模型 / Agent 成本</dt><dd>{agent||exa?money(usage?.model_cost_usd):'使用项目已有端点'}</dd></div><div><dt>本次可计量成本</dt><dd>{money(usage?.total_cost_usd)}</dd></div><div><dt>Prompt 版本</dt><dd>{result.prompt_version}</dd></div><div><dt>Schema 版本</dt><dd>{result.schema_version}</dd></div></dl></details>
}

export function DataDiscrepancies({items}:{items:DiscoveryCandidate['data_discrepancies']}) {
  if(!items.length)return null
  return <div className="data-discrepancy"><b>发现数据差异</b>{items.map(row=><p key={row.metric}>{metricLabels[row.metric]||row.metric}：{row.values.map(value=>`${value.source} ${value.value}`).join('；')}</p>)}<small>不同数据源的统计口径或更新时间可能不同。</small></div>
}

function CandidateDetailDrawer({id,onClose,onChanged}:{id:number|null;onClose:()=>void;onChanged:()=>void}) {
  const detail=useQuery({queryKey:['discovery-candidate',id],queryFn:()=>api<DiscoveryCandidateDetail>(`/discovery/candidates/${id}`),enabled:id!=null})
  const item=detail.data
  const analysisLabel=item?.source_badges.some(source=>source.startsWith('pi_'))?'Pi Agent 智能研究':item?.source_badges.some(source=>source.startsWith('exa_'))?'Exa Agent + Financial Datasets':item?.source_badges.includes('perplexity_finance')?'Perplexity Finance Search + GPT-5.4':'GPT-5.6-sol + Perplexity Search'
  return <Sheet open={id!=null} onClose={onClose} title={item?.normalized_ticker||item?.raw_ticker||'候选详情'}>{detail.isLoading&&<div className="empty">正在读取已保存的候选资料…</div>}{item&&<article className="candidate-detail">
    <div className="candidate-detail-heading"><div><p className="eyebrow">研究候选</p><h2>{item.normalized_ticker||item.raw_ticker} <small>{item.company_name}</small></h2></div><CandidateStatusBadge status={item.display_status}/></div>
    <section><h3>{analysisLabel}</h3><p>{item.discovery_reason}</p>{!!item.investment_thesis.length&&<ul>{item.investment_thesis.map(text=><li key={text}>{text}</li>)}</ul>}<CandidateMetricRow snapshot={(item.raw_analysis.financial_snapshot||{}) as CandidateMetric}/></section>
    <section><h3>本地数据验证</h3><CandidateMetricRow snapshot={item.financial_snapshot}/><p className="detail-note">验证状态：{levelLabel[item.verification_status]||'待验证'}　·　时间：{formatTime(item.verified_at)}</p><DataDiscrepancies items={item.data_discrepancies}/></section>
    <section><h3>组合适配</h3><p>{item.portfolio_fit||'数据不足'}</p><p>分散作用：{levelLabel[item.diversification_effect||'']||'不确定'}</p>{!!item.overlap_with_existing_holdings.length&&<p>重叠持仓：{item.overlap_with_existing_holdings.join('、')}</p>}</section>
    {!!item.bear_case.length&&<section className="candidate-bear-case"><h3>反方论据（Bear Case）</h3><ul>{item.bear_case.map(text=><li key={text}>{text}</li>)}</ul><small>主动寻找的不买入理由，用于对冲确认偏误。</small></section>}
    {!!item.evidence.length&&<section><h3>证据链</h3><ul className="candidate-evidence-list">{item.evidence.map((row,index)=><li key={`${row.claim}-${index}`}><span className={`evidence-source-type ${row.source_type}`}>{evidenceSourceLabel(row.source_type)}</span><div><p>{row.claim}</p><small>{row.date?`日期 ${row.date}　`:''}{row.confidence!=null?`置信度 ${(row.confidence*100).toFixed(0)}%　`:''}{row.url_or_reference&&<a href={row.url_or_reference} target="_blank" rel="noreferrer">来源链接</a>}</small></div></li>)}</ul></section>}
    <section><h3>风险与失效条件</h3>{!!item.major_risks.length&&<><b>主要风险</b><ul>{item.major_risks.map(text=><li key={text}>{text}</li>)}</ul></>}{!!item.thesis_breakers.length&&<><b>失效条件</b><ul>{item.thesis_breakers.map(text=><li key={text}>{text}</li>)}</ul></>}{!!item.filter_reasons.length&&<p className="candidate-warning">本地过滤：{item.filter_reasons.join('；')}</p>}</section>
    <section><h3>来源与数据差异</h3>{item.sources.map((source,index)=><a key={`${source.url}-${index}`} href={source.url} target="_blank" rel="noreferrer">{source.title||source.url} <small>{discoverySourceLabel(source.origin)}</small></a>)}{!item.sources.length&&<p>来源链接数据不足</p>}</section>
    <div className="candidate-detail-actions"><button onClick={()=>post(`/discovery/candidates/${item.id}/watchlist`,{}).then(onChanged)}>加入自选</button><button onClick={()=>post(`/discovery/candidates/${item.id}/researched`,{}).then(onChanged)}>标记已研究</button></div>
  </article>}</Sheet>
}

function OpportunityReport({history}:{history:OpportunityHistory}) {
  return <section className="opportunity-history-detail" aria-label="机会详情">
    <div className="section-title"><div><p>机会详情</p><h2>{formatTime(history.created_at)}</h2></div><small>{history.model_version} · {discoverySearchSourceLabel(history.search_source)}</small></div>
    <p className="history-market-condition"><b>当时市场环境</b>{history.market_condition}</p>
    <div className="history-report-grid">{history.opportunities.map((item,index)=><article key={`${item.ticker}-${index}`}>
      <div className="history-company-heading"><div><span>{item.ticker}</span><h3>{item.title}</h3></div><strong>{item.confidence}</strong></div>
      <div className="history-category-row">{item.category.map(category=><span key={category}>{category}</span>)}{item.action.map(action=><em key={action}>{action}</em>)}</div>
      <p className="history-summary">{item.summary}</p>
      <section><h4>投资逻辑 / Why now</h4><ul>{item.why_now.map(text=><li key={text}>{text}</li>)}</ul></section>
      <section><h4>依据</h4><ul>{item.evidence.map((row,evidenceIndex)=><li key={`${row.type}-${evidenceIndex}`}><span className={`evidence-type ${row.type}`}>{row.type}</span>{row.content}</li>)}</ul></section>
      <section><h4>催化剂</h4><ul>{item.catalysts.map(text=><li key={text}>{text}</li>)}</ul></section>
      <section><h4>风险</h4><ul>{item.risks.map(text=><li key={text}>{text}</li>)}</ul></section>
      <p><b>估值判断</b>{item.valuation_view}</p>
    </article>)}</div>
    {!!history.sources?.length&&<details className="history-sources"><summary>数据来源（{history.sources.length}）</summary><div>{history.sources.map((source,index)=><a key={`${source.url}-${index}`} href={source.url} target="_blank" rel="noreferrer">{source.title||source.url}<small>{discoverySourceLabel(source.origin)}</small></a>)}</div></details>}
  </section>
}

function OpportunityHistorySection({refreshKey}:{refreshKey:string}) {
  const [selected,setSelected]=useState<number|null>(null)
  const history=useQuery({queryKey:['discovery-history',refreshKey],queryFn:()=>api<OpportunityHistory[]>('/discovery/history')})
  useEffect(()=>{if(history.data?.length)setSelected(history.data[0].id)},[refreshKey,history.data?.[0]?.id])
  const detail=useQuery({queryKey:['discovery-history-detail',selected],queryFn:()=>api<OpportunityHistory>(`/discovery/history/${selected}`),enabled:selected!=null})
  return <>
    <section className="discovery-section opportunity-history" aria-label="历史机会">
      <div className="section-title"><div><p>历史机会</p><h2>Opportunity History</h2></div><small>每次成功手动发现都会永久保存</small></div>
      {history.isLoading&&<p className="candidate-data-gap">正在读取历史记录…</p>}
      {!history.isLoading&&!history.data?.length&&<p className="candidate-data-gap">还没有历史机会。</p>}
      <div className="opportunity-history-list">{history.data?.map(row=><button key={row.id} className={selected===row.id?'active':''} onClick={()=>setSelected(row.id)}>
        <time>{new Date(row.created_at).toLocaleDateString('zh-CN')}</time>
        <span><b>{row.tickers.join('、')||'数据不足'}</b><small>{row.categories.join(' · ')||row.market_condition}</small></span>
        <strong>{row.max_confidence}</strong>
      </button>)}</div>
    </section>
    {detail.data&&<OpportunityReport history={detail.data}/>}
  </>
}

export function OpportunityDiscovery() {
  const client=useQueryClient()
  const [selectedId,setSelectedId]=useState<number|null>(null)
  const latest=useQuery({queryKey:['discovery-latest'],queryFn:()=>api<LatestDiscovery>('/discovery/latest'),staleTime:30_000,
    refetchInterval:query=>shouldPollDiscovery(query.state.data as LatestDiscovery|undefined)?8000:false})
  const settings=useQuery({queryKey:['discovery-settings'],queryFn:()=>api<DiscoverySettings>('/discovery/settings'),staleTime:30_000})
  const result=latest.data?.result
  const [activeGroup,setActiveGroup]=useState('')
  useEffect(()=>{if(result?.groups.length&&!result.groups.some(group=>group.id===activeGroup))setActiveGroup(result.groups[0].id)},[result?.id,activeGroup,result?.groups])
  const refresh=useMutation({mutationFn:()=>post<{run_id:number}>('/discovery/refresh',{}),onSuccess:()=>client.invalidateQueries({queryKey:['discovery-latest']})})
  const saveEngine=useMutation({
    mutationFn:(discovery_mode:DiscoverySettings['discovery_mode'])=>patch<DiscoverySettings>('/discovery/settings',{discovery_mode}),
    onSuccess:data=>{
      client.setQueryData(['discovery-settings'],data)
      client.invalidateQueries({queryKey:['discovery-latest']})
    },
  })
  const action=useMutation({mutationFn:({kind,id}:{kind:'watchlist'|'researched'|'dismiss';id:number})=>post(`/discovery/candidates/${id}/${kind}`,{}),onSuccess:()=>{client.invalidateQueries({queryKey:['discovery-latest']});client.invalidateQueries({queryKey:['watchlist']})}})
  const group=result?chooseCandidateGroup(result.groups,activeGroup):undefined
  const selectedEngine=settings.data?.discovery_mode||latest.data?.discovery_mode||'search_local'
  const onRefresh=()=>{if(result&&!window.confirm(`将使用“${engineLabel[selectedEngine]}”运行一次并产生 API 费用，是否继续？`))return;refresh.mutate()}
  const goTicker=(ticker:string)=>{const target=result?.groups.find(item=>item.candidates.some(candidate=>(candidate.normalized_ticker||candidate.raw_ticker)===ticker));if(target)setActiveGroup(target.id);requestAnimationFrame(()=>document.getElementById(`candidate-${ticker}`)?.scrollIntoView({behavior:'smooth',block:'center'}))}
  const running=latest.data?.current_run&&['pending','running'].includes(latest.data.current_run.status)
  if(latest.isLoading)return <div className="discovery-empty"><div className="discovery-skeleton"/><h2>正在读取最近一次机会发现结果…</h2></div>
  if(latest.error)return <div className="error">机会发现数据暂时无法读取，请稍后重试。</div>
  return <div className="opportunity-discovery">
    {running&&<div className="discovery-banner active"><span><b>正在生成新的机会发现结果</b>{result?'当前仍显示上一批内容。':'完成前可离开此页面。'}</span><em>{stageLabel[latest.data?.current_run?.stage||'']||'正在处理'}</em></div>}
    {running&&latest.data?.current_run?.discovery_mode==='pi_agent'&&<PiFunnelProgress stage={latest.data.current_run.stage} stats={latest.data.current_run.funnel_stats||undefined}/>}
    {latest.data?.using_previous_result&&!running&&<div className="discovery-banner warning"><span><b>正在使用上一批成功结果</b>{latest.data.current_run?.failure_reason||'新批次没有替换当前内容。'}</span></div>}
    {!latest.data?.api_key_configured&&<div className="discovery-banner warning"><span><b>当前引擎所需 API Key 未完整配置</b>请到设置确认 Perplexity、本机端点或 Exa 配置。</span></div>}
    {refresh.error&&<div className="discovery-banner warning"><span><b>未能开始本次发现</b>{refresh.error.message}</span></div>}
    <section className="discovery-engine-selector" aria-label="选择机会发现引擎">
      <div><p className="eyebrow">本次运行</p><h2>选择机会发现引擎</h2><small>只会运行你选中的一项；切换引擎本身不会发起机会发现请求。</small></div>
      <div className="discovery-mode-picker" role="radiogroup" aria-label="机会发现引擎">
        <button type="button" role="radio" aria-checked={selectedEngine==='agent_finance'} className={selectedEngine==='agent_finance'?'active':''} disabled={saveEngine.isPending||Boolean(running)} onClick={()=>saveEngine.mutate('agent_finance')}><b>高成本引擎</b><span>Perplexity Finance Search + GPT-5.4</span><small>Perplexity Agent 完成金融检索与判断</small></button>
        <button type="button" role="radio" aria-checked={selectedEngine==='exa_finance'} className={selectedEngine==='exa_finance'?'active':''} disabled={saveEngine.isPending||Boolean(running)} onClick={()=>saveEngine.mutate('exa_finance')}><b>Exa 深度研究</b><span>Exa Agent + Financial Datasets</span><small>覆盖行情、财务、SEC、持仓与股票筛选</small></button>
        <button type="button" role="radio" aria-checked={selectedEngine==='pi_agent'} className={selectedEngine==='pi_agent'?'active':''} disabled={saveEngine.isPending||Boolean(running)} onClick={()=>saveEngine.mutate('pi_agent')}><b>Pi Agent 智能研究</b><span>{settings.data?.pi_agent_model||'GPT-5.6-sol'} · 内部数据优先 + Exa 检索</span><small>自主研究漏斗：规划→筛选→外部研究→反证→组合适配</small></button>
      </div>
      <p className={`discovery-engine-save-state ${saveEngine.isError?'error':''}`}>{saveEngine.isPending?'正在保存选择…':saveEngine.isError?'引擎选择保存失败':`当前选择：${engineLabel[selectedEngine]}`}</p>
    </section>
    {!result?<section className="discovery-empty"><span className="discovery-empty-icon" aria-hidden="true">⌁</span><h2>还没有机会发现结果</h2><p>系统会结合持仓结构、市场资金方向与公开金融数据生成一批研究候选。</p><button onClick={()=>onRefresh()} disabled={refresh.isPending||!latest.data?.api_key_configured}>{refresh.isPending?'正在提交…':'开始首次发现'}</button>{refresh.error&&<small>{refresh.error.message}</small>}</section>:<>
      <section className="opportunity-header"><div><p className="eyebrow">当前机会</p><h2>机会发现</h2><p>上方选择器决定下一次发现使用哪一个引擎。</p><small>仅用于发现研究对象，不构成买入或卖出建议。</small></div><button onClick={onRefresh} disabled={refresh.isPending||running||saveEngine.isPending||!latest.data?.api_key_configured}>{refresh.isPending||running?'正在发现…':'发现机会'}</button><dl><div><dt>分析时间</dt><dd>{formatTime(result.analysis_date)}</dd></div><div><dt>运行方式</dt><dd>仅手动触发</dd></div><div><dt>本批结果引擎</dt><dd>{engineLabel[result.discovery_mode||'search_local']}</dd></div><div><dt>原始 / 保留</dt><dd>{result.counts.raw} / {result.counts.accepted}</dd></div><div><dt>可计量成本</dt><dd>{money(result.usage?.total_cost_usd)}</dd></div><div><dt>当前状态</dt><dd>{statusLabel[result.status]||result.status}</dd></div></dl></section>
      <section className="discovery-section"><div className="section-title"><div><p>组合诊断</p><h2>组合暴露诊断</h2></div></div><div className="exposure-grid"><PortfolioExposureCard title="持仓偏重" items={result.portfolio_diagnosis.overweight}/><PortfolioExposureCard title="持仓缺口" items={result.portfolio_diagnosis.missing}/><PortfolioExposureCard title="组合优势" items={result.portfolio_diagnosis.strength}/><PortfolioExposureCard title="主要脆弱点" items={result.portfolio_diagnosis.vulnerability}/></div></section>
      <section className="discovery-section"><div className="section-title"><div><p>市场观察</p><h2>市场资金方向</h2></div></div><div className="capital-flow-grid"><CapitalFlowColumn title="资金正在加速的方向" items={result.capital_flows.strong} onTicker={goTicker}/><CapitalFlowColumn title="资金尚弱但可提前研究" items={result.capital_flows.early} onTicker={goTicker}/></div></section>
      <section className="discovery-section candidate-groups"><div className="section-title"><div><p>本地验证后</p><h2>研究候选</h2></div><small>{result.counts.accepted} 只保留 · {result.counts.watch_only} 只观察</small></div><div className="candidate-group-tabs" role="tablist">{result.groups.map(item=><button role="tab" aria-selected={item.id===group?.id} className={item.id===group?.id?'active':''} key={item.id} onClick={()=>setActiveGroup(item.id)}>{item.name}<span>{item.candidates.length}</span></button>)}</div>{group&&<><p className="candidate-group-summary">{group.summary}</p><div className="candidate-grid">{group.candidates.map(candidate=><CandidateCard key={candidate.id} candidate={candidate} onDetail={setSelectedId} onAction={(kind,id)=>action.mutate({kind,id})}/>)}{!group.candidates.length&&<div className="empty">该分组没有通过本地过滤的候选。</div>}</div></>}</section>
      <RawCandidatePanel items={result.raw_candidates} onDetail={setSelectedId}/>
      <FilteredCandidateList items={result.filtered_candidates} onDetail={setSelectedId}/>
      <DiscoveryRunMetadata result={result}/>
    </>}
    <OpportunityHistorySection refreshKey={`${latest.data?.current_run?.id||'none'}:${latest.data?.current_run?.status||'idle'}`}/>
    <CandidateDetailDrawer id={selectedId} onClose={()=>setSelectedId(null)} onChanged={()=>{client.invalidateQueries({queryKey:['discovery-latest']});client.invalidateQueries({queryKey:['discovery-candidate',selectedId]});client.invalidateQueries({queryKey:['watchlist']})}}/>
  </div>
}

export function DiscoverySettingsPanel() {
  const client=useQueryClient()
  const query=useQuery({queryKey:['discovery-settings'],queryFn:()=>api<DiscoverySettings>('/discovery/settings')})
  const [form,setForm]=useState<DiscoverySettings|null>(null)
  useEffect(()=>{if(query.data)setForm(query.data)},[query.data])
  const save=useMutation({mutationFn:()=>patch<DiscoverySettings>('/discovery/settings',form),onSuccess:data=>{client.setQueryData(['discovery-settings'],data);setForm(data)}})
  if(!form)return <section className="settings-card"><h2>机会发现</h2><p>正在读取设置…</p></section>
  const set=<K extends keyof DiscoverySettings>(key:K,value:DiscoverySettings[K])=>setForm({...form,[key]:value})
  const keysReady=form.discovery_mode==='exa_finance'?form.exa_api_key_configured:form.discovery_mode==='pi_agent'?(form.pi_agent_ready!==false):(form.api_key_configured&&(form.discovery_mode==='agent_finance'||form.analysis_api_key_configured))
  return <section className="settings-card discovery-settings"><h2>机会发现</h2><p>仅在页面点击“发现机会”时运行，不会定时扫描。下面三项是完成同一个机会发现任务的独立引擎，只会运行你选中的一项。</p><div className={`settings-key-state ${keysReady?'ready':''}`}>{keysReady?'当前引擎所需端点已配置':'当前引擎所需 API Key 未完整配置'}</div>
  <div className="discovery-mode-picker" role="radiogroup" aria-label="机会发现引擎">
    <button type="button" role="radio" aria-checked={form.discovery_mode==='agent_finance'} className={form.discovery_mode==='agent_finance'?'active':''} onClick={()=>set('discovery_mode','agent_finance')}><b>深度研究引擎</b><span>Perplexity Finance Search + {form.agent_model.replace('openai/','')}</span><small>由 Perplexity Agent 在同一次任务中完成金融检索与判断</small></button>
    <button type="button" role="radio" aria-checked={form.discovery_mode==='exa_finance'} className={form.discovery_mode==='exa_finance'?'active':''} onClick={()=>set('discovery_mode','exa_finance')}><b>Exa 深度研究</b><span>{form.exa_agent_model} · {form.exa_agent_effort}</span><small>Exa Agent + {form.exa_finance_provider}，包含金融数据与 Web 深度研究</small></button>
    <button type="button" role="radio" aria-checked={form.discovery_mode==='pi_agent'} className={form.discovery_mode==='pi_agent'?'active':''} onClick={()=>set('discovery_mode','pi_agent')}><b>Pi Agent 智能研究</b><span>{form.pi_agent_model||form.analysis_model} · {form.pi_agent_deep_effort||'medium'} 深度</span><small>研究代理优先使用站内数据，外部检索预算 {form.pi_agent_max_web_search_calls||15} 次 + 深度研究 1 次</small></button>
  </div><div className="settings-grid">
    <label>单次最大输出长度<input type="number" min="2048" max="32000" value={form.max_output_tokens} onChange={e=>set('max_output_tokens',Number(e.target.value))}/></label>
    <label>每月预算上限（美元）<input type="number" min="0" step="0.1" value={form.monthly_budget_usd} onChange={e=>set('monthly_budget_usd',Number(e.target.value))}/></label>
    <label>单次成本预警线（美元）<input type="number" min="0.01" step="0.05" value={form.max_run_cost_usd} onChange={e=>set('max_run_cost_usd',Number(e.target.value))}/></label>
    <label>最低市值<input type="number" min="0" value={form.min_market_cap} onChange={e=>set('min_market_cap',Number(e.target.value))}/></label>
    <label className="settings-toggle">排除当前持仓<input type="checkbox" checked={form.exclude_current_holdings} onChange={e=>set('exclude_current_holdings',e.target.checked)}/></label>
    <label className="settings-toggle">排除已有自选（默认开启，自选股只进"仅观察"）<input type="checkbox" checked={form.exclude_watchlist} onChange={e=>set('exclude_watchlist',e.target.checked)}/></label>
    <label className="settings-toggle">要求正自由现金流<input type="checkbox" checked={form.require_positive_fcf} onChange={e=>set('require_positive_fcf',e.target.checked)}/></label>
    <label>最大 PE<input type="number" value={form.max_trailing_pe} onChange={e=>set('max_trailing_pe',Number(e.target.value))}/></label>
    <label>最大预期 PE<input type="number" value={form.max_forward_pe} onChange={e=>set('max_forward_pe',Number(e.target.value))}/></label>
    <label>最大市销率<input type="number" value={form.max_price_to_sales} onChange={e=>set('max_price_to_sales',Number(e.target.value))}/></label>
    <label className="settings-toggle">过滤极端动量<input type="checkbox" checked={form.filter_extreme_momentum} onChange={e=>set('filter_extreme_momentum',e.target.checked)}/></label>
    <label>数据不足处理<select value={form.missing_data_policy} onChange={e=>set('missing_data_policy',e.target.value as DiscoverySettings['missing_data_policy'])}><option value="warn">保留并警告</option><option value="watch_only">仅观察</option><option value="reject">过滤</option></select></label>
  </div><button onClick={()=>save.mutate()} disabled={save.isPending}>{save.isPending?'保存中…':'保存机会发现设置'}</button>{save.isSuccess&&<span className="saved">已保存</span>}{save.error&&<span className="error">{save.error.message}</span>}</section>
}
