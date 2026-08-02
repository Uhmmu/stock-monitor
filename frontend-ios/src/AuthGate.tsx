import { useState, type FormEvent } from 'react'
import { login, register, saveToken, type AuthUser } from '@shared/api'
import { PressButton } from './components'

export function AuthGate({ authenticated }: { authenticated: (user: AuthUser) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setMessage('')
    try {
      if (mode === 'login') {
        const result = await login(username, password, remember)
        saveToken(result.token, remember)
        authenticated(result)
      } else {
        const result = await register(username, password)
        setMessage(result.message); setMode('login')
      }
    } catch (error) {
      const raw = error instanceof Error ? error.message : '请求失败'
      try { setMessage(JSON.parse(raw).detail || raw) } catch { setMessage(raw) }
    } finally { setBusy(false) }
  }
  return <main className="auth-page"><div className="auth-ambient"/><section className="auth-panel glass"><div className="app-mark">↗</div><span>STOCK MONITOR</span><h1>把重要变化，<br/>留在手边。</h1><p>独立为 iPhone 设计的投资组合与市场雷达。</p><div className="auth-segment"><button className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')}>登录</button><button className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>注册</button></div><form onSubmit={submit}><label>用户名<input autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} required minLength={2}/></label><label>密码<input type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={event => setPassword(event.target.value)} required minLength={6}/></label>{mode === 'login' && <label className="remember"><input type="checkbox" checked={remember} onChange={event => setRemember(event.target.checked)}/><span>在这台设备上保持登录</span></label>}{message && <p className="auth-message" role="status">{message}</p>}<PressButton className="primary-button" disabled={busy}>{busy ? '请稍候…' : mode === 'login' ? '安全登录' : '提交注册申请'}</PressButton></form><small className="auth-footnote">与桌面端共用账户、数据和权限。</small></section></main>
}
