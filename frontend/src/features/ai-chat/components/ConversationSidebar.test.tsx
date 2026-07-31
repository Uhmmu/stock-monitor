import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ConversationSidebar } from './ConversationSidebar'

describe('Chat conversation sidebar', () => {
  it('uses the Chat name and exposes memory management as a setting', () => {
    const html = renderToStaticMarkup(<ConversationSidebar
      open={false}
      items={[]}
      selectedId={null}
      status="active"
      loading={false}
      hasMore={false}
      onLoadMore={() => undefined}
      onClose={() => undefined}
      onNew={() => undefined}
      onSelect={() => undefined}
      onStatus={() => undefined}
      onRename={() => undefined}
      onArchive={() => undefined}
      onDelete={() => undefined}
      onRestore={() => undefined}
      onUnarchive={() => undefined}
      onSettings={() => undefined}
    />)

    expect(html).toContain('Chat 设置')
    expect(html).toContain('长期记忆与偏好')
    expect(html).not.toContain('研究会话')
  })
})
