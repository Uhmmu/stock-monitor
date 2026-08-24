import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { AboutPage } from './About'
import { appPath, isBetaDesignPath } from './appRoute'
import { initTheme } from './theme'
import './styles.css'
import './dark-theme.css'
import './apple-design.css'
import './beta-design.css'

initTheme()
const client = new QueryClient()
const appleDesign = true
const betaDesign = isBetaDesignPath()
document.documentElement.dataset.interface = 'apple'
document.documentElement.dataset.beta = betaDesign ? 'true' : 'false'
const page = appPath().replace(/\/+$/, '') === '/about' ? <AboutPage /> : <App appleDesign={appleDesign} betaDesign={betaDesign} />
createRoot(document.getElementById('root')!).render(<StrictMode><QueryClientProvider client={client}>{page}</QueryClientProvider></StrictMode>)
