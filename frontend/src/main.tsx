import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { AboutPage } from './About'
import { appPath, isBetaDesignPath } from './appRoute'
import { RefreshProgressBar } from './RefreshProgressBar'
import { restoreQueryCache, setupQueryCacheAutoSave } from './queryPersistence'
import { initTheme } from './theme'
import './styles.css'
import './dark-theme.css'
import './apple-design.css'
import './beta-design.css'

initTheme()
// gcTime 与持久化 maxAge 对齐（7 天）：访问过的板块在会话内不淘汰，冷加载也能从 IndexedDB 恢复；
// staleTime 30s 只减少反复切换板块时的重复挂载请求，30s 轮询类查询不受影响。
const client = new QueryClient({ defaultOptions: { queries: { gcTime: 7 * 24 * 60 * 60 * 1000, staleTime: 30_000 } } })
const appleDesign = true
const betaDesign = isBetaDesignPath()
document.documentElement.dataset.interface = 'apple'
document.documentElement.dataset.beta = betaDesign ? 'true' : 'false'
const page = appPath().replace(/\/+$/, '') === '/about' ? <AboutPage /> : <App appleDesign={appleDesign} betaDesign={betaDesign} />
const root = createRoot(document.getElementById('root')!)
const render = () => root.render(<StrictMode><QueryClientProvider client={client}><RefreshProgressBar/>{page}</QueryClientProvider></StrictMode>)
// 先恢复上次缓存再渲染：冷加载直接显示旧数据，react-query 在挂载后自动后台刷新并切换为新数据。
restoreQueryCache(client).catch(() => {}).then(() => {
  setupQueryCacheAutoSave(client)
  render()
})
