import { describe, expect, it } from 'vitest'
import { newsContentIncomplete, newsSentimentBadge } from './App'

describe('news card badges', () => {
  it('labels sentiment and incomplete source text', () => {
    expect(newsSentimentBadge('positive', null, 'completed')).toEqual({ label: '利好', tone: 'positive' })
    expect(newsSentimentBadge(null, -.4, 'completed')).toEqual({ label: '利空', tone: 'negative' })
    expect(newsSentimentBadge(null, null, 'processing')).toEqual({ label: '判别中', tone: 'pending' })
    expect(newsContentIncomplete('completed', 'completed')).toBe(false)
    expect(newsContentIncomplete('degraded', 'degraded')).toBe(true)
  })
})
