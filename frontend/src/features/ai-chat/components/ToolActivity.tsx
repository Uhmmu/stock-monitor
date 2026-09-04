import { useState } from 'react'
import type { ToolActivity as Activity, ToolCallRecord } from '../api'

const statusLabel = (status: string) => status === 'planning' ? '准备中' : status === 'running' ? '进行中' : ['error', 'failed', 'timeout', 'denied'].includes(status) ? '暂不可用' : '已完成'

export function ToolActivity({ records, streaming = [] }: { records: ToolCallRecord[]; streaming?: Activity[] }) {
  const [open, setOpen] = useState(false)
  const items = records.length ? records.map(item => ({
    id: item.tool_call_id,
    name: item.display_name || '研究数据',
    status: item.status,
    summary: item.summary,
    count: item.returned_item_count,
  })) : streaming.map(item => ({ id: item.tool_call_id, name: item.display_name || '研究数据', status: item.status, summary: item.summary, count: item.returned_item_count }))
  if (!items.length) return null
  const planning = items.some(item => item.status === 'planning')
  const running = items.some(item => item.status === 'running' || item.status === 'planning')
  const headline = planning && !items.some(item => item.status === 'running' || item.status === 'completed')
    ? `正在规划 ${items.length} 项工具调用`
    : running ? `正在使用 ${items.length} 项研究数据` : `已使用 ${items.length} 项研究数据`
  return <section className="ai-tool-activity">
    <button aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <span className={running ? 'ai-tool-pulse' : 'ai-tool-done'}/>
      {headline}
      <i>{open ? '收起' : '详情'}</i>
    </button>
    {open && <div>{items.map(item => <div key={item.id}>
      <span>{item.name}</span><small>{item.summary || (item.count != null ? `读取 ${item.count} 项` : statusLabel(item.status))}</small><em>{statusLabel(item.status)}</em>
    </div>)}</div>}
  </section>
}
