import type { ReactNode } from 'react'

const paths: Record<string, ReactNode> = {
  overview: <><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><path d="M14 18h7M17.5 14.5v7"/></>,
  portfolio: <><rect x="3" y="6" width="18" height="14" rx="3"/><path d="M8 6V4h8v2M3 11h18M9 15h6"/></>,
  activity: <><path d="M4 17l4-5 4 3 7-9"/><path d="M15 6h4v4"/><path d="M4 21h16"/></>,
  discovery: <><circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2.3 5-4.7 2 2.2-4.8z"/></>,
  chat: <><path d="M4 4h16v13H9l-5 4V4z"/><path d="M8 9h8M8 13h5"/></>,
  fundamentals: <><path d="M4 19V9M10 19V5M16 19v-7M22 19H2"/><path d="m4 8 6-4 6 6 5-5"/></>,
  more: <><circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/></>,
  bell: <><path d="M18 8a6 6 0 0 0-12 0c0 6-3 7-3 9h18c0-2-3-3-3-9"/><path d="M10 21h4"/></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18"/></>,
  news: <><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 8h10M7 12h7M7 16h5"/></>,
  chevron: <path d="m9 18 6-6-6-6"/>, back: <path d="m15 18-6-6 6-6"/>,
}

export function Icon({ name, size = 24 }: { name: string; size?: number }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>
}
