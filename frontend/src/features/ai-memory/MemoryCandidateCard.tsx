import { useMutation, useQueryClient } from '@tanstack/react-query'
import { confirmMemory, memoryKeys, rejectMemory } from './api'
import type { Memory } from './types'

export function MemoryCandidateCard({memory}:{memory:Memory}) {
  const client=useQueryClient()
  const refresh=()=>{void client.invalidateQueries({queryKey:memoryKeys.all});void client.invalidateQueries({queryKey:['ai-memory-candidates']})}
  const confirm=useMutation({mutationFn:()=>confirmMemory(memory.id),onSuccess:refresh})
  const reject=useMutation({mutationFn:()=>rejectMemory(memory.id),onSuccess:refresh})
  return <article className="ai-memory-candidate">
    <div><span>可能值得记住</span><small>{memory.memory_type.replaceAll('_',' ')} · {Math.round((memory.confidence||0)*100)}%</small></div>
    <p>{memory.content}</p>
    {memory.supersedes_memory_id&&<em>这可能会替代一条已有记忆，确认后旧记忆将归档。</em>}
    <footer><button onClick={()=>reject.mutate()} disabled={reject.isPending}>忽略</button><button className="primary" onClick={()=>confirm.mutate()} disabled={confirm.isPending}>{confirm.isPending?'保存中…':'确认记住'}</button></footer>
  </article>
}
