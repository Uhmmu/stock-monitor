import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { AboutPage } from './About'
import { initTheme } from './theme'
import './styles.css'
import './dark-theme.css'

initTheme()
const client = new QueryClient()
const page = window.location.pathname.replace(/\/+$/, '') === '/about' ? <AboutPage /> : <App />
createRoot(document.getElementById('root')!).render(<StrictMode><QueryClientProvider client={client}>{page}</QueryClientProvider></StrictMode>)
