import { FormEvent, useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  confirmDecision,
  createDecisionReview,
  createDecision,
  createReviewDraft,
  deleteDecision,
  executeDecision,
  getDecision,
  listDecisions,
  memoryKeys,
  transitionDecision,
  updateDecision,
} from './api'
import type { InvestmentDecision } from './types'

const typeLabels:Record<string,string>={buy:'买入',add:'加仓',hold:'持有',reduce:'减仓',sell:'卖出',avoid:'回避',watch:'观察',rebalance:'再平衡',hedge:'对冲',research:'研究',thesis:'投资逻辑'}
const statusLabels:Record<string,string>={draft:'草稿',active:'有效',executed:'已执行',partially_executed:'部分执行',cancelled:'已取消',invalidated:'已失效',closed:'已关闭',archived:'已归档'}
const split=(value:string)=>value.split('\n').map(row=>row.trim()).filter(Boolean)
const routeDecisionId=()=>Number(window.location.pathname.match(/^\/investment-decisions\/(\d+)/)?.[1]||0)||null
const emptyForm={symbol:'',decision_type:'hold',action:'',thesis:'',catalysts:'',risks:'',invalidation:'',assumptions:'',open_questions:'',time_horizon:'long_term',target_review_at:'',confidence:''}
const emptyReview={thesis_status:'uncertain',invalidation_status:'unknown',what_changed:'',supporting_changes:'',contradicting_changes:'',lessons:'',next_action:''}

export function InvestmentDecisionsPage() {
  const client=useQueryClient()
  const [filters,setFilters]=useState({status:'',symbol:'',decisionType:'',search:'',timeHorizon:'',reviewDue:'',dateFrom:'',dateTo:'',minConfidence:'',portfolio:''})
  const [selected,setSelected]=useState<number|null>(routeDecisionId)
  const [adding,setAdding]=useState(false)
  const [editing,setEditing]=useState<number|null>(null)
  const [form,setForm]=useState(emptyForm)
  const [reviewing,setReviewing]=useState(false)
  const [reviewForm,setReviewForm]=useState(emptyReview)
  useEffect(()=>{const onPop=()=>setSelected(routeDecisionId());window.addEventListener('popstate',onPop);return()=>window.removeEventListener('popstate',onPop)},[])
  const list=useQuery({queryKey:[...memoryKeys.decisions,filters],queryFn:()=>listDecisions({status:filters.status||undefined,symbol:filters.symbol.trim()||undefined,decisionType:filters.decisionType||undefined,search:filters.search.trim()||undefined,timeHorizon:filters.timeHorizon||undefined,reviewDue:filters.reviewDue?filters.reviewDue==='due':undefined,decisionDateFrom:filters.dateFrom||undefined,decisionDateTo:filters.dateTo||undefined,minConfidence:filters.minConfidence===''?undefined:Number(filters.minConfidence),portfolioId:filters.portfolio===''?undefined:Number(filters.portfolio)})})
  const detail=useQuery({queryKey:['ai-investment-decision',selected],queryFn:()=>getDecision(selected!),enabled:selected!==null})
  const refresh=()=>{void client.invalidateQueries({queryKey:memoryKeys.decisions});if(selected)void client.invalidateQueries({queryKey:['ai-investment-decision',selected]})}
  const save=useMutation({mutationFn:()=>{
    const body={title:`${form.symbol||'投资'} · ${typeLabels[form.decision_type]}`,decision_type:form.decision_type,symbols:form.symbol?[form.symbol.toUpperCase()]:[],action:form.action,time_horizon:form.time_horizon,target_review_at:form.target_review_at?new Date(form.target_review_at).toISOString():null,thesis:split(form.thesis),catalysts:split(form.catalysts),risks:split(form.risks),invalidation_conditions:split(form.invalidation),assumptions:split(form.assumptions),open_questions:split(form.open_questions),confidence:form.confidence===''?null:Number(form.confidence)}
    return editing?updateDecision(editing,body):createDecision(body)
  },onSuccess:item=>{setAdding(false);setEditing(null);setForm(emptyForm);refresh();open(item)}})
  const action=useMutation({mutationFn:async({name,item}:{name:string;item:InvestmentDecision})=>{
    if(name==='confirm')return confirmDecision(item.id)
    if(name==='execute')return executeDecision(item.id)
    if(name==='delete'){await deleteDecision(item.id);return item}
    return transitionDecision(item.id,name as 'cancel'|'invalidate'|'close'|'archive')
  },onSuccess:()=>refresh()})
  const beginReview=useMutation({mutationFn:(id:number)=>createReviewDraft(id),onSuccess:draft=>{setReviewing(true);setReviewForm({...emptyReview,thesis_status:draft.thesis_status,invalidation_status:draft.invalidation_status,what_changed:draft.what_changed,next_action:draft.next_action||''});refresh()}})
  const saveReview=useMutation({mutationFn:(id:number)=>createDecisionReview(id,{status:'completed',review_type:'manual',data_as_of:new Date().toISOString(),thesis_status:reviewForm.thesis_status,invalidation_status:reviewForm.invalidation_status,what_changed:reviewForm.what_changed,supporting_changes:split(reviewForm.supporting_changes),contradicting_changes:split(reviewForm.contradicting_changes),lessons:split(reviewForm.lessons),next_action:reviewForm.next_action}),onSuccess:()=>{setReviewing(false);setReviewForm(emptyReview);refresh()}})
  const open=(item:InvestmentDecision)=>{setSelected(item.id);window.history.pushState({},'',`/investment-decisions/${item.id}`)}
  const close=()=>{setSelected(null);window.history.pushState({},'','/investment-decisions')}
  const edit=(item:InvestmentDecision)=>{setEditing(item.id);setAdding(true);setForm({symbol:item.primary_symbol||'',decision_type:item.decision_type,action:item.action,thesis:item.thesis.join('\n'),catalysts:item.catalysts.join('\n'),risks:item.risks.join('\n'),invalidation:item.invalidation_conditions.join('\n'),assumptions:item.assumptions.join('\n'),open_questions:item.open_questions.join('\n'),time_horizon:item.time_horizon,target_review_at:item.target_review_at?.slice(0,10)||'',confidence:item.confidence==null?'':String(item.confidence)});close()}
  const submit=(event:FormEvent)=>{event.preventDefault();if(form.action.trim())save.mutate()}
  const item=detail.data
  return <div className="ai-decisions-page">
    <section className="ai-memory-hero"><div><p className="eyebrow">INVESTMENT DECISION MEMORY</p><h2>投资决策日志</h2><p>保存当时的判断、证据和失效条件。决策不会自动交易，也不会因新数据静默改写。</p></div><button onClick={()=>{if(adding){setEditing(null);setForm(emptyForm)};setAdding(value=>!value)}}>{adding?'取消':'＋ 新建决策'}</button></section>
    {adding&&<form className="ai-decision-create" onSubmit={submit}>
      <h3>{editing?'编辑决策草稿':'新建决策草稿'}</h3>
      <div><label>股票代码<input value={form.symbol} onChange={event=>setForm({...form,symbol:event.target.value})} maxLength={32}/></label><label>决策类型<select value={form.decision_type} onChange={event=>setForm({...form,decision_type:event.target.value})}>{Object.entries(typeLabels).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select></label><label>持有周期<select value={form.time_horizon} onChange={event=>setForm({...form,time_horizon:event.target.value})}><option value="days">数日</option><option value="weeks">数周</option><option value="months">数月</option><option value="years">数年</option><option value="long_term">长期</option></select></label><label>目标复盘日<input type="date" value={form.target_review_at} onChange={event=>setForm({...form,target_review_at:event.target.value})}/></label></div>
      <label>行动<textarea value={form.action} onChange={event=>setForm({...form,action:event.target.value})} required/></label>
      <label>投资逻辑（每行一条）<textarea value={form.thesis} onChange={event=>setForm({...form,thesis:event.target.value})}/></label>
      <label>催化剂（每行一条）<textarea value={form.catalysts} onChange={event=>setForm({...form,catalysts:event.target.value})}/></label>
      <label>主要风险（每行一条）<textarea value={form.risks} onChange={event=>setForm({...form,risks:event.target.value})}/></label>
      <label>失效条件（每行一条）<textarea value={form.invalidation} onChange={event=>setForm({...form,invalidation:event.target.value})}/></label>
      <label>关键假设（每行一条）<textarea value={form.assumptions} onChange={event=>setForm({...form,assumptions:event.target.value})}/></label>
      <label>待确认问题（每行一条）<textarea value={form.open_questions} onChange={event=>setForm({...form,open_questions:event.target.value})}/></label>
      <label>信心 0–1<input type="number" min="0" max="1" step="0.05" value={form.confidence} onChange={event=>setForm({...form,confidence:event.target.value})}/></label>
      <button disabled={save.isPending||!form.action.trim()}>{editing?'保存草稿修改':'保存为决策草稿'}</button>
    </form>}
    <div className="ai-decision-toolbar"><input aria-label="搜索决策" placeholder="搜索标题或行动" value={filters.search} onChange={event=>setFilters({...filters,search:event.target.value})}/><input aria-label="股票代码筛选" placeholder="代码" value={filters.symbol} onChange={event=>setFilters({...filters,symbol:event.target.value.toUpperCase()})}/><select value={filters.status} onChange={event=>setFilters({...filters,status:event.target.value})}><option value="">全部状态</option>{Object.entries(statusLabels).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select><select value={filters.decisionType} onChange={event=>setFilters({...filters,decisionType:event.target.value})}><option value="">全部类型</option>{Object.entries(typeLabels).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select><select value={filters.timeHorizon} onChange={event=>setFilters({...filters,timeHorizon:event.target.value})}><option value="">全部周期</option>{['days','weeks','months','years','long_term','unspecified'].map(value=><option value={value} key={value}>{value}</option>)}</select><select value={filters.reviewDue} onChange={event=>setFilters({...filters,reviewDue:event.target.value})}><option value="">全部复盘状态</option><option value="due">待复盘</option><option value="not-due">未到期</option></select><input aria-label="决策日期起" type="date" value={filters.dateFrom} onChange={event=>setFilters({...filters,dateFrom:event.target.value})}/><input aria-label="决策日期止" type="date" value={filters.dateTo} onChange={event=>setFilters({...filters,dateTo:event.target.value})}/><input aria-label="最低信心" type="number" min="0" max="1" step="0.1" placeholder="最低信心" value={filters.minConfidence} onChange={event=>setFilters({...filters,minConfidence:event.target.value})}/><input aria-label="组合编号" type="number" min="1" placeholder="组合编号" value={filters.portfolio} onChange={event=>setFilters({...filters,portfolio:event.target.value})}/><span>{list.data?.total||0} 条决策</span></div>
    <section className="ai-decision-list">{list.data?.items.map(row=><button key={row.id} onClick={()=>open(row)}><span className={`decision-status ${row.status}`}>{statusLabels[row.status]||row.status}</span><div><h3>{row.title}</h3><p>{row.action}</p><small>{row.decision_date} · {typeLabels[row.decision_type]||row.decision_type} · {row.time_horizon}{row.confidence==null?'':` · 信心 ${Math.round(row.confidence*100)}%`}{row.portfolio_id?` · 组合 #${row.portfolio_id}`:''}</small></div>{row.review_due&&<em>待复盘</em>}<b>›</b></button>)}{!list.isLoading&&!list.data?.items.length&&<div className="empty">还没有投资决策。</div>}</section>
    {selected&&<div className="ai-decision-detail-scrim" onClick={close}><article className="ai-decision-detail" onClick={event=>event.stopPropagation()}>
      <button className="close" onClick={close}>关闭</button>{!item?<div className="empty">正在读取决策…</div>:<>
      <header><span className={`decision-status ${item.status}`}>{statusLabels[item.status]||item.status}</span><h2>{item.title}</h2><p>{item.action}</p><small>决策日 {item.decision_date} · 数据不会自动改写</small></header>
      <section><h3>投资逻辑</h3>{item.thesis.map((value,index)=><p key={index}>{value}</p>)}{!item.thesis.length&&<p>数据不足 / 待补充</p>}</section>
      <div className="ai-decision-columns"><section><h3>催化剂</h3>{item.catalysts.map((value,index)=><p key={index}>{value}</p>)}{!item.catalysts.length&&<p>待补充</p>}</section><section><h3>风险</h3>{item.risks.map((value,index)=><p key={index}>{value}</p>)}{!item.risks.length&&<p>待补充</p>}</section></div>
      <section className="invalidation"><h3>失效条件</h3>{item.invalidation_conditions.map((value,index)=><p key={index}>{value}</p>)}{!item.invalidation_conditions.length&&<p>尚未记录明确失效条件。</p>}</section>
      <div className="ai-decision-columns"><section><h3>关键假设</h3>{item.assumptions.map((value,index)=><p key={index}>{value}</p>)}{!item.assumptions.length&&<p>待补充</p>}</section><section><h3>待确认问题</h3>{item.open_questions.map((value,index)=><p key={index}>{value}</p>)}{!item.open_questions.length&&<p>无</p>}</section></div>
      <section><h3>当时证据</h3>{item.evidence.map(source=><a href={source.url||undefined} target="_blank" rel="noreferrer" key={source.id}><span>{source.evidence_role}</span><b>{source.title}</b><small>{source.freshness_status} · {source.as_of||source.retrieved_at||'日期未知'}</small></a>)}{!item.evidence.length&&<p>未关联来源证据。</p>}</section>
      <section><h3>复盘时间线</h3>{item.reviews.map(review=><article key={review.id}><b>{review.thesis_status} · {review.invalidation_status}</b><p>{review.what_changed}</p><small>{review.data_as_of||review.created_at}</small></article>)}{!item.reviews.length&&<p>尚未复盘。</p>}</section>
      {reviewing&&<form className="ai-decision-review-form" onSubmit={event=>{event.preventDefault();saveReview.mutate(item.id)}}><h3>确认复盘结论</h3><div><label>投资逻辑状态<select value={reviewForm.thesis_status} onChange={event=>setReviewForm({...reviewForm,thesis_status:event.target.value})}>{['strengthened','unchanged','weakened','broken','uncertain'].map(value=><option value={value} key={value}>{value}</option>)}</select></label><label>失效条件状态<select value={reviewForm.invalidation_status} onChange={event=>setReviewForm({...reviewForm,invalidation_status:event.target.value})}>{['not_triggered','partially_triggered','triggered','unknown'].map(value=><option value={value} key={value}>{value}</option>)}</select></label></div><label>发生了什么变化<textarea required value={reviewForm.what_changed} onChange={event=>setReviewForm({...reviewForm,what_changed:event.target.value})}/></label><label>支持逻辑的新信息（每行一条）<textarea value={reviewForm.supporting_changes} onChange={event=>setReviewForm({...reviewForm,supporting_changes:event.target.value})}/></label><label>反驳逻辑的新信息（每行一条）<textarea value={reviewForm.contradicting_changes} onChange={event=>setReviewForm({...reviewForm,contradicting_changes:event.target.value})}/></label><label>经验与下一步<textarea value={reviewForm.lessons} onChange={event=>setReviewForm({...reviewForm,lessons:event.target.value})}/><textarea value={reviewForm.next_action} onChange={event=>setReviewForm({...reviewForm,next_action:event.target.value})} placeholder="下一步"/></label><footer><button type="button" onClick={()=>setReviewing(false)}>取消</button><button className="primary" disabled={saveReview.isPending||!reviewForm.what_changed.trim()}>保存复盘</button></footer></form>}
      <section><h3>执行与关联</h3><p>组合：{item.portfolio_id?`#${item.portfolio_id}`:'未关联'} · 交易：{item.executed_trade_id?`#${item.executed_trade_id}`:'未关联'} · 会话：{item.source_conversation_id?`#${item.source_conversation_id}`:'无'}</p><small>{item.executed_at?`手工标记执行于 ${new Date(item.executed_at).toLocaleString()}`:'系统不会自动执行交易。'}</small></section>
      <footer>{item.status==='draft'&&<><button onClick={()=>edit(item)}>编辑草稿</button><button onClick={()=>action.mutate({name:'cancel',item})}>取消草稿</button><button className="primary" onClick={()=>action.mutate({name:'confirm',item})}>保存为正式决策</button></>}{item.status==='active'&&<><button onClick={()=>beginReview.mutate(item.id)}>开始复盘</button><button onClick={()=>action.mutate({name:'execute',item})}>标记已执行</button><button onClick={()=>action.mutate({name:'cancel',item})}>取消</button><button onClick={()=>action.mutate({name:'invalidate',item})}>标记失效</button><button onClick={()=>action.mutate({name:'close',item})}>关闭决策</button></>}{['executed','partially_executed','cancelled','invalidated','closed'].includes(item.status)&&<button onClick={()=>action.mutate({name:'archive',item})}>归档</button>}<button className="danger" onClick={()=>window.confirm('删除这条决策？')&&action.mutate({name:'delete',item})}>删除</button></footer>
      </>}</article></div>}
  </div>
}
