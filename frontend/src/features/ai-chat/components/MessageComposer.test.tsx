import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { groupModels, MessageComposer } from './MessageComposer'

describe('AI message composer model selector', () => {
  it('groups every configured model under Claude and GPT without response modes', () => {
    const html = renderToStaticMarkup(<MessageComposer
      value=""
      onChange={() => undefined}
      onSend={() => undefined}
      onStop={() => undefined}
      generating={false}
      stopping={false}
      model="gpt-5.6-sol"
      models={[
        { id: 'claude-haiku-4-5-20251001', label: 'claude-haiku-4-5-20251001', family: 'claude', is_default: false, available: true },
        { id: 'gpt-5.4-mini', label: 'gpt-5.4-mini', family: 'gpt', is_default: false, available: true },
        { id: 'gpt-5.6-luna', label: 'gpt-5.6-luna', family: 'gpt', is_default: false, available: true },
        { id: 'gpt-5.6-sol', label: 'gpt-5.6-sol', family: 'gpt', is_default: true, available: true },
      ]}
      onModel={() => undefined}
      symbol={null}
      pageContext={null}
      onRemoveSymbol={() => undefined}
    />)

    expect(groupModels([
      { id: 'claude-haiku-4-5-20251001', label: 'claude-haiku-4-5-20251001', family: 'claude', is_default: false, available: true },
      { id: 'gpt-5.4-mini', label: 'gpt-5.4-mini', family: 'gpt', is_default: false, available: true },
    ]).map(group => group.label)).toEqual(['Claude', 'GPT'])
    expect(html).toContain('aria-haspopup="listbox"')
    expect(html).toContain('gpt-5.6-sol')
    expect(html).toContain('data-model-logo="gpt"')
    expect(html).toContain('<svg')
    expect(html).not.toContain('简洁')
    expect(html).not.toContain('标准')
    expect(html).not.toContain('详细')
  })
})
