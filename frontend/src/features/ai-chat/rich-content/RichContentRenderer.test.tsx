import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { RichContentRenderer } from './RichContentRenderer'
import { supportedRichBlocks } from './registry'
import { validateRichContentDocument } from './validation'

const quoteBlock = {
  block_id: 'block_stock_quote_test',
  block_type: 'stock_quote',
  block_version: 1,
  title: 'MSFT 行情',
  data: {
    symbol: 'MSFT',
    company_name: 'Microsoft',
    price: '512.36',
    currency: 'USD',
    change: '4.21',
    change_percent: '0.83',
    previous_close: '508.15',
    day_high: '514',
    day_low: '507',
    market_status: 'closed',
    sparkline: [],
    as_of: '2026-07-31T20:00:00Z',
  },
  citation_keys: ['S1'],
  source_ids: ['price:MSFT'],
  warnings: [],
  fallback_markdown: '**MSFT**：USD 512.36 [S1]',
}

const document = {
  schema_version: 1,
  parts: [
    { type: 'markdown', part_id: 'markdown_0', content: '先看结论。[S1]' },
    { type: 'block', part_id: 'part_quote', block: quoteBlock },
  ],
  fallback_markdown: '先看结论。[S1]\n\n**MSFT**：USD 512.36 [S1]',
  warnings: [],
}

const citations = [{
  key: 'S1',
  source_id: 'price:MSFT',
  title: 'MSFT quote',
  source_type: 'price',
  symbol: 'MSFT',
  provider: 'yahoo',
  authority: null,
  published_at: null,
  retrieved_at: null,
  locator: null,
  url: null,
}]

describe('Rich AI content runtime', () => {
  it('registers every supported v1 block explicitly', () => {
    expect(supportedRichBlocks()).toEqual([
      'stock_quote:1',
      'metric_grid:1',
      'mini_line_chart:1',
      'valuation_range:1',
      'valuation_summary:1',
      'comparison_table:1',
      'portfolio_allocation:1',
      'risk_panel:1',
      'catalyst_timeline:1',
      'news_cluster:1',
      'sec_filing:1',
      'investment_decision:1',
      'source_list:1',
    ])
  })

  it('validates and renders a known block with citations and freshness-safe data', () => {
    expect(validateRichContentDocument(document)).not.toBeNull()
    const html = renderToStaticMarkup(
      <RichContentRenderer
        document={document}
        fallbackMarkdown={document.fallback_markdown}
        citations={citations}
        onCitation={() => undefined}
      />,
    )
    expect(html).toContain('MSFT 行情')
    expect(html).toContain('US$512.36')
    expect(html).toContain('S1')
  })

  it('uses the block fallback for an unknown version', () => {
    const unknown = {
      ...document,
      parts: [
        document.parts[0],
        {
          type: 'block',
          part_id: 'part_quote_v2',
          block: { ...quoteBlock, block_version: 2 },
        },
      ],
    }
    const html = renderToStaticMarkup(
      <RichContentRenderer
        document={unknown}
        fallbackMarkdown={unknown.fallback_markdown}
        citations={citations}
        onCitation={() => undefined}
      />,
    )
    expect(html).toContain('当前客户端暂不支持这个组件版本')
    expect(html).toContain('USD 512.36')
  })

  it('rejects oversized documents and falls back to persisted Markdown', () => {
    const oversized = {
      ...document,
      parts: Array.from({ length: 42 }, (_, index) => ({
        type: 'markdown',
        part_id: `part_${index}`,
        content: 'x',
      })),
    }
    expect(validateRichContentDocument(oversized)).toBeNull()
    const html = renderToStaticMarkup(
      <RichContentRenderer
        document={oversized}
        fallbackMarkdown="安全降级文本"
        citations={[]}
        onCitation={() => undefined}
      />,
    )
    expect(html).toContain('安全降级文本')
  })

  it('renders the valuation summary card with top methods and the consensus', () => {
    const valuationSummaryBlock = {
      block_id: 'block_valuation_summary_test',
      block_type: 'valuation_summary',
      block_version: 1,
      title: 'MSFT 估值',
      data: {
        symbol: 'MSFT',
        currency: 'USD',
        current_price: '512.36',
        methods: [
          { key: 'dcf', label: 'DCF（现金流折现）', weight_percent: '30', verdict: '合理', stars: 3, fair_value: '510', scenario_low: '420', scenario_high: '600' },
          { key: 'graham', label: 'Graham（格莱厄姆估值）', weight_percent: '20', verdict: '偏贵', fair_value: '402.5' },
          { key: 'forward_pe', label: 'Forward P/E（预期市盈率）', weight_percent: '25', verdict: '偏贵', stars: 2, metric_value: '28.4', metric_unit: 'multiple', peer_median: '25.1', comparison: '高于同行 13%' },
        ],
        consensus_value: '498.2',
        consensus_label: '模型估值共识（公允价值中位数）',
        consensus_position_percent: '2.8',
        model_conflict: false,
        valuation_date: '2026-07-31',
      },
      citation_keys: ['S1'],
      source_ids: ['valuation:MSFT'],
      warnings: [],
      fallback_markdown: '**MSFT 估值**',
    }
    const valuationDocument = {
      schema_version: 1,
      parts: [
        { type: 'markdown', part_id: 'markdown_0', content: '估值结论如下。[S1]' },
        { type: 'block', part_id: 'part_valuation', block: valuationSummaryBlock },
      ],
      fallback_markdown: '估值结论如下。[S1]',
      warnings: [],
    }
    expect(validateRichContentDocument(valuationDocument)).not.toBeNull()
    const html = renderToStaticMarkup(
      <RichContentRenderer
        document={valuationDocument}
        fallbackMarkdown={valuationDocument.fallback_markdown}
        citations={citations}
        onCitation={() => undefined}
      />,
    )
    expect(html).toContain('MSFT 估值')
    expect(html).toContain('模型估值共识（公允价值中位数）')
    expect(html).toContain('US$498.20')
    expect(html).toContain('DCF（现金流折现）')
    expect(html).toContain('Graham（格莱厄姆估值）')
    expect(html).toContain('Forward P/E（预期市盈率）')
    expect(html).toContain('US$510.00')
    expect(html).toContain('权重')
    expect(html).toContain('现价较共识')
  })
})
