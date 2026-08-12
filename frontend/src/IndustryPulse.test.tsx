import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  buildTaxonomyTree,
  chainFlow,
  confidenceText,
  coverageText,
  extractFocusBuckets,
  normalizePulseRow,
  scoreText,
} from './IndustryPulse'

describe('行业板块检测', () => {
  it('规范化行业节点并保留三类独立分数', () => {
    const row = normalizePulseRow({
      id: 'semis', name_zh: '半导体', pulse_score: 88, delta_5d: 4.5,
      strength_score: 90, heat_score: 82, risk_score: 61,
      children: [{ id: 'chips', name: '芯片', pulse: 77 }],
    })
    expect(row).toMatchObject({ id: 'semis', name: '半导体', pulse: 88, change5d: 4.5, strength: 90, heat: 82, risk: 61 })
    expect(row.children[0]).toMatchObject({ id: 'chips', name: '芯片', pulse: 77 })
  })

  it('缺失值使用明确的数据不足语义', () => {
    expect(scoreText(null)).toBe('数据不足')
    expect(confidenceText(null)).toBe('置信度不足')
    expect(coverageText('low')).toBe('低覆盖')
  })

  it('提取重点板块分组并保留中文信号名称', () => {
    const buckets = extractFocusBuckets({ buckets: { leaders: [{ id: 'a', name: '软件', pulse: 90 }], fastest_heating: [{ id: 'b', name: '能源', pulse: 74 }] } })
    expect(buckets.map(bucket => bucket.label)).toEqual(['今日领涨', '升温最快'])
    expect(buckets[0].rows[0].name).toBe('软件')
  })

  it('把扁平分类节点组装成可展开的行业树', () => {
    const roots = buildTaxonomyTree({ nodes: [
      { id: 'tech', name: '科技' },
      { id: 'software', name: '软件', parent_id: 'tech' },
      { id: 'saas', name: 'SaaS', parent_id: 'software' },
    ] })
    expect(roots).toHaveLength(1)
    expect(roots[0].children[0].children[0].name).toBe('SaaS')
  })

  it('按上游到下游重排 AI 产业链', () => {
    const phases = chainFlow({ groups: [
      { node_key: 'ai.applications', nodes: [{ id: 'app', name: '应用', pulse: 70 }] },
      { node_key: 'ai.power', nodes: [{ id: 'power', name: '电力', pulse: 60 }] },
      { node_key: 'ai.infrastructure', nodes: [{ id: 'infra', name: '基建', pulse: 50 }] },
    ] })
    expect(phases.map(phase => phase.key)).toEqual(['upstream', 'infrastructure', 'downstream'])
    expect(phases[0].rows[0].name).toBe('电力')
  })

  it('异步状态公开忙碌、错误和空数据语义', () => {
    expect(renderToStaticMarkup(<LoadingState text="正在读取行业脉冲" />)).toContain('aria-busy="true"')
    expect(renderToStaticMarkup(<ErrorState text="读取失败" />)).toContain('role="alert"')
    expect(renderToStaticMarkup(<EmptyState text="暂无快照" />)).toContain('暂无快照')
  })
})
