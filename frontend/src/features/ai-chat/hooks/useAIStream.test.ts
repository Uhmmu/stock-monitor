import { describe, expect, it } from 'vitest'
import type { AIMessage } from '../api'
import { persistAssistantMessage } from './useAIStream'

describe('AI stream persisted messages', () => {
  it('replaces the latest temporary assistant id with the persisted numeric id', () => {
    const older = { id: 'temp-assistant-old', conversation_id: 1, role: 'assistant', status: 'completed' } as AIMessage
    const current = { id: 'temp-assistant-current', conversation_id: 2, role: 'assistant', status: 'streaming' } as AIMessage
    const result = persistAssistantMessage([older, current], 42, 2, 42, 'completed')

    expect(result[0].id).toBe('temp-assistant-old')
    expect(result[1]).toMatchObject({ id: 42, status: 'completed' })
  })
})
