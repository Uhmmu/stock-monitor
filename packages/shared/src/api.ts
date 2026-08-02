const BASE = '/api'
const TOKEN_KEY = 'auth_token'

export type AuthUser = { id?: number; username: string; role: string }
export type LoginResponse = AuthUser & { token: string }

export const getToken = () =>
  localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY) || ''

export function saveToken(token: string, remember: boolean) {
  clearToken()
  ;(remember ? localStorage : sessionStorage).setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(TOKEN_KEY)
}

export async function api<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((opts.headers as Record<string, string>) || {}),
  }
  if (token) headers.Authorization = `Bearer ${token}`
  const response = await fetch(BASE + path, { ...opts, headers })
  if (response.status === 401 && !path.startsWith('/admin/integrations/ibkr')) {
    clearToken()
    window.dispatchEvent(new Event('auth:logout'))
    throw new Error('Unauthorized')
  }
  if (!response.ok) {
    const message = await response.text()
    throw new Error(message || `Request failed (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const post = <T>(path: string, body: unknown) =>
  api<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const patch = <T>(path: string, body: unknown) =>
  api<T>(path, { method: 'PATCH', body: JSON.stringify(body) })

export const login = (username: string, password: string, remember: boolean) =>
  post<LoginResponse>('/auth/login', { username, password, remember })

export const register = (username: string, password: string) =>
  post<{ message: string }>('/auth/register', { username, password })
