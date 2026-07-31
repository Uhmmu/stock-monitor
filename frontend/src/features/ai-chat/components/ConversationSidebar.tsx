import type { Conversation, ConversationStatus } from '../api'

function relativeTime(value: string | null): string {
  if (!value) return '尚无消息'
  const date = new Date(value)
  const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000)
  if (seconds < 60) return '刚刚'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  const today = new Date()
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1)
  if (date.toDateString() === yesterday.toDateString()) return '昨天'
  if (date.toDateString() === today.toDateString()) return `${Math.floor(seconds / 3600)} 小时前`
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日`
}

export function ConversationSidebar({ open, items, selectedId, status, loading, hasMore, onLoadMore, onClose, onNew, onSelect, onStatus, onRename, onArchive, onDelete, onRestore, onUnarchive, onSettings }: {
  open: boolean
  items: Conversation[]
  selectedId: number | null
  status: ConversationStatus
  loading: boolean
  hasMore: boolean
  onLoadMore: () => void
  onClose: () => void
  onNew: () => void
  onSelect: (id: number) => void
  onStatus: (status: ConversationStatus) => void
  onRename: (item: Conversation) => void
  onArchive: (item: Conversation) => void
  onDelete: (item: Conversation) => void
  onRestore: (item: Conversation) => void
  onUnarchive: (item: Conversation) => void
  onSettings: () => void
}) {
  return <>
    {open && <button className="ai-sidebar-scrim" onClick={onClose} aria-label="关闭会话列表"/>}
    <aside className={`ai-conversation-sidebar${open ? ' open' : ''}`} aria-label="Chat 会话">
      <div className="ai-sidebar-heading"><div><b>Chat</b><small>可恢复的私人历史</small></div><button onClick={onClose} aria-label="关闭会话列表">×</button></div>
      <button className="ai-new-conversation" onClick={onNew}><span>＋</span> 新建会话</button>
      <div className="ai-conversation-filters" aria-label="会话分类">
        {(['active', 'archived', 'deleted'] as const).map(value => <button key={value} className={status === value ? 'active' : ''} onClick={() => onStatus(value)}>{{ active: '最近', archived: '归档', deleted: '已删除' }[value]}</button>)}
      </div>
      <div className="ai-conversation-list">
        {loading && Array.from({ length: 5 }).map((_, index) => <div className="ai-conversation-skeleton" key={index}><i/><i/></div>)}
        {!loading && !items.length && <div className="ai-sidebar-empty"><span>◇</span><b>{status === 'active' ? '还没有 Chat 会话' : status === 'archived' ? '没有归档会话' : '回收区为空'}</b><small>{status === 'active' ? '第一条消息发送时才会创建。' : '这里保持安静。'}</small></div>}
        {items.map(item => <article key={item.id} className={selectedId === item.id ? 'selected' : ''}>
          <button className="ai-conversation-open" onClick={() => onSelect(item.id)} title={`${item.title} · ${new Date(item.last_message_at || item.created_at).toLocaleString('zh-CN')}`}>
            <span><b>{item.title}</b>{item.active_symbol && <em>{item.active_symbol}</em>}</span>
            <p>{item.last_message_preview || '空会话'}</p><time>{relativeTime(item.last_message_at || item.created_at)}</time>
          </button>
          <details><summary aria-label={`${item.title} 更多操作`}>•••</summary><div>
            {status !== 'deleted' && <button onClick={() => onRename(item)}>重命名</button>}
            {status === 'active' && <button onClick={() => onArchive(item)}>归档</button>}
            {status === 'archived' && <button onClick={() => onUnarchive(item)}>移出归档</button>}
            {status === 'deleted' ? <button onClick={() => onRestore(item)}>恢复</button> : <button className="danger" onClick={() => onDelete(item)}>删除</button>}
          </div></details>
        </article>)}
        {hasMore && <button className="ai-load-conversations" onClick={onLoadMore}>加载更多</button>}
      </div>
      <button className="ai-chat-settings-button" onClick={onSettings}><span aria-hidden="true">⚙</span><span><b>Chat 设置</b><small>长期记忆与偏好</small></span><i aria-hidden="true">›</i></button>
    </aside>
  </>
}
