import { BlockFrame } from '../components/BlockFrame'
import { formatCurrency, formatDate, formatNumber, toNumber } from '../format'
import type { RichBlockProps, ValuationMethodItem, ValuationSummaryData } from '../types'

function verdictTone(verdict: string | null | undefined): string {
  if (verdict === '低估') return 'positive'
  if (verdict === '偏贵') return 'negative'
  return 'neutral'
}

function MethodRow({ method, currency }: { method: ValuationMethodItem; currency: string }) {
  const weight = toNumber(method.weight_percent)
  const stars = method.stars ?? null
  const verdict = method.verdict || null
  return <div className="ai-rich-valuation-method">
    <div className="ai-rich-valuation-method-head">
      <b>{method.label}</b>
      {verdict && <span className={`ai-rich-verdict ${verdictTone(verdict)}`}>{verdict}</span>}
    </div>
    <div className="ai-rich-valuation-method-body">
      {method.fair_value != null && <span className="ai-rich-method-value">
        {formatCurrency(method.fair_value, currency)}
        {toNumber(method.scenario_low) != null && toNumber(method.scenario_high) != null && <small>
          {formatCurrency(method.scenario_low, currency)}–{formatCurrency(method.scenario_high, currency)}
        </small>}
      </span>}
      {method.metric_value != null && <span className="ai-rich-method-value">
        {formatNumber(method.metric_value)}{method.metric_unit === 'percent' ? '%' : ''}
        {method.peer_median != null && <small>同行中位数 {formatNumber(method.peer_median)}</small>}
      </span>}
      {method.fair_value == null && method.metric_value == null && <span className="ai-rich-method-value">数据不足</span>}
      {weight != null && <em>权重 {formatNumber(weight)}%</em>}
    </div>
    {(method.comparison || method.note || stars != null) && <small className="ai-rich-valuation-method-note">
      {stars != null && <span aria-label={`模型信号 ${stars}/5`}>{'★'.repeat(stars)}{'☆'.repeat(5 - stars)}</span>}
      {method.comparison}
      {method.note}
    </small>}
  </div>
}

export function ValuationSummaryBlock({ block, citations, onCitation }: RichBlockProps<ValuationSummaryData>) {
  const { data } = block
  const position = toNumber(data.consensus_position_percent)
  const positionTone = position == null || Math.abs(position) < 5 ? 'neutral' : position > 0 ? 'negative' : 'positive'
  return <BlockFrame block={block} citations={citations} onCitation={onCitation}>
    <div className="ai-rich-valuation-summary">
      <div className="ai-rich-valuation-summary-head">
        <div>
          <span>当前价格</span>
          <strong>{formatCurrency(data.current_price, data.currency)}</strong>
        </div>
        <div className="ai-rich-valuation-consensus">
          <span>{data.consensus_label || '模型估值共识'}</span>
          <strong>{formatCurrency(data.consensus_value, data.currency)}</strong>
          {position != null && <em className={positionTone}>
            现价较共识 {position > 0 ? '+' : ''}{formatNumber(position)}%
          </em>}
          {data.model_conflict != null && <small>{data.model_conflict ? '模型之间存在分歧' : '模型方向一致'}</small>}
        </div>
      </div>
      {data.methods.length > 0 && <div className="ai-rich-valuation-methods">
        {data.methods.map(method => <MethodRow key={method.key} method={method} currency={data.currency}/>)}
      </div>}
      <small className="ai-rich-valuation-summary-footer">
        {data.valuation_date ? `估值快照 ${formatDate(data.valuation_date)}` : '估值快照'} · 估值用于研究比较，不构成投资建议。
      </small>
    </div>
  </BlockFrame>
}
