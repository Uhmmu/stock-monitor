import { useEffect, useMemo, useState } from 'react'
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
import {
  AIMemorySettingsPage,
  ChatMemorySuggestions,
  decisionFromMessage,
  deleteMemory,
  extractMessageMemories,
  getMessageMemoryUsage,
  listDecisions,
  listMemoryCandidates,
  memoryKeys,
  updateMemory,
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

export function AIChatPage({ enabled = true }: { enabled?: boolean }) {
  const client = useQueryClient()
  const params = new URLSearchParams(window.location.search)
  const [conversationId, setConversationId] = useState<number | null>(routeConversationId)
  const [initialSymbol, setInitialSymbol] = useState<string | null>(() => params.get('symbol')?.toUpperCase() || null)
  const [initialContext, setInitialContext] = useState<string | null>(() => params.get('context'))
  const [draft, setDraft] = useState('')
  const [selectedModel, setSelectedModel] = useState('')
  const [selectedWebMode, setSelectedWebMode] = useState<WebAccessMode>('off')
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
  const saveDecision=useMutation({mutationFn:(messageId:number)=>decisionFromMessage(messageId),onSuccess:()=>{void client.invalidateQueries({queryKey:['ai-chat-decision-drafts',conversationId]});setToast('已生成决策草稿，请确认后保存')}})
  const rememberMessage=useMutation({mutationFn:(messageId:number)=>extractMessageMemories(messageId),onSuccess:data=>{void client.invalidateQueries({queryKey:memoryKeys.candidates(conversationId||0)});setToast(data.items.length?'已生成待确认的记忆候选':'这条消息没有可安全保存的长期记忆')}})
  const manageUsedMemory=useMutation({mutationFn:async({id,action}:{id:number;action:'edit'|'delete'})=>{
    if(action==='delete')return deleteMemory(id)
    const current=usage.data?.memories.find(item=>item.id===id)
    const next=window.prompt('编辑记忆',current?.content||'')
    if(next?.trim())return updateMemory(id,{content:next.trim()})
  },onSuccess:()=>{void usage.refetch();void client.invalidateQueries({queryKey:memoryKeys.all})}})

  useEffect(() => {
    const model = detail.data?.model || aiConfig.data?.default_model
    if (model) setSelectedModel(model)
  }, [detail.data, aiConfig.data?.default_model])
  useEffect(() => {
    const mode = detail.data?.web_access_mode || aiConfig.data?.web_search.default_mode
    if (mode) setSelectedWebMode(mode)
  }, [detail.data?.web_access_mode, aiConfig.data?.web_search.default_mode])

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
    setSelectedWebMode(aiConfig.data?.web_search.default_mode || 'off')
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
    if (conversationId != null) update.mutate({ id: conversationId, body: { model } })
  }
  const applyWebMode = (mode: WebAccessMode, preserveConfirmation = false) => {
    setSelectedWebMode(mode)
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
      <button className="ai-conversation-toggle" onClick={() => setSidebarOpen(true)} aria-label="打开会话列表">☰</button>
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
        onCitation={openCitation}
        onRegenerate={regenerate}
        onSaveDecision={message=>typeof message.id==='number'&&saveDecision.mutate(message.id)}
        onShowMemory={message=>typeof message.id==='number'&&setUsageMessageId(message.id)}
        onRemember={message=>typeof message.id==='number'&&rememberMessage.mutate(message.id)}
        activeGeneration={generating ? true : activeGeneration.data?.active ?? null}
      />
      <ChatMemorySuggestions memories={candidates.data?.items||[]} decisions={decisionDrafts.data?.items||[]}/>
      </>}
      {stream.error && <div className="ai-stream-error" role="alert"><span>{stream.error}</span><button onClick={() => stream.setError(null)}>关闭</button></div>}
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
