export function RichBlockSkeleton({ blockType }: { blockType?: string }) {
  return <div className="ai-rich-block ai-rich-block-skeleton" role="status" aria-label={`${blockType || '内容'}正在整理`}>
    <i/><i/><i/>
  </div>
}
