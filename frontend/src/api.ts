const BASE = '/api'

export const getToken = () =>
  localStorage.getItem('auth_token') || sessionStorage.getItem('auth_token') || ''

export async function api<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json', ...(opts.headers as Record<string, string> || {}) }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(BASE + path, { ...opts, headers })
  if (res.status === 401) {
    localStorage.removeItem('auth_token')
    sessionStorage.removeItem('auth_token')
    window.dispatchEvent(new Event('auth:logout'))
    throw new Error('Unauthorized')
  }
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: 'POST', body: JSON.stringify(body) })
}

export async function patch<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
}
