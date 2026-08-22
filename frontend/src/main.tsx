import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { AboutPage } from './About'
import { isAppleDesignPath } from './appRoute'
import { initTheme } from './theme'
import './styles.css'
import './dark-theme.css'
import './apple-design.css'

initTheme()
const client = new QueryClient()
const appleDesign = isAppleDesignPath()
if (appleDesign) document.documentElement.dataset.interface = 'apple'
else delete document.documentElement.dataset.interface
const page = window.location.pathname.replace(/\/+$/, '') === '/about' ? <AboutPage /> : <App appleDesign={appleDesign} />
createRoot(document.getElementById('root')!).render(<StrictMode><QueryClientProvider client={client}>{page}</QueryClientProvider></StrictMode>)
