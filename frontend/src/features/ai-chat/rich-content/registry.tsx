import type { ComponentType } from 'react'
import type { RichBlockProps } from './types'
import { blockDataValidators } from './blockValidators'
import { StockQuoteBlock } from './blocks/StockQuoteBlock'
import { MetricGridBlock } from './blocks/MetricGridBlock'
import { MiniLineChartBlock } from './blocks/MiniLineChartBlock'
import { ValuationRangeBlock } from './blocks/ValuationRangeBlock'
import { ComparisonTableBlock } from './blocks/ComparisonTableBlock'
import { PortfolioAllocationBlock } from './blocks/PortfolioAllocationBlock'
import { RiskPanelBlock } from './blocks/RiskPanelBlock'
import { CatalystTimelineBlock } from './blocks/CatalystTimelineBlock'
import { NewsClusterBlock } from './blocks/NewsClusterBlock'
import { SecFilingBlock } from './blocks/SecFilingBlock'
import { InvestmentDecisionBlock } from './blocks/InvestmentDecisionBlock'
import { SourceListBlock } from './blocks/SourceListBlock'

type Registration = {
  component: ComponentType<RichBlockProps<any>>
  validate: (value: unknown) => boolean
}

const registry = new Map<string, Registration>()

function register(
  blockType: string,
  version: number,
  component: ComponentType<RichBlockProps<any>>,
) {
  const key = `${blockType}:${version}`
  if (registry.has(key)) throw new Error(`Duplicate rich block registration: ${key}`)
  registry.set(key, {
    component,
    validate: blockDataValidators[blockType],
  })
}

register('stock_quote', 1, StockQuoteBlock)
register('metric_grid', 1, MetricGridBlock)
register('mini_line_chart', 1, MiniLineChartBlock)
register('valuation_range', 1, ValuationRangeBlock)
register('comparison_table', 1, ComparisonTableBlock)
register('portfolio_allocation', 1, PortfolioAllocationBlock)
register('risk_panel', 1, RiskPanelBlock)
register('catalyst_timeline', 1, CatalystTimelineBlock)
register('news_cluster', 1, NewsClusterBlock)
register('sec_filing', 1, SecFilingBlock)
register('investment_decision', 1, InvestmentDecisionBlock)
register('source_list', 1, SourceListBlock)

export function getRichBlockRegistration(blockType: string, version: number) {
  return registry.get(`${blockType}:${version}`) || null
}

export function supportedRichBlocks() {
  return [...registry.keys()]
}
