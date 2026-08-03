import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { groupModels, MessageComposer } from './MessageComposer'
import { ModelSelector } from './ModelSelector'

const models = [
  { id: 'claude-haiku-4-5-20251001', label: 'claude-haiku-4-5-20251001', family: 'claude' as const, is_default: false, available: true },
  { id: 'gpt-5.4-mini', label: 'gpt-5.4-mini', family: 'gpt' as const, is_default: false, available: true },
  { id: 'gpt-5.6-luna', label: 'gpt-5.6-luna', family: 'gpt' as const, is_default: false, available: true },
  { id: 'gpt-5.6-sol', label: 'gpt-5.6-sol', family: 'gpt' as const, is_default: true, available: true },
]

describe('AI message composer model selector', () => {
  it('anchors the current model selector to the Chat header control', () => {
    const html = renderToStaticMarkup(<ModelSelector
      model="gpt-5.6-sol"
      models={models}
      onModel={() => undefined}
      className="ai-chat-header-model"
    />)

    expect(html).toContain('aria-haspopup="listbox"')
    expect(html).toContain('gpt-5.6-sol')
    expect(html).toContain('ai-chat-header-model')
    expect(html).toContain('data-model-logo="gpt"')
    expect(html).toContain('<svg')
  })

  it('groups configured models without rendering a second model control in the composer', () => {
    const html = renderToStaticMarkup(<MessageComposer
      value=""
      onChange={() => undefined}
      onSend={() => undefined}
      onStop={() => undefined}
      generating={false}
      stopping={false}
      model="gpt-5.6-sol"
      models={models}
      onModel={() => undefined}
      symbol={null}
      pageContext={null}
      onRemoveSymbol={() => undefined}
    />)

    expect(groupModels(models).map(group => group.label)).toEqual(['Claude', 'GPT'])
    expect(html).not.toContain('ai-model-picker')
    expect(html).not.toContain('简洁')
    expect(html).not.toContain('标准')
    expect(html).not.toContain('详细')
  })
})
