import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'
import type { AIMessage, Conversation, WebAccessMode } from '@shared/types'
import { formatDateTime } from '@shared/format'
import { createConversation, getAIConfig, getMessages, listConversations, stopGeneration, streamChatMessage, temporaryMessage, type MobileStreamEvent } from '../chat-api'
import { loadChatPreference, newestChatPreference, saveChatPreference, validateChatPreference } from '../chat-preferences'
import { LoadingState, StateView } from '../components'

const modeLabels: Record<WebAccessMode, string> = { off: '不联网', search: '联网搜索', deep_minimal: 'Deep · Minimal', deep_low: 'Deep · Low', deep_medium: 'Deep · Medium', deep_high: 'Deep · High', deep_xhigh: 'Deep · X-High' }
const suggestions = ['分析我的持仓集中度', '本周持仓有哪些重要事件？', '比较我持仓中估值最高的两家公司', '总结最近最需要关注的风险']

export function ChatPage() {
  const client = useQueryClient()
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const initialPreference = useRef(loadChatPreference())
  const [model, setModel] = useState(() => initialPreference.current?.model || '')
  const [webMode, setWebMode] = useState<WebAccessMode>(() => initialPreference.current?.web_access_mode || 'off')
  const [localMessages, setLocalMessages] = useState<AIMessage[]>([])
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [modelMenuOpen, setModelMenuOpen] = useState(false)
  const [webMenuOpen, setWebMenuOpen] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [activity, setActivity] = useState('')
  const [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const modelPicker = useRef<HTMLDivElement>(null)
  const webPicker = useRef<HTMLDivElement>(null)
  const preferencesApplied = useRef(false)
  const config = useQuery({ queryKey: ['ios-ai-config'], queryFn: getAIConfig, staleTime: 5 * 60_000 })
  const conversations = useQuery({ queryKey: ['ios-ai-conversations'], queryFn: listConversations, staleTime: 10_000 })
  const messages = useQuery({ queryKey: ['ios-ai-messages', conversationId], queryFn: () => getMessages(conversationId!), enabled: conversationId != null })
  useEffect(() => {
    const data = config.data
    if (!data || preferencesApplied.current || conversations.isLoading) return
    const latest = conversations.data?.items[0]
    const latestPreference = latest ? { model: latest.model || data.default_model, web_access_mode: latest.web_access_mode, updated_at: latest.last_message_at || latest.updated_at } : null
    const fallback = newestChatPreference(loadChatPreference(), latestPreference)
    const preference = validateChatPreference(fallback, data)
    preferencesApplied.current = true
    setModel(preference.model)
    setWebMode(preference.web_access_mode)
    saveChatPreference(preference.model, preference.web_access_mode)
  }, [config.data, conversations.data, conversations.isLoading])
  useEffect(() => {
    if (!modelMenuOpen && !webMenuOpen) return
    const closeOnOutside = (event: PointerEvent) => {
      if (!(event.target instanceof Node)) return
      if (!modelPicker.current?.contains(event.target)) setModelMenuOpen(false)
      if (!webPicker.current?.contains(event.target)) setWebMenuOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setModelMenuOpen(false); setWebMenuOpen(false) } }
    document.addEventListener('pointerdown', closeOnOutside)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutside)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [modelMenuOpen, webMenuOpen])
  useEffect(() => { if (generating) { setModelMenuOpen(false); setWebMenuOpen(false) } }, [generating])
  useEffect(() => { if (!generating) setLocalMessages([]) }, [conversationId])
  useEffect(() => {
    const viewport = window.visualViewport
    const root = document.documentElement
    const previousOverflow = document.body.style.overflow
    const previousOverscroll = document.body.style.overscrollBehavior
    let frame = 0
    const syncViewport = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        root.style.setProperty('--chat-viewport-top', `${viewport?.offsetTop ?? 0}px`)
        root.style.setProperty('--chat-viewport-height', `${viewport?.height ?? window.innerHeight}px`)
      })
    }
    document.body.style.overflow = 'hidden'
    document.body.style.overscrollBehavior = 'none'
    syncViewport()
    viewport?.addEventListener('resize', syncViewport)
    viewport?.addEventListener('scroll', syncViewport)
    window.addEventListener('resize', syncViewport)
    return () => {
      cancelAnimationFrame(frame)
      viewport?.removeEventListener('resize', syncViewport)
      viewport?.removeEventListener('scroll', syncViewport)
      window.removeEventListener('resize', syncViewport)
      root.style.removeProperty('--chat-viewport-top')
      root.style.removeProperty('--chat-viewport-height')
      document.body.style.overflow = previousOverflow
      document.body.style.overscrollBehavior = previousOverscroll
    }
  }, [])
  const displayMessages = useMemo(() => {
    const map = new Map<string, AIMessage>()
    messages.data?.items.forEach(item => map.set(String(item.id), item))
    localMessages.forEach(item => map.set(String(item.id), item))
    return [...map.values()].sort((a, b) => a.created_at.localeCompare(b.created_at))
  }, [messages.data, localMessages])
  useEffect(() => { const frame = requestAnimationFrame(() => end.current?.scrollIntoView({ block: 'end' })); return () => cancelAnimationFrame(frame) }, [displayMessages, activity])

  const modelOptions = config.data?.models.filter(item => item.available) || []
  const currentModel = config.data?.models.find(item => item.id === model)
  const currentModelLabel = currentModel?.label || model || '默认模型'
  const currentModelId = currentModel?.id || model || (config.data ? '未指定' : '配置加载中')
  const webSearch = config.data?.web_search
  const configuredWebModes: WebAccessMode[] = webSearch?.available_modes?.length ? webSearch.available_modes : ['off']
  const webModes = [...new Set<WebAccessMode>([webMode, ...configuredWebModes])]
  const deepModeConfig = (mode: WebAccessMode) => mode.startsWith('deep_') ? webSearch?.deep_modes[mode.slice(5)] : undefined
  const webModeInfo = (mode: WebAccessMode) => ({ label: mode.startsWith('deep_') ? deepModeConfig(mode)?.label || modeLabels[mode] : modeLabels[mode], deep: deepModeConfig(mode) })
  const currentWebModeInfo = webModeInfo(webMode)
  const webModeDescription = (mode: WebAccessMode, available: boolean) => {
    if (!available) return '当前会话模式不可用'
    if (mode === 'off') return '仅使用账户内研究数据'
    if (mode === 'search') return '搜索最新公开资料'
    const deep = deepModeConfig(mode)
    if (!deep) return '深度研究'
    return deep.confirmation_required ? `发送时确认 · 基础费用 $${deep.estimated_base_cost_usd.toFixed(2)}` : `基础费用约 $${deep.estimated_base_cost_usd.toFixed(2)}`
  }
  const chooseModel = (nextModel: string) => { setModel(nextModel); saveChatPreference(nextModel, webMode); setModelMenuOpen(false) }
  const chooseWebMode = (mode: WebAccessMode) => { setWebMode(mode); saveChatPreference(model, mode); setWebMenuOpen(false) }
  const newConversation = () => { if (generating) return; setConversationId(null); setLocalMessages([]); setDraft(''); setDrawerOpen(false); setModelMenuOpen(false); setWebMenuOpen(false); setError('') }
  const selectConversation = (conversation: Conversation) => { if (generating) return; const nextModel=conversation.model || config.data?.default_model || ''; const nextMode=conversation.web_access_mode || 'off'; setConversationId(conversation.id); setModel(nextModel); setWebMode(nextMode); saveChatPreference(nextModel,nextMode); setLocalMessages([]); setDrawerOpen(false); setModelMenuOpen(false); setWebMenuOpen(false); setError('') }
  const send = async () => {
    const question = draft.trim()
    if (!question || generating) return
    const deep = deepModeConfig(webMode)
    if (deep?.confirmation_required && !window.confirm(`${currentWebModeInfo.label} 预计基础费用 $${deep.estimated_base_cost_usd.toFixed(2)}，继续吗？`)) return
    saveChatPreference(model, webMode)
    setGenerating(true); setError(''); setActivity('正在准备上下文…'); setDraft('')
    let id = conversationId
    try {
      if (id == null) { const created = await createConversation(model || null, webMode); id = created.id; setConversationId(id); void client.invalidateQueries({ queryKey: ['ios-ai-conversations'] }) }
      const stamp = Date.now()
      const userTemp = temporaryMessage(`temp-user-${stamp}`, id, 'user', question)
      const assistantTemp = temporaryMessage(`temp-assistant-${stamp}`, id, 'assistant', '')
      let assistantId: string | number = assistantTemp.id
      setLocalMessages(items => [...items, userTemp, assistantTemp])
      controller.current = new AbortController()
      const handle = (event: MobileStreamEvent) => {
        if (event.type === 'message.created') {
          const user = event.data.user_message as unknown as AIMessage
          const assistant = event.data.assistant_message as unknown as AIMessage
          assistantId = assistant.id
          setLocalMessages(items => [...items.filter(item => !String(item.id).startsWith('temp-')), user, assistant])
        } else if (event.type === 'response.started') setActivity('正在生成回答…')
        else if (event.type === 'context.ready') setActivity('已读取账户内研究数据')
        else if (event.type === 'tool.started') setActivity(String(event.data.display_name || '正在读取研究数据…'))
        else if (event.type === 'tool.completed') setActivity(String(event.data.summary || '研究数据读取完成'))
        else if (event.type === 'response.delta') setLocalMessages(items => items.map(item => item.id === assistantId ? { ...item, content: item.content + String(event.data.delta || '') } : item))
        else if (event.type === 'response.reset') setLocalMessages(items => items.map(item => item.id === assistantId ? { ...item, content: '' } : item))
        else if (event.type === 'citation.map') setLocalMessages(items => items.map(item => item.id === assistantId ? { ...item, citations: event.data.citations as AIMessage['citations'] } : item))
        else if (event.type === 'response.rich_content.completed') { const rich = event.data as { fallback_markdown?: string }; if (rich.fallback_markdown) setLocalMessages(items => items.map(item => item.id === assistantId ? { ...item, content: rich.fallback_markdown || item.content } : item)) }
        else if (event.type === 'deep_search.started' || event.type === 'deep_search.progress') setActivity(String(event.data.message || '深度研究进行中…'))
        else if (event.type === 'response.completed') { const answer = String(event.data.answer || ''); setLocalMessages(items => items.map(item => item.id === assistantId ? { ...item, content: answer || item.content, status: String(event.data.status || 'completed') } : item)); setActivity('') }
        else if (event.type === 'error') throw new Error(String(event.data.message || '回答生成失败'))
      }
      await streamChatMessage(id, { message: question, model: model || null, web_access_mode: webMode, deep_search_confirmed: Boolean(deep?.confirmation_required) }, controller.current.signal, handle)
      await Promise.all([client.invalidateQueries({ queryKey: ['ios-ai-messages', id] }), client.invalidateQueries({ queryKey: ['ios-ai-conversations'] })])
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === 'AbortError')) setError(caught instanceof Error ? caught.message : '连接中断，请稍后重试。')
    } finally { setGenerating(false); setActivity(''); controller.current = null }
  }
  const stop = async () => { controller.current?.abort(); if (conversationId != null) await stopGeneration(conversationId).catch(() => undefined); setGenerating(false); setActivity(''); void client.invalidateQueries({ queryKey: ['ios-ai-messages', conversationId] }) }

  return <main className="mobile-chat-page">
    <header className="mobile-chat-header">
      <button type="button" className="chat-brand-button" onClick={() => setDrawerOpen(true)} aria-label="会话列表"><img src="/icon.svg" alt="本站 Logo"/></button>
      <div className="chat-model-picker" ref={modelPicker}>
        <button type="button" className="chat-model-trigger" onClick={() => setModelMenuOpen(value => !value)} aria-haspopup="listbox" aria-expanded={modelMenuOpen} aria-label={`当前模型：${currentModelLabel}（${currentModelId}），点击切换`}>
          <strong className="chat-model-label">{currentModelLabel}</strong>
          <span className="chat-model-id">{currentModelId}</span>
          <i className="chat-model-chevron" aria-hidden="true">⌄</i>
        </button>
        {modelMenuOpen && <div className="chat-model-menu" role="listbox" aria-label="选择模型">
          {modelOptions.length ? modelOptions.map(option => <button type="button" role="option" aria-selected={option.id === model} className={`chat-model-option${option.id === model ? ' selected' : ''}`} key={option.id} onClick={() => chooseModel(option.id)}>
            <span><strong>{option.label}</strong><small>{option.id}</small></span><i aria-hidden="true">{option.id === model ? '✓' : ''}</i>
          </button>) : <p className="chat-model-empty">{config.isLoading ? '模型配置加载中…' : '暂无可用模型'}</p>}
        </div>}
      </div>
      <button type="button" onClick={newConversation} aria-label="新建对话">＋</button>
    </header>
    <section className="mobile-chat-scroll">{messages.isLoading ? <LoadingState rows={5}/> : !displayMessages.length ? <div className="mobile-chat-empty"><div className="chat-orb">✦</div><h1>今天想研究什么？</h1><p>我可以读取你的持仓、估值、新闻、财报和 SEC 数据，并在回答中保留来源。</p><div>{suggestions.map(value => <button type="button" key={value} onClick={() => setDraft(value)}>{value}<span>↗</span></button>)}</div></div> : displayMessages.map(message => <ChatMessage message={message} key={message.id}/>) }{activity && <div className="chat-activity"><i/><span>{activity}</span></div>}{error && <div className="chat-error"><span>{error}</span><button type="button" onClick={() => setError('')}>关闭</button></div>}<div ref={end}/></section>
    <section className="mobile-chat-composer"><div className="chat-input-row"><textarea className="mobile-chat-input" value={draft} onChange={event => setDraft(event.target.value)} rows={1} maxLength={config.data?.max_message_chars || 12000} placeholder="询问持仓、公司或市场…" onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }}/><div className="chat-web-picker" ref={webPicker}>
      <button type="button" className={`chat-web-trigger${webMode !== 'off' ? ' active' : ''}`} onClick={() => setWebMenuOpen(value => !value)} disabled={generating || !config.data} aria-haspopup="menu" aria-expanded={webMenuOpen} aria-label={config.data ? `联网模式：${currentWebModeInfo.label}` : '联网模式配置加载中'}><WebIcon/></button>
      {webMenuOpen && config.data && <div className="chat-web-menu" role="menu" aria-label="选择联网模式">
        <div className="chat-web-menu-heading"><strong>联网模式</strong><small>{currentWebModeInfo.label}</small></div>
        {webModes.map(mode => {
          const info = webModeInfo(mode)
          const available = configuredWebModes.includes(mode)
          return <button type="button" role="menuitemradio" aria-checked={mode === webMode} className={`chat-web-option${mode === webMode ? ' selected' : ''}`} key={mode} onClick={() => chooseWebMode(mode)}>
            <span><strong>{info.label}</strong><small>{webModeDescription(mode, available)}</small></span><i aria-hidden="true">{mode === webMode ? '✓' : ''}</i>
          </button>
        })}
      </div>}
    </div>{generating ? <button type="button" className="chat-stop" onClick={() => void stop()} aria-label="停止生成"><i/></button> : <button type="button" className="chat-send" onClick={() => void send()} disabled={!draft.trim()} aria-label="发送">↑</button>}</div></section>
    {drawerOpen && <><button type="button" className="chat-drawer-scrim" onClick={() => setDrawerOpen(false)} aria-label="关闭会话列表"/><aside className="chat-drawer"><header><div><span>CHAT HISTORY</span><h2>对话</h2></div><button type="button" onClick={() => setDrawerOpen(false)}>完成</button></header><button type="button" className="new-chat-row" onClick={newConversation}><i>＋</i><span><strong>新对话</strong><small>开始新的研究主题</small></span></button><div>{conversations.data?.items.map(item => <button type="button" className={conversationId === item.id ? 'active' : ''} key={item.id} onClick={() => selectConversation(item)}><span><strong>{item.title}</strong><small>{item.last_message_preview || '还没有消息'}</small></span><time>{formatDateTime(item.last_message_at || item.updated_at)}</time></button>)}</div></aside></>}
  </main>
}

function WebIcon() {
  return <svg className="chat-web-icon" aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.3 2.5 3.5 5.5 3.5 9S14.3 18.5 12 21c-2.3-2.5-3.5-5.5-3.5-9S9.7 5.5 12 3Z"/></svg>
}

function ChatMessage({ message }: { message: AIMessage }) {
  return <article className={`mobile-chat-message ${message.role}`}><div className="chat-message-label">{message.role === 'user' ? '你' : 'Luna'}{message.model && <span>{message.model}</span>}</div><div className="chat-markdown">{message.content ? <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{message.content}</ReactMarkdown> : <span className="typing-dots"><i/><i/><i/></span>}</div>{message.citations?.length > 0 && <details className="chat-citations"><summary>来源 {message.citations.length}</summary>{message.citations.map(item => item.url ? <a href={item.url} target="_blank" rel="noreferrer" key={item.key}>[{item.key}] {item.title}</a> : <span key={item.key}>[{item.key}] {item.title}</span>)}</details>}</article>
}
