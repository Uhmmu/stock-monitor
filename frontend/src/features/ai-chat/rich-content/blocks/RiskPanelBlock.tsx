import { BlockFrame } from '../components/BlockFrame'
import type { RichBlockProps, RiskPanelData } from '../types'

const severityText = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '严重',
  unknown: '待确认',
}

const statusText = {
  not_triggered: '未触发',
  watching: '观察中',
  partially_triggered: '部分触发',
  triggered: '已触发',
  unknown: '状态未知',
}

export function RiskPanelBlock({ block, citations, onCitation }: RichBlockProps<RiskPanelData>) {
  return <BlockFrame block={block} citations={citations} onCitation={onCitation} tone="risk">
    <div className="ai-rich-risks">
      {block.data.risks.map(risk => <details key={risk.risk_id} open={risk.severity === 'critical' || risk.status === 'triggered'}>
        <summary>
          <span className={`severity-${risk.severity}`}>{severityText[risk.severity]}</span>
          <b>{risk.title}</b>
          <em>{statusText[risk.status]}</em>
        </summary>
        <p>{risk.summary}</p>
        {risk.evidence_summary && <div><span>依据</span><p>{risk.evidence_summary}</p></div>}
        {risk.monitoring_condition && <div><span>观察条件</span><p>{risk.monitoring_condition}</p></div>}
        {risk.citation_keys.length > 0 && <footer>{risk.citation_keys.map(key => <button key={key} onClick={() => onCitation(key)}>{key}</button>)}</footer>}
      </details>)}
    </div>
  </BlockFrame>
}
