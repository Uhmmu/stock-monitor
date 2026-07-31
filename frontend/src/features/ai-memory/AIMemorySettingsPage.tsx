import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  archiveMemory,
  confirmMemory,
  createMemory,
  deleteMemory,
  getMemory,
  getMemorySettings,
  listMemories,
  memoryKeys,
  rejectMemory,
  restoreMemory,
  updateMemory,
  updateMemorySettings,
} from './api'
import type { Memory } from './types'

const sections=[['active','已启用'],['proposed','待确认'],['stale','需要重新确认'],['expired','已过期'],['archived','已归档']] as const
const typeLabels:Record<string,string>={
  investment_style:'投资风格',risk_policy:'风险政策',portfolio_constraint:'组合约束',
  valuation_preference:'估值偏好',market_preference:'市场偏好',research_preference:'研究偏好',
  communication_preference:'沟通偏好',long_term_goal:'长期目标',project_context:'项目上下文',
  watchlist_interest:'股票关注',recurring_workflow:'固定工作流',general_preference:'一般偏好',
}

export function AIMemorySettingsPage({embedded=false}:{embedded?:boolean}) {
  const client=useQueryClient()
  const [status,setStatus]=useState<(typeof sections)[number][0]>('active')
  const [adding,setAdding]=useState(false)
  const [content,setContent]=useState('')
  const [memoryType,setMemoryType]=useState('general_preference')
  const [historyId,setHistoryId]=useState<number|null>(null)
  const list=useQuery({queryKey:[...memoryKeys.all,status],queryFn:()=>listMemories(status)})
  const settings=useQuery({queryKey:memoryKeys.settings,queryFn:getMemorySettings})
  const history=useQuery({queryKey:['ai-memory-history',historyId],queryFn:()=>getMemory(historyId!),enabled:historyId!==null})
  const refresh=()=>void client.invalidateQueries({queryKey:memoryKeys.all})
  const toggle=useMutation({mutationFn:(body:Record<string,boolean>)=>updateMemorySettings(body),onSuccess:data=>client.setQueryData(memoryKeys.settings,data)})
  const create=useMutation({mutationFn:()=>createMemory({memory_type:memoryType,scope:'global',content,origin:'manual_entry'}),onSuccess:()=>{setAdding(false);setContent('');refresh()}})
  const action=useMutation({mutationFn:async({name,item}:{name:string;item:Memory})=>{
    if(name==='confirm')return confirmMemory(item.id)
    if(name==='reject')return rejectMemory(item.id)
    if(name==='archive')return archiveMemory(item.id)
    if(name==='restore')return restoreMemory(item.id)
    if(name==='edit'){const next=window.prompt('编辑记忆',item.content);return next&&next.trim()?updateMemory(item.id,{content:next.trim()}):item}
    await deleteMemory(item.id);return item
  },onSuccess:refresh})
  const submit=(event:FormEvent)=>{event.preventDefault();if(content.trim())create.mutate()}
  return <div className={`ai-memory-page${embedded?' embedded':''}`}>
    <section className="ai-memory-hero">
      <div><p className="eyebrow">CONTROLLED LONG-TERM MEMORY</p><h2>AI 记忆</h2><p>只有你明确保存或确认的稳定偏好会用于跨会话回答。价格、新闻和模型推断不会静默进入长期记忆。</p></div>
      <button onClick={()=>setAdding(value=>!value)}>{adding?'取消':'＋ 手工添加'}</button>
    </section>
    <section className="ai-memory-controls">
      <label><span><b>启用长期记忆</b><small>关闭后仍保留并可管理已有记录</small></span><input type="checkbox" checked={settings.data?.enabled??false} onChange={event=>toggle.mutate({enabled:event.target.checked})}/></label>
      <label><span><b>在回答中使用</b><small>联网与 Deep Search 回合不会注入私密记忆</small></span><input type="checkbox" checked={settings.data?.use_in_context??false} onChange={event=>toggle.mutate({use_in_context:event.target.checked})}/></label>
      <label><span><b>建议记忆候选</b><small>候选必须由你确认才会启用</small></span><input type="checkbox" checked={settings.data?.candidate_extraction_enabled??false} onChange={event=>toggle.mutate({candidate_extraction_enabled:event.target.checked})}/></label>
    </section>
    {adding&&<form className="ai-memory-create" onSubmit={submit}><select value={memoryType} onChange={event=>setMemoryType(event.target.value)}>{Object.entries(typeLabels).map(([key,label])=><option value={key} key={key}>{label}</option>)}</select><textarea autoFocus value={content} onChange={event=>setContent(event.target.value)} placeholder="例如：分析股票时默认采用长期投资视角" maxLength={4000}/><button disabled={!content.trim()||create.isPending}>保存记忆</button></form>}
    <nav className="ai-memory-tabs">{sections.map(([key,label])=><button key={key} className={status===key?'active':''} onClick={()=>setStatus(key)}>{label}</button>)}</nav>
    <section className="ai-memory-list">
      {list.isLoading&&<div className="empty">正在读取记忆…</div>}
      {list.data?.items.map(item=><article key={item.id}>
        <header><span>{typeLabels[item.memory_type]||item.memory_type}</span><small>{item.scope}{item.scope_key?` · ${item.scope_key}`:''}</small></header>
        <p>{item.content}</p>
        <div className="ai-memory-meta"><span>来源：{item.origin}</span><span>{item.last_confirmed_at?`确认于 ${new Date(item.last_confirmed_at).toLocaleDateString()}`:'尚未确认'}</span>{item.last_used_at&&<span>最近使用 {new Date(item.last_used_at).toLocaleDateString()}</span>}</div>
        {item.supersedes_memory_id&&<em>确认后将替代一条冲突记忆</em>}
        <footer>
          {['proposed','stale','expired'].includes(item.status)&&<button onClick={()=>action.mutate({name:'confirm',item})}>确认</button>}
          {item.status==='proposed'&&<button onClick={()=>action.mutate({name:'reject',item})}>忽略</button>}
          {item.status==='archived'?<button onClick={()=>action.mutate({name:'restore',item})}>恢复</button>:<button onClick={()=>action.mutate({name:'archive',item})}>归档</button>}
          <button onClick={()=>action.mutate({name:'edit',item})}>编辑</button>
          <button onClick={()=>setHistoryId(item.id)}>查看历史</button>
          <button className="danger" onClick={()=>window.confirm('忘记这条记忆？')&&action.mutate({name:'delete',item})}>忘记</button>
        </footer>
      </article>)}
      {!list.isLoading&&!list.data?.items.length&&<div className="empty">这个分区没有记忆。</div>}
    </section>
    {historyId&&<div className="ai-memory-history-scrim" onClick={()=>setHistoryId(null)}><article onClick={event=>event.stopPropagation()}>
      <header><div><small>MEMORY HISTORY</small><h3>{history.data?.title||'记忆修改历史'}</h3></div><button onClick={()=>setHistoryId(null)}>关闭</button></header>
      {history.isLoading?<p>正在读取…</p>:history.data?.events.map(event=><section key={event.id}><b>{event.event_type}</b><time>{new Date(event.created_at).toLocaleString()}</time>{event.message_id&&<small>来源消息 #{event.message_id}</small>}</section>)}
      {!history.isLoading&&!history.data?.events.length&&<p>暂无历史事件。</p>}
    </article></div>}
  </div>
}
