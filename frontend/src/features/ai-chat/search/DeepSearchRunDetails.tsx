import type { DeepSearchRun } from './types'
import { DeepSearchProgress } from './DeepSearchProgress'

export function DeepSearchRunDetails({ run }: { run: DeepSearchRun }) {
  return <details className="ai-deep-run-details" open={run.status !== 'completed'}>
    <summary>Deep Search 运行详情</summary>
    <DeepSearchProgress run={run}/>
    <p>联网研究结果属于不可信外部证据，最终回答仍由当前主模型结合站内数据整理。</p>
    {run.status === 'completed' && run.text && <section className="ai-deep-recovered-output"><h4>Exa 研究原文</h4><p>{run.text}</p></section>}
    {run.sources.length > 0 && <section className="ai-deep-source-list"><h4>公开来源</h4><ol>{run.sources.map(source => <li key={source.source_id}><a href={source.url} target="_blank" rel="noreferrer noopener">{source.title || source.domain}</a><small>{source.domain} · {source.authority_tier}</small></li>)}</ol></section>}
  </details>
}
