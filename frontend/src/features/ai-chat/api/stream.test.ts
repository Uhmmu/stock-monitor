import { describe, expect, it } from 'vitest'
import { parseSSEChunks } from './stream'

async function collect(chunks: (string | Uint8Array)[]) {
  async function* source() { for (const chunk of chunks) yield chunk }
  const events = []
  for await (const event of parseSSEChunks(source())) events.push(event)
  return events
}

describe('AI SSE parser', () => {
  it('parses a single JSON event', async () => {
    const events = await collect(['event: response.delta\ndata: {"delta":"hello"}\n\n'])
    expect(events).toEqual([{ type: 'response.delta', data: { delta: 'hello' } }])
  })

  it('handles cross-chunk boundaries and UTF-8 Chinese', async () => {
    const bytes = new TextEncoder().encode('event: response.delta\ndata: {"delta":"中文回答"}\n\n')
    const events = await collect([bytes.slice(0, 18), bytes.slice(18, 33), bytes.slice(33)])
    expect(events[0]).toEqual({ type: 'response.delta', data: { delta: '中文回答' } })
  })

  it('parses multiple and continuous delta events', async () => {
    const events = await collect([
      'event: response.delta\ndata: {"delta":"A"}\n\n',
      'event: response.delta\ndata: {"delta":"B"}\n\nevent: response.completed\ndata: {"status":"completed","answer":"AB"}\n\n',
    ])
    expect(events.map(event => event.type)).toEqual(['response.delta', 'response.delta', 'response.completed'])
  })

  it('accepts a reset between provisional and final text', async () => {
    const events = await collect([
      'event: response.delta\ndata: {"delta":"先查询"}\n\n',
      'event: response.reset\ndata: {}\n\n',
      'event: response.delta\ndata: {"delta":"最终回答"}\n\n',
    ])
    expect(events.map(event => event.type)).toEqual(['response.delta', 'response.reset', 'response.delta'])
  })

  it('ignores unknown and malformed events without losing later events', async () => {
    const events = await collect([
      'event: provider.reasoning\ndata: {"secret":true}\n\n',
      'event: response.delta\ndata: not-json\n\n',
      'event: error\ndata: {"code":"AI_PROVIDER_UNAVAILABLE","message":"safe"}\n\n',
    ])
    expect(events).toEqual([{ type: 'error', data: { code: 'AI_PROVIDER_UNAVAILABLE', message: 'safe' } }])
  })

  it('accepts CRLF framing split between chunks', async () => {
    const events = await collect(['event: context.ready\r', '\ndata: {"history_message_count":2}\r\n\r', '\n'])
    expect(events[0]?.type).toBe('context.ready')
  })

  it('accepts bounded rich-content completion events', async () => {
    const document = {
      schema_version: 1,
      parts: [{ type: 'markdown', part_id: 'm1', content: '结论' }],
      fallback_markdown: '结论',
      warnings: [],
    }
    const events = await collect([
      `event: response.block.created\ndata: {"block_id":"b1","block_type":"stock_quote","block_version":1}\n\n`,
      `event: response.rich_content.completed\ndata: ${JSON.stringify(document)}\n\n`,
      'event: response.completed\ndata: {"status":"completed","answer":"结论"}\n\n',
    ])
    expect(events.map(event => event.type)).toEqual([
      'response.block.created',
      'response.rich_content.completed',
      'response.completed',
    ])
  })

  it('forwards tool planning and model switch progress events', async () => {
    const events = await collect([
      'event: tool.planning\ndata: {"tool_call_id":"c1","tool":"get_portfolio_summary","display_name":"正在读取组合摘要"}\n\n',
      'event: model.switched\ndata: {"from":"gpt-5.6-sol","to":"gpt-5.6-terra","reason":"AI_PROVIDER_UNAVAILABLE"}\n\n',
      'event: response.delta\ndata: {"delta":"答"}\n\n',
    ])
    expect(events).toEqual([
      { type: 'tool.planning', data: { tool_call_id: 'c1', tool: 'get_portfolio_summary', display_name: '正在读取组合摘要' } },
      { type: 'model.switched', data: { from: 'gpt-5.6-sol', to: 'gpt-5.6-terra', reason: 'AI_PROVIDER_UNAVAILABLE' } },
      { type: 'response.delta', data: { delta: '答' } },
    ])
  })
})
