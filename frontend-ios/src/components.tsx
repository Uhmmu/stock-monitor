import type { ButtonHTMLAttributes, PropsWithChildren, ReactNode } from 'react'
import { Icon } from './icons'

export function IOSPage({ children, className = '' }: PropsWithChildren<{ className?: string }>) {
  return <main className={`ios-page ${className}`}>{children}</main>
}

export function NavigationBar({ title, eyebrow, back, action }: { title: string; eyebrow?: string; back?: () => void; action?: ReactNode }) {
  return <><header className="navigation-bar glass"><div className="nav-side"/><div className="nav-title">{eyebrow && <span>{eyebrow}</span>}<strong>{title}</strong></div><div className="nav-side end">{action}</div></header>{back && <button className="floating-back-button glass" onClick={back} aria-label="返回上一页" title="返回上一页"><Icon name="back"/></button>}</>
}

export function SectionHeader({ title, caption, action }: { title: string; caption?: string; action?: ReactNode }) {
  return <div className="section-header"><div><h2>{title}</h2>{caption && <p>{caption}</p>}</div>{action}</div>
}

export function GlassCard({ children, className = '' }: PropsWithChildren<{ className?: string }>) {
  return <section className={`glass-card ${className}`}>{children}</section>
}

export function InsetList({ children, label }: PropsWithChildren<{ label?: string }>) {
  return <section className="inset-section">{label && <h2>{label}</h2>}<div className="inset-list">{children}</div></section>
}

export function ListRow({ title, subtitle, value, icon, onClick, children }: { title: string; subtitle?: string; value?: ReactNode; icon?: ReactNode; onClick?: () => void; children?: ReactNode }) {
  const content = <>{icon && <span className="row-icon">{icon}</span>}<span className="row-copy"><strong>{title}</strong>{subtitle && <small>{subtitle}</small>}{children}</span>{value && <span className="row-value">{value}</span>}{onClick && <Icon name="chevron" size={18}/>}</>
  return onClick ? <button className="list-row" onClick={onClick}>{content}</button> : <div className="list-row">{content}</div>
}

export function StatusPill({ children, tone = 'neutral' }: PropsWithChildren<{ tone?: 'positive' | 'negative' | 'warning' | 'neutral' }>) {
  return <span className={`status-pill ${tone}`}>{children}</span>
}

export function LoadingState({ rows = 3 }: { rows?: number }) {
  return <div className="loading-state" aria-label="正在加载">{Array.from({ length: rows }, (_, index) => <i key={index}/>)}</div>
}

export function StateView({ title, message, retry }: { title: string; message: string; retry?: () => void }) {
  return <div className="state-view"><span>⌁</span><h2>{title}</h2><p>{message}</p>{retry && <button onClick={retry}>重新加载</button>}</div>
}

export function PressButton({ className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={`press-button ${className}`} {...props}/>
}
