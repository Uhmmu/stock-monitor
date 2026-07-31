import type { Citation } from '../api'
import { ExternalSourceBadge } from '../search/ExternalSourceBadge'
import { ChatDialog } from './ChatDialog'

const date = (value: string | null | undefined) => value ? new Date(value).toLocaleString('zh-CN', { timeZoneName: 'short' }) : '数据不足'
const sessionLabel:Record<string,string>={pre_market:'盘前',regular:'常规交易',after_hours:'盘后',closed:'已休市',unknown:'未知'}
const statusLabel:Record<string,string>={fresh:'新鲜',delayed:'延迟',stale:'陈旧'}

export function CitationDrawer({ citations, selectedKey, onSelect, onClose }: {
  citations: Citation[]
  selectedKey: string | null
  onSelect: (key: string) => void
  onClose: () => void
}) {
  const ordered = [...citations].sort((a, b) => Number(a.key.replace(/\D/g, '')) - Number(b.key.replace(/\D/g, '')))
  const selected = ordered.find(item => item.key === selectedKey) || ordered[0]
  return <ChatDialog open={citations.length > 0} title="信息来源" onClose={onClose} className="ai-citation-dialog">
    <div className="ai-citation-layout">
      <nav aria-label="引用列表">{ordered.map(item => <button key={item.key} className={item.key === selected?.key ? 'active' : ''} onClick={() => onSelect(item.key)}>
        <b>[{item.key}]</b><span>{item.title || '来源信息不可用'}</span>
      </button>)}</nav>
      {selected ? <article>
        <span className="ai-citation-key">[{selected.key}]</span><ExternalSourceBadge sourceType={selected.source_type}/>
        <h3>{selected.title || '来源信息不可用'}</h3>
        <dl>
          <div><dt>来源类型</dt><dd>{selected.source_type === 'price_snapshot' ? '市场价格快照' : selected.source_type || '数据不足'}</dd></div>
          {selected.symbol && <div><dt>证券</dt><dd>{selected.symbol}</dd></div>}
          <div><dt>提供方</dt><dd>{selected.provider || '数据不足'}</dd></div>
          {selected.source_type === 'price_snapshot' ? <>
            <div><dt>数据源性质</dt><dd>{selected.provider_role === 'market_data_aggregator' ? '市场数据聚合商' : selected.provider_role || '数据不足'}</dd></div>
            <div><dt>行情时点</dt><dd>{date(selected.market_timestamp)}</dd></div>
            <div><dt>获取时间</dt><dd>{date(selected.fetched_at || selected.retrieved_at)}</dd></div>
            <div><dt>入库时间</dt><dd>{date(selected.persisted_at)}</dd></div>
            <div><dt>交易阶段</dt><dd>{sessionLabel[selected.market_session || 'unknown'] || selected.market_session || '未知'}</dd></div>
            <div><dt>数据状态</dt><dd>{statusLabel[selected.data_status || ''] || selected.data_status || '数据不足'}</dd></div>
          </> : <>
            <div><dt>权威主体</dt><dd>{selected.authority || '数据不足'}</dd></div>
            <div><dt>发布时间</dt><dd>{date(selected.published_at)}</dd></div>
            <div><dt>读取时间</dt><dd>{date(selected.retrieved_at)}</dd></div>
          </>}
        </dl>
        {selected.url?.startsWith('http') && <a href={selected.url} target="_blank" rel="noopener noreferrer">打开来源 ↗</a>}
      </article> : <div className="ai-citation-missing">来源信息不可用。</div>}
    </div>
  </ChatDialog>
}
