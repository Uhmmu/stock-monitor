const jsonHeaders = { 'Content-Type': 'application/json' }

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options)
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(body.detail || '请求失败')
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

export const post = <T>(path: string, body: unknown) => api<T>(path, { method: 'POST', headers: jsonHeaders, body: JSON.stringify(body) })
export const patch = <T>(path: string, body: unknown) => api<T>(path, { method: 'PATCH', headers: jsonHeaders, body: JSON.stringify(body) })
