import { Component, type ErrorInfo, type PropsWithChildren, type ReactNode } from 'react'
import type { Citation } from '../../api'
import type { RichBlock } from '../types'
import { SafeMarkdown } from '../../components/SafeMarkdown'

type Props = PropsWithChildren<{
  block: RichBlock<unknown>
  citations: Citation[]
  onCitation: (key: string) => void
}>

type State = { failed: boolean }

export class RichBlockErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // The Markdown fallback is intentionally local; one block cannot take the
    // rest of the assistant message down with it.
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children
    return <div className="ai-rich-block-fallback" role="status">
      <p>该组件暂时无法显示，已切换为文本。</p>
      <SafeMarkdown
        content={this.props.block.fallback_markdown}
        citations={this.props.citations}
        onCitation={this.props.onCitation}
      />
    </div>
  }
}
