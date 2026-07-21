import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from './api'

export type SecuritySearchResult = {
  provider_key:string
  security_id:number|null
  display_symbol:string
  display_name:string
  local_symbol:string|null
  exchange:string|null
  exchange_code:string|null
  market:string|null
  country_code:string|null
  currency:string|null
  instrument_type:string|null
  yahoo_symbol:string|null
  finnhub_symbol:string|null
  source:'local'|'yahoo'|'finnhub'
  is_local:boolean
}

type Props = {
  value:SecuritySearchResult|null
  onSelect:(security:SecuritySearchResult|null)=>void
  placeholder?:string
  label?:string
  excludeSymbols?:string[]
  disabledSymbols?:string[]
  autoFocus?:boolean
  compact?:boolean
}

const typeNames:Record<string,string> = {
  EQUITY:'股票', ETF:'ETF', ADR:'ADR', INDEX:'指数', MUTUALFUND:'基金', CRYPTOCURRENCY:'加密货币',
  FUTURE:'期货', OPTION:'期权', WARRANT:'权证',
}

export function securityPayload(security:SecuritySearchResult) {
  return {
    security_id:security.security_id,
    source:security.source === 'local' ? undefined : security.source,
    yahoo_symbol:security.yahoo_symbol,
    finnhub_symbol:security.finnhub_symbol,
  }
}

export function SecuritySearchAutocomplete({value,onSelect,placeholder='搜索股票代码或公司名称',label,excludeSymbols=[],disabledSymbols=[],autoFocus,compact}:Props) {
  const [query,setQuery] = useState(value?.display_symbol||'')
  const [results,setResults] = useState<SecuritySearchResult[]>([])
  const [loading,setLoading] = useState(false)
  const [error,setError] = useState(false)
  const [open,setOpen] = useState(false)
  const [activeIndex,setActiveIndex] = useState(-1)
  const rootRef = useRef<HTMLDivElement>(null)
  const fieldRef = useRef<HTMLDivElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const requestRef = useRef(0)
  const listId = useId()
  const [popoverStyle,setPopoverStyle] = useState<React.CSSProperties>({})

  const positionPopover=useCallback(()=>{
    const field=fieldRef.current
    if(!field) return
    const rect=field.getBoundingClientRect()
    const gutter=12
    const width=Math.min(400,Math.max(280,rect.width),window.innerWidth-gutter*2)
    const left=Math.min(Math.max(gutter,rect.left),window.innerWidth-width-gutter)
    const below=window.innerHeight-rect.bottom-gutter
    const above=rect.top-gutter
    const useAbove=below<210&&above>below
    const maxHeight=Math.min(332,Math.max(160,(useAbove?above:below)-8))
    const visibleHeight=Math.min(popoverRef.current?.scrollHeight||maxHeight,maxHeight)
    setPopoverStyle({left,width,maxHeight,top:useAbove?Math.max(gutter,rect.top-visibleHeight-8):rect.bottom+8})
  },[])

  useEffect(()=>{ if(value) setQuery(value.display_symbol); else if(!open) setQuery('') },[value,open])
  useEffect(()=>{
    const close = (event:PointerEvent) => {
      const target=event.target as Node
      if(!rootRef.current?.contains(target)&&!popoverRef.current?.contains(target)) setOpen(false)
    }
    document.addEventListener('pointerdown',close)
    return ()=>document.removeEventListener('pointerdown',close)
  },[])
  useLayoutEffect(()=>{
    if(!open) return
    positionPopover()
    window.addEventListener('resize',positionPopover)
    window.addEventListener('scroll',positionPopover,true)
    return ()=>{window.removeEventListener('resize',positionPopover);window.removeEventListener('scroll',positionPopover,true)}
  },[open,loading,error,results.length,positionPopover])
  useEffect(()=>{
    const trimmed=query.trim()
    if(value?.display_symbol===trimmed) return
    if(!trimmed) {setResults([]);setLoading(false);setError(false);setOpen(false);return}
    const controller = new AbortController()
    const request=++requestRef.current
    setLoading(true);setError(false);setOpen(true)
    const timer=window.setTimeout(async()=>{
      try {
        const data=await api<{query:string;results:SecuritySearchResult[]}>(`/securities/search?q=${encodeURIComponent(trimmed)}&limit=8`,{signal:controller.signal})
        if(request!==requestRef.current) return
        const excluded=new Set(excludeSymbols.map(item=>item.toUpperCase()))
        const filtered=data.results.filter(item=>!excluded.has(item.display_symbol.toUpperCase()))
        setResults(filtered)
        setActiveIndex(filtered.length?0:-1)
      } catch(err) {
        if((err as Error).name!=='AbortError'&&request===requestRef.current){setResults([]);setError(true)}
      } finally {if(request===requestRef.current)setLoading(false)}
    },300)
    return ()=>{window.clearTimeout(timer);controller.abort()}
  },[query,value,excludeSymbols.join('|')])

  const choose=(item:SecuritySearchResult)=>{
    if(disabledSymbols.some(symbol=>symbol.toUpperCase()===item.display_symbol.toUpperCase())) return
    setQuery(item.display_symbol);setOpen(false);setActiveIndex(-1);onSelect(item)
  }
  const change=(text:string)=>{
    setQuery(text)
    if(value) onSelect(null)
    setOpen(Boolean(text.trim()))
  }
  const keyDown=(event:React.KeyboardEvent<HTMLInputElement>)=>{
    if(event.key==='ArrowDown'){event.preventDefault();setOpen(true);setActiveIndex(index=>Math.min(results.length-1,index+1))}
    else if(event.key==='ArrowUp'){event.preventDefault();setActiveIndex(index=>Math.max(0,index-1))}
    else if(event.key==='Enter'&&open&&activeIndex>=0){event.preventDefault();choose(results[activeIndex])}
    else if(event.key==='Escape'){event.preventDefault();setOpen(false)}
  }
  const countryFlag=(code:string|null)=>code&&/^[A-Z]{2}$/.test(code)?String.fromCodePoint(...[...code].map(char=>127397+char.charCodeAt(0))):''
  return <div className={`security-search${compact?' compact':''}`} ref={rootRef}>
    {label&&<label htmlFor={`${listId}-input`}>{label}</label>}
    <div ref={fieldRef} className={`security-search-field${open?' is-open':''}${value?' has-selection':''}`}>
      <span className="security-search-icon" aria-hidden="true"/>
      <input id={`${listId}-input`} value={query} onChange={event=>change(event.target.value)} onFocus={()=>query.trim()&&setOpen(true)}
        onKeyDown={keyDown} placeholder={placeholder} autoComplete="off" autoFocus={autoFocus}
        role="combobox" aria-autocomplete="list" aria-expanded={open} aria-controls={listId}
        aria-activedescendant={activeIndex>=0?`${listId}-${activeIndex}`:undefined}/>
      {loading&&<span className="security-search-spinner" aria-label="正在搜索"/>}
      {!loading&&query&&<button type="button" className="security-search-clear" aria-label="清空证券" onClick={()=>{setQuery('');setResults([]);setOpen(false);onSelect(null)}}>×</button>}
    </div>
    {open&&createPortal(<div ref={popoverRef} className={`security-search-popover${compact?' compact':''}`} style={popoverStyle} id={listId} role="listbox">
      {loading&&<div className="security-search-state"><span className="security-search-skeleton"/><span>正在查找证券…</span></div>}
      {!loading&&error&&<div className="security-search-state error-state"><b>暂时无法连接搜索服务</b><span>请稍后重试</span></div>}
      {!loading&&!error&&!results.length&&<div className="security-search-state"><b>没有找到匹配证券</b><span>试试完整代码或公司名称</span></div>}
      {!loading&&!error&&results.map((item,index)=>{const disabled=disabledSymbols.some(symbol=>symbol.toUpperCase()===item.display_symbol.toUpperCase());const status=disabled?'已添加':item.is_local?'已入库':null;return <button
        type="button" role="option" aria-selected={index===activeIndex} aria-disabled={disabled} id={`${listId}-${index}`}
        className={`security-search-option${index===activeIndex?' active':''}`} key={item.provider_key}
        onPointerMove={()=>setActiveIndex(index)} onClick={()=>choose(item)} disabled={disabled}>
        <span className="security-option-main"><span className="security-option-heading"><b>{item.display_symbol}</b>{status&&<em className={disabled?'is-disabled':'is-local'}>{status}</em>}</span><strong>{item.display_name}</strong></span>
        <span className="security-option-meta">{[item.exchange,item.country_code&&`${countryFlag(item.country_code)} ${item.country_code}`,typeNames[item.instrument_type||'']||item.instrument_type,item.currency].filter(Boolean).join(' · ')||'证券资料待验证'}</span>
      </button>})}
    </div>,document.body)}
  </div>
}
