import { useMutation, useQueryClient } from '@tanstack/react-query'
import { confirmDecision, memoryKeys, transitionDecision } from './api'
import type { InvestmentDecision, Memory } from './types'
import { MemoryCandidateCard } from './MemoryCandidateCard'

export function ChatMemorySuggestions({memories,decisions}:{memories:Memory[];decisions:InvestmentDecision[]}) {
  const client=useQueryClient()
  const refresh=()=>{void client.invalidateQueries({queryKey:memoryKeys.decisions});void client.invalidateQueries({queryKey:['ai-chat-decision-drafts']})}
  const confirm=useMutation({mutationFn:(id:number)=>confirmDecision(id),onSuccess:refresh})
  const cancel=useMutation({mutationFn:(id:number)=>transitionDecision(id,'cancel'),onSuccess:refresh})
  if(!memories.length&&!decisions.length)return null
  return <aside className="ai-chat-suggestions">
    {memories.slice(0,3).map(memory=><MemoryCandidateCard key={memory.id} memory={memory}/>)}
    {decisions.slice(0,2).map(item=><article className="ai-decision-candidate" key={item.id}>
      <div><span>投资决策草稿</span><small>{item.decision_type} · {item.symbols.join(' / ')||'未指定代码'}</small></div>
      <h3>{item.title}</h3><p>{item.action}</p>
      <dl><div><dt>逻辑</dt><dd>{item.thesis.join('；')||'待补充'}</dd></div><div><dt>失效条件</dt><dd>{item.invalidation_conditions.join('；')||'待补充'}</dd></div></dl>
      <footer><button onClick={()=>cancel.mutate(item.id)}>取消草稿</button><button className="primary" onClick={()=>confirm.mutate(item.id)}>保存为正式决策</button></footer>
    </article>)}
  </aside>
}
