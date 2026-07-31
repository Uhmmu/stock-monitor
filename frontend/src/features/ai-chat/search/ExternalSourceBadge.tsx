export function ExternalSourceBadge({ sourceType }: { sourceType: string }) {
  const label = sourceType === 'deep_research' ? 'Deep Research 来源' : sourceType === 'web_search' ? '联网来源' : '站内来源'
  return <span className={`ai-source-origin ${sourceType}`}>{label}</span>
}
