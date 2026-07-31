import { ChatDialog } from '../components/ChatDialog'
import type { WebAccessMode, WebSearchConfig } from './types'
import { modeCost, SEARCH_MODE_COPY } from './searchModes'

export function DeepSearchConfirmDialog({ mode, config, open, onCancel, onConfirm }: { mode: WebAccessMode; config: WebSearchConfig; open: boolean; onCancel: () => void; onConfirm: () => void }) {
  const cost = modeCost(mode, config)
  const highest = mode === 'deep_xhigh'
  return <ChatDialog open={open} title={highest ? '确认最高强度研究' : '确认深度研究'} onClose={onCancel} className="ai-deep-confirm-dialog"><div className="ai-deep-confirm"><span className={highest ? 'xhigh' : ''}>◎</span><h3>你选择了 {SEARCH_MODE_COPY[mode].label}</h3><p>参考基础费用约 ${cost?.toFixed(2)}，本次还可能产生额外搜索费用。实际费用以 Exa 响应和当前官方计费为准。</p><p>{highest ? '仅建议用于复杂、重要且确实需要最高完整度的研究任务。' : '研究可能需要较长时间，关闭页面不会自动取消已经创建的研究。'}</p><div><button onClick={onCancel}>取消</button><button className={highest ? 'danger' : ''} onClick={onConfirm}>确认继续</button></div></div></ChatDialog>
}
