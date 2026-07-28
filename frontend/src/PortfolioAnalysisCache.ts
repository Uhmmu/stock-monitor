import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export type AnalysisType = 'metrics' | 'stress_test' | 'scenario_analysis' | 'monte_carlo' | 'expected_return' | 'optimization'

export type PortfolioAnalysisRun<TResult = unknown> = {
  job_id: number
  analysis_type: AnalysisType | string
  status: string
  result: TResult | null
  input_request: Record<string, unknown>
  model_version: string
  created_at: string
  completed_at: string | null
  expires_at: string
  is_fresh: boolean
  error_message: string | null
}

export type PortfolioAnalysisHistory = {
  cache_days: number
  runs: PortfolioAnalysisRun[]
}

export function usePortfolioAnalysisHistory() {
  return useQuery({
    queryKey: ['portfolio-analysis-history'],
    queryFn: () => api<PortfolioAnalysisHistory>('/portfolio/analysis/history'),
    staleTime: 30_000,
  })
}

export function latestFreshAnalysis<TResult>(
  runs: PortfolioAnalysisRun[] | undefined,
  analysisType: AnalysisType,
  matches: (run: PortfolioAnalysisRun<TResult>) => boolean = () => true,
) {
  return runs?.find(run => run.analysis_type === analysisType && run.status === 'completed' && run.is_fresh && matches(run as PortfolioAnalysisRun<TResult>)) as PortfolioAnalysisRun<TResult> | undefined
}

function comparable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(comparable)
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).sort(([left], [right]) => left.localeCompare(right)).map(([key, item]) => [key, comparable(item)]))
  }
  return value
}

export function requestsMatch(saved: Record<string, unknown> | undefined, current: Record<string, unknown>) {
  if (!saved) return false
  const withoutControlFields = (source: Record<string, unknown>) => Object.fromEntries(Object.entries(source).filter(([key]) => !['portfolio_id', 'force_refresh'].includes(key)))
  return JSON.stringify(comparable(withoutControlFields(saved))) === JSON.stringify(comparable(withoutControlFields(current)))
}

export function cacheTimeLabel(run: PortfolioAnalysisRun | undefined) {
  if (!run) return ''
  const completed = new Date(run.completed_at || run.created_at).toLocaleString('zh-CN')
  const expires = new Date(run.expires_at).toLocaleDateString('zh-CN')
  return `已显示 ${completed} 的保存结果，有效至 ${expires}`
}
