import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { AboutPage } from './About'
import './styles.css'

const client = new QueryClient()
const page = window.location.pathname.replace(/\/+$/, '') === '/about' ? <AboutPage /> : <App />
createRoot(document.getElementById('root')!).render(<StrictMode><QueryClientProvider client={client}>{page}</QueryClientProvider></StrictMode>)
