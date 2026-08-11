import { useEffect, useMemo, useRef, useState } from 'react'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  archiveConversation,
  conversationKeys,
  deleteConversation,
  getAIConfig,
  getActiveGeneration,
  getConversation,
  getMessages,
  getActiveDeepSearchRun,
  cancelDeepSearchRun,
  listConversations,
  restoreConversation,
  updateConversation,
  type AIMessage,
  type Citation,
  type Conversation,
  type ConversationStatus,
  type WebAccessMode,
} from '../api'
import { useAIStream } from '../hooks/useAIStream'
import { ChatDialog } from '../components/ChatDialog'
import { CitationDrawer } from '../components/CitationDrawer'
import { ConversationSidebar } from '../components/ConversationSidebar'
import { MessageComposer } from '../components/MessageComposer'
import { MessageList } from '../components/MessageList'
import { DeepSearchConfirmDialog } from '../search/DeepSearchConfirmDialog'
import { DeepSearchProgress } from '../search/DeepSearchProgress'
import { effortForMode, isDeepMode } from '../search/searchModes'
import { loadChatPreference, newestChatPreference, saveChatPreference, validateChatPreference } from '../preferences'
import {
  AIMemorySettingsPage,
  ChatMemorySuggestions,
  decisionFromMessage,
  resolveDecision,
  deleteMemory,
  extractMessageMemories,
  getMessageMemoryUsage,
  listDecisions,
  listMemoryCandidates,
  memoryKeys,
  updateMemory,
  type DecisionDraftPreview,
} from '../../ai-memory'

function routeConversationId(): number | null {
  const match = window.location.pathname.match(/^\/ai\/(\d+)\/?$/)
  return match ? Number(match[1]) : null
}

function navigate(id: number | null, context?: { symbol?: string | null; pageContext?: string | null }) {
  const params = new URLSearchParams()
  if (context?.symbol) params.set('symbol', context.symbol)
  if (context?.pageContext) params.set('context', context.pageContext)
  const path = id == null ? `/ai/new${params.size ? `?${params}` : ''}` : `/ai/${id}`
  window.history.pushState({}, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

const generatingStates = new Set(['creating_conversation', 'connecting', 'streaming', 'stopping'])
const apiErrorMessage=(error:unknown,fallback:string)=>{if(!(error instanceof Error))return fallback;try{return JSON.parse(error.message).detail||fallback}catch{return fallback}}

export function AIChatPage({ enabled = true }: { enabled?: boolean }) {
  const client = useQueryClient()
  const params = new URLSearchParams(window.location.search)
  const [conversationId, setConversationId] = useState<number | null>(routeConversationId)
  const [initialSymbol, setInitialSymbol] = useState<string | null>(() => params.get('symbol')?.toUpperCase() || null)
  const [initialContext, setInitialContext] = useState<string | null>(() => params.get('context'))
  const [draft, setDraft] = useState('')
  const initialPreference = useRef(loadChatPreference())
  const [selectedModel, setSelectedModel] = useState(() => initialPreference.current?.model || '')
  const [selectedWebMode, setSelectedWebMode] = useState<WebAccessMode>(() => initialPreference.current?.web_access_mode || 'off')
  const [confirmedWebMode, setConfirmedWebMode] = useState<WebAccessMode | null>(null)
  const [confirmIntent, setConfirmIntent] = useState<{ mode: WebAccessMode; action: 'select' | 'send' | 'regenerate'; message?: AIMessage } | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [filter, setFilter] = useState<ConversationStatus>('active')
  const [citationState, setCitationState] = useState<{ citations: Citation[]; key: string | null }>({ citations: [], key: null })
  const [rename, setRename] = useState<Conversation | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [deleting, setDeleting] = useState<Conversation | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [usageMessageId,setUsageMessageId] = useState<number|null>(null)
  const [decisionPreview,setDecisionPreview] = useState<DecisionDraftPreview|null>(null)
  const [memorySettingsOpen,setMemorySettingsOpen] = useState(() => window.location.pathname.startsWith('/ai-memory'))

  useEffect(() => {
    if (window.location.pathname.startsWith('/ai-memory')) window.history.replaceState({}, '', '/ai/new')
    const onPop = () => {
      setConversationId(routeConversationId())
      const next = new URLSearchParams(window.location.search)
      setInitialSymbol(next.get('symbol')?.toUpperCase() || null)
      setInitialContext(next.get('context'))
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 2400)
    return () => window.clearTimeout(timer)
  }, [toast])

  const stream = useAIStream({
    conversationId,
    onConversationCreated: id => { setConversationId(id); navigate(id) },
  })
  const generating = generatingStates.has(stream.state)

  const conversations = useInfiniteQuery({
    queryKey: ['ai-conversations', filter],
    queryFn: ({ pageParam }) => listConversations(filter, pageParam, 30),
    initialPageParam: 1,
    getNextPageParam: last => last.has_more ? last.page + 1 : undefined,
    enabled,
  })
  const aiConfig = useQuery({ queryKey: ['ai-config'], queryFn: getAIConfig, enabled, staleTime: 5 * 60 * 1000 })
  const conversationItems = conversations.data?.pages.flatMap(page => page.items) || []
  const latestConversation = conversationItems[0]
  const detail = useQuery({ queryKey: conversationKeys.detail(conversationId || 0), queryFn: () => getConversation(conversationId!), enabled: enabled && conversationId != null })
  const messages = useInfiniteQuery({
    queryKey: conversationKeys.messages(conversationId || 0),
    queryFn: ({ pageParam }) => getMessages(conversationId!, pageParam, 80),
    initialPageParam: 1,
    getNextPageParam: last => last.has_more ? last.page + 1 : undefined,
    enabled: enabled && conversationId != null,
  })
  const activeGeneration = useQuery({
    queryKey: ['ai-active-generation', conversationId],
    queryFn: () => getActiveGeneration(conversationId!),
    enabled: enabled && conversationId != null,
    retry: false,
    staleTime: 3000,
  })
  const activeDeepRun = useQuery({
    queryKey: ['ai-active-deep-run', conversationId],
    queryFn: () => getActiveDeepSearchRun(conversationId!),
    enabled: enabled && conversationId != null,
    retry: false,
    refetchInterval: query => {
      const run = query.state.data
      return generating || (run && ['pending', 'queued', 'running'].includes(run.status)) ? 2000 : false
    },
  })
  const candidates=useQuery({queryKey:memoryKeys.candidates(conversationId||0),queryFn:()=>listMemoryCandidates(conversationId!),enabled:enabled&&conversationId!=null,refetchInterval:generating?2000:false})
  const decisionDrafts=useQuery({queryKey:['ai-chat-decision-drafts',conversationId],queryFn:()=>listDecisions('draft',conversationId!),enabled:enabled&&conversationId!=null,refetchInterval:generating?2000:false})
  const usage=useQuery({queryKey:['ai-message-memory-usage',usageMessageId],queryFn:()=>getMessageMemoryUsage(usageMessageId!),enabled:usageMessageId!==null,retry:false})
  const saveDecision=useMutation({mutationFn:(messageId:number)=>decisionFromMessage(messageId),onSuccess:data=>setDecisionPreview(data),onError:error=>setToast(apiErrorMessage(error,'AI 未能提取出可用的投资决策，请稍后重试'))})
  const finalizeDecision=useMutation({mutationFn:(resolution:'standalone'|'keep_both'|'replace_existing'|'merge')=>resolveDecision(decisionPreview!.candidate,resolution,decisionPreview!.conflicts.map(item=>item.id)),onSuccess:item=>{void client.invalidateQueries({queryKey:['ai-chat-decision-drafts',conversationId]});void client.invalidateQueries({queryKey:memoryKeys.decisions});setDecisionPreview(null);setToast(`已生成决策 #${item.decision_number}，请在投资决策区确认`)},onError:error=>setToast(apiErrorMessage(error,'投资决策保存失败，请稍后重试'))})
  const rememberMessage=useMutation({mutationFn:(messageId:number)=>extractMessageMemories(messageId),onSuccess:data=>{void client.invalidateQueries({queryKey:memoryKeys.candidates(conversationId||0)});setToast(data.items.length?'已生成待确认的记忆候选':'这条消息没有可安全保存的长期记忆')}})
  const manageUsedMemory=useMutation({mutationFn:async({id,action}:{id:number;action:'edit'|'delete'})=>{
    if(action==='delete')return deleteMemory(id)
    const current=usage.data?.memories.find(item=>item.id===id)
    const next=window.prompt('编辑记忆',current?.content||'')
    if(next?.trim())return updateMemory(id,{content:next.trim()})
  },onSuccess:()=>{void usage.refetch();void client.invalidateQueries({queryKey:memoryKeys.all})}})

  useEffect(() => {
    const config = aiConfig.data
    if (!config) return
    if (conversationId != null) {
      if (!detail.data) return
      const preference = validateChatPreference({
        model: detail.data.model || config.default_model,
        web_access_mode: detail.data.web_access_mode,
        updated_at: detail.data.updated_at,
      }, config)
      setSelectedModel(preference.model)
      setSelectedWebMode(preference.web_access_mode)
      saveChatPreference(preference.model, preference.web_access_mode)
      return
    }
    const stored = loadChatPreference()
    const latest = latestConversation ? {
      model: latestConversation.model || config.default_model,
      web_access_mode: latestConversation.web_access_mode,
      updated_at: latestConversation.last_message_at || latestConversation.updated_at,
    } : null
    const fallback = newestChatPreference(stored, latest)
    const preference = validateChatPreference(fallback, config)
    setSelectedModel(preference.model)
    setSelectedWebMode(preference.web_access_mode)
    saveChatPreference(preference.model, preference.web_access_mode)
  }, [conversationId, detail.data, aiConfig.data, latestConversation?.id, latestConversation?.model, latestConversation?.web_access_mode, latestConversation?.updated_at, latestConversation?.last_message_at])

  const serverMessages = useMemo(() => {
    const pages = [...(messages.data?.pages || [])].reverse()
    return pages.flatMap(page => page.items)
  }, [messages.data])
  const displayMessages = useMemo(() => {
    const map = new Map<string, AIMessage>()
    serverMessages.forEach(item => map.set(String(item.id), item))
    stream.localMessages.filter(item => item.conversation_id === conversationId).forEach(item => map.set(String(item.id), item))
    return [...map.values()].sort((a, b) => a.created_at.localeCompare(b.created_at) || String(a.id).localeCompare(String(b.id)))
  }, [conversationId, serverMessages, stream.localMessages])
  useEffect(() => stream.clearPersisted(new Set(serverMessages.map(item => String(item.id)))), [serverMessages, stream.clearPersisted])

  const symbol = detail.data ? detail.data.active_symbol : initialSymbol
  const pageContext = detail.data ? detail.data.page_context : initialContext
  const effectiveModel = selectedModel || aiConfig.data?.default_model || ''
  const invalidate = () => client.invalidateQueries({ queryKey: conversationKeys.all })
  const update = useMutation({ mutationFn: ({ id, body }: { id: number; body: Parameters<typeof updateConversation>[1] }) => updateConversation(id, body), onSuccess: item => { client.setQueryData(conversationKeys.detail(item.id), item); invalidate() } })
  const archive = useMutation({ mutationFn: (id: number) => archiveConversation(id), onSuccess: (_, id) => { invalidate(); setToast('会话已归档'); if (conversationId === id) newConversation() } })
  const remove = useMutation({ mutationFn: (id: number) => deleteConversation(id), onSuccess: (_, id) => { invalidate(); setDeleting(null); setToast('会话已移至已删除'); if (conversationId === id) newConversation() } })
  const restore = useMutation({ mutationFn: (id: number) => restoreConversation(id), onSuccess: () => { invalidate(); setToast('会话已恢复') } })
  const cancelDeep = useMutation({ mutationFn: (runId: string) => cancelDeepSearchRun(runId), onSuccess: run => {
    client.setQueryData(['ai-active-deep-run', conversationId], run)
    if (conversationId != null) client.invalidateQueries({ queryKey: conversationKeys.messages(conversationId) })
    setToast('深度研究已取消')
  } })

  const newConversation = () => {
    if (generating) void stream.stop()
    setConversationId(null)
    setInitialSymbol(null)
    setInitialContext(null)
    setDraft('')
    if (aiConfig.data) {
      const preference = validateChatPreference(loadChatPreference(), aiConfig.data)
      setSelectedModel(preference.model)
      setSelectedWebMode(preference.web_access_mode)
    }
    setConfirmedWebMode(null)
    setSidebarOpen(false)
    navigate(null)
  }
  const selectConversation = (id: number) => {
    if (filter === 'deleted') return
    if (generating) void stream.stop()
    setConversationId(id)
    setInitialSymbol(null)
    setInitialContext(null)
    setSidebarOpen(false)
    navigate(id)
  }
  const dispatchSend = (confirmed = false) => {
    const question = draft
    if (!question.trim() || generating) return
    setDraft('')
    void stream.send(question, {
      active_symbol: symbol,
      active_symbols: symbol ? [symbol] : [],
      page_context: pageContext,
      active_portfolio_id: detail.data?.active_portfolio_id ?? null,
      model: effectiveModel || null,
      web_access_mode: selectedWebMode,
      deep_search_confirmed: confirmed || confirmedWebMode === selectedWebMode,
    })
    if (selectedWebMode === 'deep_xhigh') setConfirmedWebMode(null)
  }
  const send = () => {
    const effort = effortForMode(selectedWebMode)
    const requiresConfirmation = effort ? aiConfig.data?.web_search.deep_modes[effort]?.confirmation_required : false
    if (requiresConfirmation && confirmedWebMode !== selectedWebMode) {
      setConfirmIntent({ mode: selectedWebMode, action: 'send' })
      return
    }
    dispatchSend()
  }
  const changeModel = (model: string) => {
    setSelectedModel(model)
    saveChatPreference(model, selectedWebMode)
    if (conversationId != null) update.mutate({ id: conversationId, body: { model } })
  }
  const applyWebMode = (mode: WebAccessMode, preserveConfirmation = false) => {
    setSelectedWebMode(mode)
    saveChatPreference(effectiveModel, mode)
    if (!preserveConfirmation && mode !== confirmedWebMode) setConfirmedWebMode(null)
    if (conversationId != null) update.mutate({ id: conversationId, body: { web_access_mode: mode } })
  }
  const changeWebMode = (mode: WebAccessMode) => {
    const effort = effortForMode(mode)
    if (effort && aiConfig.data?.web_search.deep_modes[effort]?.confirmation_required) {
      setConfirmIntent({ mode, action: 'select' })
    } else {
      applyWebMode(mode)
    }
  }
  const confirmDeepMode = () => {
    if (!confirmIntent) return
    const { mode, action } = confirmIntent
    setConfirmIntent(null)
    setConfirmedWebMode(mode)
    if (action === 'select') applyWebMode(mode, true)
    else if (action === 'send') dispatchSend(true)
    else if (confirmIntent.message) void stream.regenerate(confirmIntent.message, effectiveModel || null, mode, true)
  }
  const regenerate = (message: AIMessage) => {
    const effort = effortForMode(message.web_access_mode)
    if (effort && aiConfig.data?.web_search.deep_modes[effort]?.confirmation_required) {
      setConfirmIntent({ mode: message.web_access_mode, action: 'regenerate', message })
      return
    }
    void stream.regenerate(message, effectiveModel || null, message.web_access_mode, false)
  }
  const removeSymbol = () => {
    setInitialSymbol(null)
    if (conversationId != null) update.mutate({ id: conversationId, body: { active_symbol: null, active_symbols: [] } })
  }
  const openRename = (item: Conversation) => { setRename(item); setRenameValue(item.title) }
  const saveRename = () => {
    if (!rename || !renameValue.trim()) return
    update.mutate({ id: rename.id, body: { title: renameValue.trim() } }, { onSuccess: () => { setRename(null); setToast('会话名称已更新') } })
  }
  const openCitation = (citations: Citation[], key: string) => setCitationState({ citations: citations.length ? citations : [{ key, source_id: '', title: '来源信息不可用', source_type: 'unknown', symbol: null, provider: null, authority: null, published_at: null, retrieved_at: null, locator: null, url: null }], key })

  if (!enabled) return <div className="ai-chat-unavailable"><h2>Chat 需要登录账户</h2><p>演示空间不会发起模型请求，也不会创建会话。</p></div>

  return <div className="ai-chat-page">
    <ConversationSidebar
      open={sidebarOpen}
      items={conversationItems}
      selectedId={conversationId}
      status={filter}
      loading={conversations.isLoading}
      hasMore={Boolean(conversations.hasNextPage)}
      onLoadMore={() => conversations.fetchNextPage()}
      onClose={() => setSidebarOpen(false)}
      onNew={newConversation}
      onSelect={selectConversation}
      onStatus={setFilter}
      onRename={openRename}
      onArchive={item => archive.mutate(item.id)}
      onDelete={setDeleting}
      onRestore={item => restore.mutate(item.id)}
      onUnarchive={item => update.mutate({ id: item.id, body: { archived: false } }, { onSuccess: () => { invalidate(); setToast('会话已移出归档') } })}
      onSettings={() => { setSidebarOpen(false); setMemorySettingsOpen(true) }}
    />
    <section className="ai-chat-workspace">
      <button className="ai-conversation-toggle" onClick={() => setSidebarOpen(true)} aria-label="打开会话列表"><img src="/logo.png" alt=""/></button>
      {detail.isError && <div className="ai-chat-error" role="alert">该会话不存在、已删除，或当前账户无权访问。</div>}
      {!conversationId && !displayMessages.length ? <div className="ai-chat-empty">
        <h2>开始一段对话</h2><p>我会读取你已保存的持仓、估值、新闻与 SEC 数据，并把依据放在回答旁边。</p>
        <div>{['分析我的持仓集中度', '查看 MSFT 最近的重要风险', '比较 NVDA 和 AVGO 的估值', '检查本周持仓相关事件'].map(value => <button key={value} onClick={() => setDraft(value)}>{value}<span>↗</span></button>)}</div>
      </div> : <>
      <MessageList
        messages={displayMessages}
        loading={messages.isLoading}
        hasOlder={Boolean(messages.hasNextPage)}
        loadOlder={() => messages.fetchNextPage()}
        loadingOlder={messages.isFetchingNextPage}
        activities={stream.activities}
        savingDecisionId={saveDecision.isPending?saveDecision.variables:undefined}
        onCitation={openCitation}
        onRegenerate={regenerate}
        onSaveDecision={message=>typeof message.id==='number'&&!saveDecision.isPending&&saveDecision.mutate(message.id)}
        onShowMemory={message=>typeof message.id==='number'&&setUsageMessageId(message.id)}
        onRemember={message=>typeof message.id==='number'&&rememberMessage.mutate(message.id)}
        activeGeneration={generating ? true : activeGeneration.data?.active ?? null}
      />
      <ChatMemorySuggestions memories={candidates.data?.items||[]} decisions={decisionDrafts.data?.items||[]}/>
      </>}
      {stream.error && <div className="ai-stream-error" role="alert"><span>{stream.error}</span><button onClick={() => stream.setError(null)}>关闭</button></div>}
      {saveDecision.isPending&&<div className="ai-decision-progress" role="status" aria-live="polite"><div><strong>AI 正在提炼投资决策</strong><span>正在阅读整段对话，整理投资逻辑、风险与失效条件…</span></div><i role="progressbar" aria-label="投资决策提炼进度" aria-valuetext="处理中"><span/></i></div>}
      {activeDeepRun.data && ['pending', 'queued', 'running'].includes(activeDeepRun.data.status) && <DeepSearchProgress run={activeDeepRun.data} cancelling={cancelDeep.isPending} onCancel={() => cancelDeep.mutate(activeDeepRun.data!.run_id)}/>} 
      <MessageComposer
        value={draft}
        onChange={setDraft}
        onSend={send}
        onStop={() => {
          if (activeDeepRun.data && ['pending', 'queued', 'running'].includes(activeDeepRun.data.status)) cancelDeep.mutate(activeDeepRun.data.run_id)
          void stream.stop()
        }}
        generating={generating}
        stopping={stream.state === 'stopping'}
        disabled={detail.isError}
        model={effectiveModel}
        models={aiConfig.data?.models || []}
        onModel={changeModel}
        webMode={selectedWebMode}
        webSearchConfig={aiConfig.data?.web_search}
        onWebMode={changeWebMode}
        stopLabel={isDeepMode(selectedWebMode) ? '取消研究' : '停止'}
        symbol={symbol}
        pageContext={pageContext}
        onRemoveSymbol={removeSymbol}
      />
      <div className="sr-only" aria-live="polite">{{ idle: '', creating_conversation: '正在创建会话', connecting: '正在连接模型', streaming: '正在生成回答', stopping: '正在停止', completed: '回答已完成', partial: '回答未完整生成', failed: '回答生成失败', cancelled: '回答已停止' }[stream.state]}</div>
    </section>
    <CitationDrawer citations={citationState.citations} selectedKey={citationState.key} onSelect={key => setCitationState(value => ({ ...value, key }))} onClose={() => setCitationState({ citations: [], key: null })}/>
    <ChatDialog open={memorySettingsOpen} title="Chat 设置" onClose={()=>setMemorySettingsOpen(false)} className="ai-chat-settings-dialog">
      <AIMemorySettingsPage embedded/>
    </ChatDialog>
    <ChatDialog open={usageMessageId!==null} title="本回答使用的记忆" onClose={()=>setUsageMessageId(null)}>
      <div className="ai-memory-usage">{usage.isLoading?<p>正在读取…</p>:<>
        {usage.data?.summary_snapshot&&<section><b>会话摘要 v{usage.data.summary_snapshot.version}</b><p>{usage.data.summary_snapshot.summary_text}</p></section>}
        {usage.data?.memories.map(item=><section key={item.id}><b>{item.memory_type} · {item.scope}</b><p>{item.content}</p><small>{item.last_confirmed_at?`最后确认 ${new Date(item.last_confirmed_at).toLocaleDateString()}`:'确认时间未知'}</small><div><button onClick={()=>manageUsedMemory.mutate({id:item.id,action:'edit'})}>编辑</button><button className="danger" onClick={()=>window.confirm('忘记这条记忆？')&&manageUsedMemory.mutate({id:item.id,action:'delete'})}>忘记</button></div></section>)}
        {usage.data?.decisions.map(item=><section key={item.id}><b>投资决策 · {item.title}</b><p>{item.action}</p></section>)}
        {!usage.data?.summary_snapshot&&!usage.data?.memories.length&&!usage.data?.decisions.length&&<p>本回答未使用已保存的长期记忆或投资决策。</p>}
      </>}</div>
    </ChatDialog>
    <ChatDialog open={decisionPreview!==null} title="确认投资决策" onClose={()=>!finalizeDecision.isPending&&setDecisionPreview(null)} className="ai-decision-compare-dialog">
      {decisionPreview&&<div className="ai-decision-compare">
        <p className="ai-decision-summary"><b>AI 对话总结</b>{decisionPreview.conversation_summary}</p>
        <div className={decisionPreview.conflicts.length?'has-conflict':''}>
          <DecisionPreviewCard label="本次对话产生的新决策（可修改）" item={decisionPreview.candidate} onChange={candidate=>setDecisionPreview({...decisionPreview,candidate})}/>
          {decisionPreview.conflicts.map(item=><DecisionPreviewCard key={item.id} label={`已有决策 #${item.decision_number}`} item={item}/>) }
        </div>
        {decisionPreview.conflicts.length>0&&<p className="ai-decision-conflict-note">检测到同一证券已有决策。合并会保留原序号，并创建一个带完整关联关系的新决策；不会覆盖历史记录。</p>}
        <footer><button onClick={()=>setDecisionPreview(null)} disabled={finalizeDecision.isPending}>撤销</button>{decisionPreview.conflicts.length?<><button onClick={()=>finalizeDecision.mutate('keep_both')} disabled={finalizeDecision.isPending}>两条都保留</button><button onClick={()=>finalizeDecision.mutate('replace_existing')} disabled={finalizeDecision.isPending}>保留最新</button><button className="primary" onClick={()=>finalizeDecision.mutate('merge')} disabled={finalizeDecision.isPending||!decisionPreview.candidate.title.trim()||!decisionPreview.candidate.action.trim()}>{finalizeDecision.isPending?'Luna 正在合并…':'交给 Luna 合并'}</button></>:<button className="primary" onClick={()=>finalizeDecision.mutate('standalone')} disabled={finalizeDecision.isPending||!decisionPreview.candidate.title.trim()||!decisionPreview.candidate.action.trim()}>{finalizeDecision.isPending?'保存中…':'确认并保存草稿'}</button>}</footer>
      </div>}
    </ChatDialog>
    <ChatDialog open={rename !== null} title="重命名会话" onClose={() => setRename(null)}>
      <form className="ai-dialog-form" onSubmit={event => { event.preventDefault(); saveRename() }}><label>会话名称<input autoFocus value={renameValue} onChange={event => setRenameValue(event.target.value)} maxLength={200}/></label><div><button type="button" onClick={() => setRename(null)}>取消</button><button type="submit" disabled={!renameValue.trim() || update.isPending}>保存</button></div></form>
    </ChatDialog>
    <ChatDialog open={deleting !== null} title="删除会话？" onClose={() => setDeleting(null)}>
      <div className="ai-delete-dialog"><p>“{deleting?.title}”将移到已删除会话，之后仍可恢复。</p><div><button onClick={() => setDeleting(null)}>取消</button><button className="danger" onClick={() => deleting && remove.mutate(deleting.id)} disabled={remove.isPending}>{remove.isPending ? '删除中…' : '删除'}</button></div></div>
    </ChatDialog>
    {aiConfig.data?.web_search && <DeepSearchConfirmDialog mode={confirmIntent?.mode || selectedWebMode} config={aiConfig.data.web_search} open={confirmIntent !== null} onCancel={() => setConfirmIntent(null)} onConfirm={confirmDeepMode}/>} 
    {toast && <div className="ai-chat-toast" role="status">{toast}</div>}
  </div>
}

function DecisionPreviewCard({label,item,onChange}:{label:string;item:any;onChange?:(item:any)=>void}) {
  const sections:[string,string][]=[['投资逻辑','thesis'],['催化剂','catalysts'],['风险','risks'],['失效条件','invalidation_conditions'],['关键假设','assumptions'],['待解决问题','open_questions']]
  if(!onChange)return <article className="ai-decision-compare-card"><span>{label}</span><h3>{item.title}</h3><strong>{item.action}</strong><div>{sections.map(([name,key])=><section key={key}><b>{name}</b><p>{(item[key]||[]).join('；')||'数据不足 / 待补充'}</p></section>)}</div></article>
  const patch=(value:Record<string,unknown>)=>onChange({...item,...value})
  return <article className="ai-decision-compare-card editable"><span>{label}</span><div className="ai-decision-edit-meta"><label>标题<input required maxLength={240} value={item.title} onChange={event=>patch({title:event.target.value})}/></label><label>证券代码<input value={(item.symbols||[]).join(' / ')} onChange={event=>patch({symbols:event.target.value.split(/[\s,，/]+/).filter(Boolean).map((value:string)=>value.toUpperCase())})}/></label><label>决策类型<select value={item.decision_type} onChange={event=>patch({decision_type:event.target.value})}><option value="buy">买入</option><option value="add">加仓</option><option value="hold">持有</option><option value="reduce">减仓</option><option value="sell">卖出</option><option value="avoid">回避</option><option value="watch">观察</option><option value="portfolio">组合</option><option value="other">其他</option></select></label><label>时间周期<select value={item.time_horizon} onChange={event=>patch({time_horizon:event.target.value})}><option value="short_term">短期</option><option value="medium_term">中期</option><option value="long_term">长期</option><option value="event_driven">事件驱动</option><option value="unspecified">未指定</option></select></label></div><label className="ai-decision-action">最终目标<textarea required maxLength={4000} value={item.action} onChange={event=>patch({action:event.target.value})}/></label><div>{sections.map(([name,key])=><label key={key}>{name}<textarea value={(item[key]||[]).join('\n')} onChange={event=>patch({[key]:event.target.value.split('\n').map(value=>value.trim()).filter(Boolean)})}/></label>)}</div></article>
}
