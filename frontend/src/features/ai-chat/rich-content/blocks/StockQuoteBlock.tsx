import { BlockFrame } from '../components/BlockFrame'
import { formatCurrency, formatDate, formatPercent, toNumber } from '../format'
import type { RichBlockProps, StockQuoteData } from '../types'

const marketStatus = {
  pre_market: '盘前',
  open: '交易中',
  after_hours: '盘后',
  closed: '已收盘',
  unknown: '状态未知',
}

export function StockQuoteBlock({ block, citations, onCitation }: RichBlockProps<StockQuoteData>) {
  const change = toNumber(block.data.change_percent)
  const tone = change == null ? 'neutral' : change > 0 ? 'positive' : change < 0 ? 'negative' : 'neutral'
  return <BlockFrame block={block} citations={citations} onCitation={onCitation} tone={tone}>
    <div className="ai-rich-quote">
      <div className="ai-rich-quote-symbol">
        <b>{block.data.symbol}</b>
        {block.data.company_name && <span>{block.data.company_name}</span>}
      </div>
      <div className="ai-rich-quote-price">
        <strong>{formatCurrency(block.data.price, block.data.currency)}</strong>
        <span className={tone}>
          {formatCurrency(block.data.change, block.data.currency)} · {formatPercent(block.data.change_percent)}
        </span>
      </div>
      <dl>
        <div><dt>前收</dt><dd>{formatCurrency(block.data.previous_close, block.data.currency)}</dd></div>
        <div><dt>日内高点</dt><dd>{formatCurrency(block.data.day_high, block.data.currency)}</dd></div>
        <div><dt>日内低点</dt><dd>{formatCurrency(block.data.day_low, block.data.currency)}</dd></div>
        <div><dt>市场</dt><dd>{marketStatus[block.data.market_status]}</dd></div>
      </dl>
      <small>报价时间 {formatDate(block.data.as_of, true)}</small>
    </div>
  </BlockFrame>
}
