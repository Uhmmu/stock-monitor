import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getDeepSearchRun, type AIMessage, type Citation, type ToolActivity as Activity, type WebAccessMode } from '../api'
import { SafeMarkdown } from './SafeMarkdown'
import { ToolActivity } from './ToolActivity'
import { DeepSearchRunDetails } from '../search/DeepSearchRunDetails'
import { RichBlockSkeleton, RichContentRenderer } from '../rich-content'

const statusText: Record<string, string> = {
  pending: '准备中…', streaming: '正在生成', partial: '回答未完整生成', failed: '生成失败', cancelled: '已停止生成',
}

const webModeText: Record<WebAccessMode, string> = {
  off: '未联网', search: 'Search', deep_minimal: 'Deep · Minimal', deep_low: 'Deep · Low',
  deep_medium: 'Deep · Medium', deep_high: 'Deep · High', deep_xhigh: 'Deep · X-High',
}

function PersistedDeepRun({ runId }: { runId: string }) {
  const query = useQuery({
    queryKey: ['ai-deep-run', runId],
    queryFn: () => getDeepSearchRun(runId),
    retry: false,
    refetchInterval: state => {
      const run = state.state.data
      return run && ['pending', 'queued', 'running'].includes(run.status) ? 2500 : false
    },
  })
  if (!query.data) return query.isError ? <p className="ai-deep-run-unavailable">Deep Search 运行详情暂不可用。</p> : null
  return <DeepSearchRunDetails run={query.data}/>
}

function MessageActions({ content, onRegenerate, canRegenerate, assistant, savingDecision, onSaveDecision, onShowMemory, onRemember }: { content: string; onRegenerate?: () => void; canRegenerate: boolean; assistant?:boolean; savingDecision?:boolean; onSaveDecision?:()=>void; onShowMemory?:()=>void; onRemember?:()=>void }) {
  const [copied, setCopied] = useState(false)
  return <div className="ai-message-actions">
    <button onClick={async () => { await navigator.clipboard.writeText(content); setCopied(true); window.setTimeout(() => setCopied(false), 1200) }}>{copied ? '已复制' : '复制'}</button>
    {canRegenerate && onRegenerate && <button onClick={onRegenerate}>重新生成</button>}
    {!assistant&&onRemember&&<button onClick={onRemember}>记住这条</button>}
    {assistant&&onSaveDecision&&<button onClick={onSaveDecision} disabled={savingDecision} aria-busy={savingDecision}>{savingDecision?'AI 正在总结…':'保存为投资决策'}</button>}
    {assistant&&onShowMemory&&<button onClick={onShowMemory}>查看使用的记忆</button>}
  </div>
}

function Message({ message, isLatestAssistant, activities, savingDecisionId, onCitation, onRegenerate, onSaveDecision, onShowMemory, onRemember, interrupted }: {
  message: AIMessage
  isLatestAssistant: boolean
  activities: Activity[]
  savingDecisionId?: number
  onCitation: (citations: Citation[], key: string) => void
  onRegenerate: (message: AIMessage) => void
  onSaveDecision: (message:AIMessage)=>void
  onShowMemory: (message:AIMessage)=>void
  onRemember: (message:AIMessage)=>void
  interrupted: boolean
  }) {
  if (message.role === 'user') return <article className="ai-message user-message">
    <div className={`ai-message-web-mode ${message.web_access_mode}`}>{webModeText[message.web_access_mode]}</div>
    <p>{message.content}</p><MessageActions content={message.content} canRegenerate={false} onRemember={()=>onRemember(message)}/>
  </article>
  const pending = message.status === 'pending' || message.status === 'streaming'
  const streamingMarkdown = pending
    ? message.content
      .replace(/\[\[BLOCK:[^\]\r\n]{0,300}\]\]/g, '')
      .replace(/\[\[BLOCK:[^\]\r\n]*$/g, '')
    : message.content
  const hasContent = Boolean(message.content || message.content_parts)
  return <article className={`ai-message assistant-message status-${message.status}`}>
    {message.generation_index > 1 && <div className="ai-message-version">版本 {message.generation_index}</div>}
    <div className={`ai-message-web-mode ${message.web_access_mode}`}>{webModeText[message.web_access_mode]}{message.external_search_cost_usd != null ? ` · $${Number(message.external_search_cost_usd).toFixed(3)}` : ''}</div>
    <ToolActivity records={message.tool_calls} streaming={activities}/>
    {hasContent ? <div className="ai-message-content">
      {message.content_parts
        ? <RichContentRenderer document={message.content_parts} fallbackMarkdown={message.content} citations={message.citations} onCitation={key => onCitation(message.citations, key)}/>
        : <SafeMarkdown content={streamingMarkdown} citations={message.citations} onCitation={key => onCitation(message.citations, key)}/>}
      {message.rich_block_skeletons?.map(block => <RichBlockSkeleton key={block.block_id} blockType={block.block_type}/>)}
      {pending && <span className="ai-stream-cursor" aria-hidden="true"/>}
    </div> : pending ? <div className="ai-thinking"><i/><i/><i/><span>{statusText[message.status]}</span></div> : null}
    {(message.status !== 'completed' || interrupted) && <div className={`ai-message-status ${message.status}`} role={message.status === 'failed' ? 'alert' : 'status'}>{interrupted ? '生成已中断，刷新不会自动重新提交。' : statusText[message.status] || message.error_message_safe || '回答状态异常'}</div>}
    {message.deep_search_run_id && <PersistedDeepRun runId={message.deep_search_run_id}/>} 
    {hasContent && !pending && <MessageActions content={message.content} assistant savingDecision={message.id===savingDecisionId} canRegenerate={isLatestAssistant && ['completed', 'partial', 'failed', 'cancelled'].includes(message.status)} onRegenerate={() => onRegenerate(message)} onSaveDecision={()=>onSaveDecision(message)} onShowMemory={()=>onShowMemory(message)}/>}
  </article>
}

export function MessageList({ messages, loading, hasOlder, loadOlder, loadingOlder, activities, savingDecisionId, onCitation, onRegenerate, onSaveDecision, onShowMemory, onRemember, activeGeneration }: {
  messages: AIMessage[]
  loading: boolean
  hasOlder: boolean
  loadOlder: () => void
  loadingOlder: boolean
  activities: Record<string, Activity[]>
  savingDecisionId?: number
  onCitation: (citations: Citation[], key: string) => void
  onRegenerate: (message: AIMessage) => void
  onSaveDecision: (message:AIMessage)=>void
  onShowMemory: (message:AIMessage)=>void
  onRemember: (message:AIMessage)=>void
  activeGeneration: boolean | null
}) {
  const scroll = useRef<HTMLDivElement>(null)
  const end = useRef<HTMLDivElement>(null)
  const [following, setFollowing] = useState(true)
  const assistants = useMemo(() => messages.filter(item => item.role === 'assistant'), [messages])
  const latestAssistantId = assistants.at(-1)?.id
  useEffect(() => {
    if (!following) return
    const frame = requestAnimationFrame(() => end.current?.scrollIntoView({ block: 'end' }))
    return () => cancelAnimationFrame(frame)
  }, [messages, following])
  const onScroll = () => {
    const element = scroll.current
    if (!element) return
    setFollowing(element.scrollHeight - element.scrollTop - element.clientHeight < 96)
  }
  return <div className="ai-message-scroll" ref={scroll} onScroll={onScroll}>
    <div className="ai-message-column">
      {hasOlder && <button className="ai-load-older" onClick={loadOlder} disabled={loadingOlder}>{loadingOlder ? '正在读取…' : '加载更早消息'}</button>}
      {loading && <div className="ai-message-skeleton"><i/><i/><i/></div>}
      {messages.map(message => <Message
        key={message.id}
        message={message}
        isLatestAssistant={message.id === latestAssistantId}
        activities={activities[String(message.id)] || []}
        savingDecisionId={savingDecisionId}
        onCitation={onCitation}
        onRegenerate={onRegenerate}
        onSaveDecision={onSaveDecision}
        onShowMemory={onShowMemory}
        onRemember={onRemember}
        interrupted={Boolean(activeGeneration === false && message.id === latestAssistantId && ['pending', 'streaming'].includes(message.status))}
      />)}
      <div ref={end}/>
    </div>
    {!following && <button className="ai-scroll-bottom" onClick={() => { setFollowing(true); end.current?.scrollIntoView({ behavior: 'smooth' }) }}>回到底部 ↓</button>}
  </div>
}
