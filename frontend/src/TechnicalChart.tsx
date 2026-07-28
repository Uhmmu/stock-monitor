import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  type CandlestickData,
  type Coordinate,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type MouseEventParams,
  type Time,
} from 'lightweight-charts'
import { api, getToken, post } from './api'

export type WeeklyCandle = {
  time:string
  open:number
  high:number
  low:number
  close:number
  volume:number
}

export type TechnicalMovingAverages = {
  ma20:{time:string;value:number}[]
  ma50:{time:string;value:number}[]
}

export type TechnicalTimeframe = 'day'|'week'|'month'
export type TechnicalChartSeries = Record<TechnicalTimeframe,{
  candles:WeeklyCandle[]
  moving_averages:TechnicalMovingAverages
}>
export type TechnicalChartEvent = {
  id:string
  time:string
  type:'earnings'|'sec'|'insider'|'congress'
  label:string
  title:string
  href:string
}
export type TechnicalPriceAlert = {
  id:number
  ticker:string
  target_price:number
  direction:'above'|'below'
  enabled:boolean
  triggered_at:string|null
  created_at:string
}
export type ChartHeatZone = {
  lower:number
  upper:number
  role:'support'|'resistance'|'neutral'
  normalizedIntensity:number
}
export type ChartTrendLine = {
  type:string
  anchors?:{date:string;price:number}[]
}

type PreparedChartData = {
  candles:CandlestickData<Time>[]
  volume:HistogramData<Time>[]
  ma20:LineData<Time>[]
  ma50:LineData<Time>[]
}
type ChartPoint = {time:string;price:number}
type Drawing = {
  id:string
  timeframe:TechnicalTimeframe
  type:'trend'|'rectangle'|'fibonacci'|'gann'
  points:[ChartPoint,ChartPoint]
}
type DrawingTool = Drawing['type']|'alert'|null
type Dimensions = {width:number;height:number}

const BUSINESS_DAY = /^\d{4}-\d{2}-\d{2}$/
const finite = (value:number) => Number.isFinite(value)
const FIBONACCI_LEVELS = [0,.236,.382,.5,.618,.786,1] as const
const EMPTY_MA:TechnicalMovingAverages={ma20:[],ma50:[]}
const EVENT_COLORS:Record<TechnicalChartEvent['type'],string>={
  earnings:'#d9a7ff',
  sec:'#75a7ff',
  insider:'#53c7a2',
  congress:'#e7bd68',
}

export function prepareTechnicalChartData(
  weekly:WeeklyCandle[],
  movingAverages:TechnicalMovingAverages,
):PreparedChartData {
  const deduplicated=new Map<string,WeeklyCandle>()
  weekly.forEach(row=>{
    if(
      BUSINESS_DAY.test(row.time)
      && [row.open,row.high,row.low,row.close,row.volume].every(finite)
      && row.volume>=0
      && row.high>=Math.max(row.open,row.close)
      && row.low<=Math.min(row.open,row.close)
    ) deduplicated.set(row.time,row)
  })
  const valid=[...deduplicated.values()].sort((a,b)=>a.time.localeCompare(b.time))
  const allowedTimes = new Set(valid.map(row=>row.time))
  const line = (rows:{time:string;value:number}[]):LineData<Time>[] => rows
    .filter(row=>allowedTimes.has(row.time)&&finite(row.value))
    .sort((a,b)=>a.time.localeCompare(b.time))
    .map(row=>({time:row.time,value:row.value}))

  return {
    candles:valid.map(({time,open,high,low,close})=>({time,open,high,low,close})),
    volume:valid.map(row=>({
      time:row.time,
      value:row.volume,
      color:row.close>=row.open?'rgba(83,199,162,.42)':'rgba(239,113,134,.42)',
    })),
    ma20:line(movingAverages.ma20),
    ma50:line(movingAverages.ma50),
  }
}

export function fibonacciPrices(start:number,end:number) {
  return FIBONACCI_LEVELS.map(level=>({
    level,
    price:start+(end-start)*level,
  }))
}

export function buildVolumeProfile(candles:WeeklyCandle[],binCount=24) {
  if(!candles.length||binCount<1) return []
  const low=Math.min(...candles.map(row=>row.low))
  const high=Math.max(...candles.map(row=>row.high))
  if(!finite(low)||!finite(high)||high<=low) return []
  const step=(high-low)/binCount
  const bins=Array.from({length:binCount},(_,index)=>({
    lower:low+index*step,
    upper:low+(index+1)*step,
    volume:0,
  }))
  candles.forEach(row=>{
    const typical=(row.high+row.low+row.close)/3
    const index=Math.min(binCount-1,Math.max(0,Math.floor((typical-low)/step)))
    bins[index].volume+=row.volume
  })
  return bins
}

const fmt = (value:number|undefined) => value==null?'—':value.toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})
const volumeFmt = (value:number|undefined) => value==null?'—':new Intl.NumberFormat('zh-CN',{notation:'compact',maximumFractionDigits:1}).format(value)
const timeString=(time:Time):string=>typeof time==='string'
  ? time
  : typeof time==='number'
    ? new Date(time*1000).toISOString().slice(0,10)
    : `${time.year}-${String(time.month).padStart(2,'0')}-${String(time.day).padStart(2,'0')}`
const drawingKey=(symbol:string)=>`technical-chart-drawings:${symbol}`
const loadDrawings=(symbol:string):Drawing[]=>{
  try{
    const parsed=JSON.parse(localStorage.getItem(drawingKey(symbol))||'[]')
    return Array.isArray(parsed)?parsed.filter(item=>item&&['trend','rectangle','fibonacci','gann'].includes(item.type)&&Array.isArray(item.points)): []
  }catch{return []}
}
const nearestSeriesTime=(requested:string,candles:WeeklyCandle[])=>{
  if(!candles.length) return requested
  const target=new Date(`${requested}T00:00:00Z`).getTime()
  const first=new Date(`${candles[0].time}T00:00:00Z`).getTime()
  const last=new Date(`${candles.at(-1)!.time}T00:00:00Z`).getTime()
  if(target<first||target>last) return requested
  return candles.reduce((best,row)=>{
    const distance=Math.abs(new Date(`${row.time}T00:00:00Z`).getTime()-target)
    return distance<best.distance?{time:row.time,distance}:best
  },{time:candles[0].time,distance:Number.POSITIVE_INFINITY}).time
}

function StaticChartLink({url,symbol,visible=false}:{url:string;symbol:string;visible?:boolean}) {
  const [src,setSrc] = useState<string|null>(null)
  const [failed,setFailed] = useState(false)
  useEffect(()=>{
    let active=true
    let objectUrl=''
    setSrc(null)
    setFailed(false)
    fetch(url,{headers:{Authorization:`Bearer ${getToken()}`}})
      .then(response=>{if(!response.ok) throw new Error('chart unavailable');return response.blob()})
      .then(blob=>{
        if(!active) return
        objectUrl=URL.createObjectURL(blob)
        setSrc(objectUrl)
      })
      .catch(()=>active&&setFailed(true))
    return ()=>{
      active=false
      if(objectUrl) URL.revokeObjectURL(objectUrl)
    }
  },[url])

  if(!src) return visible
    ? <div className="technical-chart-empty">{failed?'动态图表不可用，静态缓存也暂无法读取。':'正在读取静态图缓存…'}</div>
    : null
  return visible
    ? <a href={src} target="_blank" rel="noreferrer"><img className="technical-chart" src={src} alt={`${symbol} 周线静态技术分析图`}/></a>
    : <a className="technical-static-link" href={src} target="_blank" rel="noreferrer">静态图 ↗</a>
}

function LayerButton({active,onClick,children}:{active:boolean;onClick:()=>void;children:string}) {
  return <button type="button" className={active?'active':''} aria-pressed={active} onClick={onClick}>{children}</button>
}

export function TechnicalChart({
  symbol,
  series,
  staticChartUrl,
  heatZones=[],
  fibonacci,
  trendLines=[],
  events=[],
  portfolioCost=null,
  initialPriceAlerts=[],
}:{
  symbol:string
  series:TechnicalChartSeries
  staticChartUrl?:string|null
  heatZones?:ChartHeatZone[]
  fibonacci?:{available:boolean;levels?:Record<string,number>}
  trendLines?:ChartTrendLine[]
  events?:TechnicalChartEvent[]
  portfolioCost?:{average_cost:number;quantity:number;currency:string}|null
  initialPriceAlerts?:TechnicalPriceAlert[]
}) {
  const hostRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const legendRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi|null>(null)
  const candleRef = useRef<ISeriesApi<'Candlestick'>|null>(null)
  const dragStart = useRef<ChartPoint|null>(null)
  const [timeframe,setTimeframe]=useState<TechnicalTimeframe>('week')
  const [failed,setFailed] = useState(false)
  const [dimensions,setDimensions]=useState<Dimensions>({width:0,height:0})
  const [layers,setLayers]=useState({
    heatmap:true,ma:true,fibonacci:true,trend:true,events:true,volumeProfile:false,cost:true,
  })
  const [tool,setTool]=useState<DrawingTool>(null)
  const [drawings,setDrawings]=useState<Drawing[]>(()=>loadDrawings(symbol))
  const [preview,setPreview]=useState<{type:Exclude<DrawingTool,null|'alert'>;points:[ChartPoint,ChartPoint]}|null>(null)
  const [pendingAlert,setPendingAlert]=useState<{price:number;direction:'above'|'below'}|null>(null)
  const [priceAlerts,setPriceAlerts]=useState(initialPriceAlerts)
  const [alertStatus,setAlertStatus]=useState('')
  const selected=series[timeframe]||{candles:[],moving_averages:EMPTY_MA}
  const data = useMemo(()=>prepareTechnicalChartData(selected.candles,selected.moving_averages),[selected])
  const volumeProfile=useMemo(()=>buildVolumeProfile(selected.candles),[selected.candles])

  useEffect(()=>setPriceAlerts(initialPriceAlerts),[initialPriceAlerts])
  useEffect(()=>localStorage.setItem(drawingKey(symbol),JSON.stringify(drawings)),[drawings,symbol])

  useEffect(()=>{
    const host=hostRef.current
    if(!host||!data.candles.length) return
    setFailed(false)
    let chart:IChartApi|null=null
    try{
      const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)').matches
      const chartHeight=host.clientWidth<640?420:520
      chart=createChart(host,{
        width:host.clientWidth,
        height:chartHeight,
        layout:{
          background:{type:ColorType.Solid,color:'#10131d'},
          textColor:'#8990a7',
          fontFamily:"-apple-system,BlinkMacSystemFont,'SF Pro Text','Noto Sans SC',sans-serif",
          panes:{separatorColor:'rgba(137,144,167,.14)',separatorHoverColor:'rgba(117,167,255,.35)',enableResize:true},
        },
        grid:{vertLines:{color:'rgba(137,144,167,.07)'},horzLines:{color:'rgba(137,144,167,.07)'}},
        crosshair:{
          mode:CrosshairMode.Normal,
          vertLine:{color:'rgba(232,233,242,.35)',labelBackgroundColor:'#323848'},
          horzLine:{color:'rgba(232,233,242,.25)',labelBackgroundColor:'#323848'},
        },
        rightPriceScale:{borderColor:'rgba(137,144,167,.16)',scaleMargins:{top:.12,bottom:.08}},
        timeScale:{borderColor:'rgba(137,144,167,.16)',rightOffset:3,barSpacing:timeframe==='day'?6:timeframe==='week'?7:9,minBarSpacing:3,timeVisible:false},
        handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false},
        handleScale:{axisPressedMouseMove:true,mouseWheel:true,pinch:true},
        kineticScroll:{mouse:!reducedMotion,touch:!reducedMotion},
        localization:{locale:'zh-CN'},
      })
      chartRef.current=chart
      const candles=chart.addSeries(CandlestickSeries,{
        upColor:'#53c7a2',downColor:'#ef7186',borderVisible:false,
        wickUpColor:'#53c7a2',wickDownColor:'#ef7186',
        priceLineVisible:true,priceLineColor:'rgba(243,244,250,.42)',
      })
      candleRef.current=candles
      const ma20=chart.addSeries(LineSeries,{color:'#d9a7ff',lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false,visible:layers.ma})
      const ma50=chart.addSeries(LineSeries,{color:'#75a7ff',lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false,visible:layers.ma})
      const volume=chart.addSeries(HistogramSeries,{priceFormat:{type:'volume'},priceLineVisible:false,lastValueVisible:false},1)
      candles.setData(data.candles)
      ma20.setData(data.ma20)
      ma50.setData(data.ma50)
      volume.setData(data.volume)
      chart.panes()[1]?.setHeight(112)
      chart.timeScale().fitContent()

      const updateDimensions=()=>{
        const priceHeight=chart?.panes()[0]?.getHeight()||chartHeight-112
        setDimensions({width:stageRef.current?.clientWidth||host.clientWidth,height:priceHeight})
      }
      const showValues=(
        candle=data.candles.at(-1),
        volumePoint=data.volume.at(-1),
        ma20Point=data.ma20.at(-1),
        ma50Point=data.ma50.at(-1),
      )=>{
        const legend=legendRef.current
        if(!legend||!candle||!('open' in candle)) return
        const node=(tag:'b'|'span'|'i',text:string,className='')=>{
          const element=document.createElement(tag)
          element.textContent=text
          if(className) element.className=className
          return element
        }
        legend.replaceChildren(
          node('b',symbol),node('span',timeString(candle.time)),
          node('span',`开 ${fmt(candle.open)}`),node('span',`高 ${fmt(candle.high)}`),
          node('span',`低 ${fmt(candle.low)}`),node('span',`收 ${fmt(candle.close)}`),
          node('span',`量 ${volumeFmt(volumePoint?.value)}`),
          node('i',`MA20 ${fmt(ma20Point?.value)}`,'ma20'),
          node('i',`MA50 ${fmt(ma50Point?.value)}`,'ma50'),
        )
      }
      const crosshairHandler=(param:MouseEventParams<Time>)=>{
        const candlePoint=param.seriesData.get(candles)
        if(!candlePoint||!('open' in candlePoint)){showValues();return}
        const volumePoint=param.seriesData.get(volume)
        const ma20Point=param.seriesData.get(ma20)
        const ma50Point=param.seriesData.get(ma50)
        showValues(
          candlePoint,
          volumePoint&&'value' in volumePoint?volumePoint:undefined,
          ma20Point&&'value' in ma20Point?ma20Point:undefined,
          ma50Point&&'value' in ma50Point?ma50Point:undefined,
        )
      }
      showValues()
      chart.subscribeCrosshairMove(crosshairHandler)
      chart.timeScale().subscribeVisibleTimeRangeChange(updateDimensions)
      const observer=new ResizeObserver(entries=>{
        const width=entries[0]?.contentRect.width
        if(width){chart?.applyOptions({width});requestAnimationFrame(updateDimensions)}
      })
      observer.observe(host)
      requestAnimationFrame(updateDimensions)
      return ()=>{
        observer.disconnect()
        chart?.timeScale().unsubscribeVisibleTimeRangeChange(updateDimensions)
        chart?.unsubscribeCrosshairMove(crosshairHandler)
        chart?.remove()
        chartRef.current=null
        candleRef.current=null
      }
    }catch{
      chart?.remove()
      chartRef.current=null
      candleRef.current=null
      setFailed(true)
    }
  },[data,layers.ma,symbol,timeframe])

  const toChartPoint=(clientX:number,clientY:number):ChartPoint|null=>{
    const stage=stageRef.current
    const chart=chartRef.current
    const candles=candleRef.current
    if(!stage||!chart||!candles) return null
    const box=stage.getBoundingClientRect()
    const x=Math.max(0,Math.min(dimensions.width,clientX-box.left))
    const y=Math.max(0,Math.min(dimensions.height,clientY-box.top))
    const time=chart.timeScale().coordinateToTime(x as Coordinate)
    const price=candles.coordinateToPrice(y as Coordinate)
    return time!=null&&price!=null?{time:timeString(time),price}:null
  }
  const toCoordinates=(point:ChartPoint)=>{
    const chart=chartRef.current
    const candles=candleRef.current
    if(!chart||!candles) return null
    const x=chart.timeScale().timeToCoordinate(point.time)
    const y=candles.priceToCoordinate(point.price)
    return x==null||y==null?null:{x:Number(x),y:Number(y)}
  }
  const priceY=(price:number)=>{
    const value=candleRef.current?.priceToCoordinate(price)
    return value==null?null:Number(value)
  }
  const timeX=(time:string)=>{
    const nearest=nearestSeriesTime(time,selected.candles)
    const value=chartRef.current?.timeScale().timeToCoordinate(nearest)
    return value==null?null:Number(value)
  }
  const chooseTool=(next:DrawingTool)=>{
    setTool(current=>current===next?null:next)
    setPreview(null)
  }
  const onDrawStart=(event:React.PointerEvent<SVGSVGElement>)=>{
    if(!tool) return
    const point=toChartPoint(event.clientX,event.clientY)
    if(!point) return
    event.currentTarget.setPointerCapture(event.pointerId)
    dragStart.current=point
    if(tool!=='alert') setPreview({type:tool,points:[point,point]})
  }
  const onDrawMove=(event:React.PointerEvent<SVGSVGElement>)=>{
    if(!tool||tool==='alert'||!dragStart.current) return
    const point=toChartPoint(event.clientX,event.clientY)
    if(point) setPreview({type:tool,points:[dragStart.current,point]})
  }
  const onDrawEnd=(event:React.PointerEvent<SVGSVGElement>)=>{
    if(!tool||!dragStart.current) return
    const point=toChartPoint(event.clientX,event.clientY)||dragStart.current
    const start=dragStart.current
    dragStart.current=null
    if(tool==='alert'){
      const latest=selected.candles.at(-1)?.close||point.price
      setPendingAlert({price:Number(point.price.toFixed(4)),direction:point.price>=latest?'above':'below'})
    }else{
      setDrawings(current=>[...current,{
        id:`${tool}-${Date.now()}`,
        timeframe,
        type:tool,
        points:[start,point],
      }])
    }
    setPreview(null)
    setTool(null)
  }
  const saveAlert=async(event:FormEvent)=>{
    event.preventDefault()
    if(!pendingAlert) return
    setAlertStatus('saving')
    try{
      const saved=await post<TechnicalPriceAlert>(`/technical-analysis/${symbol}/price-alerts`,{
        target_price:pendingAlert.price,
        direction:pendingAlert.direction,
      })
      setPriceAlerts(current=>[saved,...current.filter(item=>item.id!==saved.id)])
      setPendingAlert(null)
      setAlertStatus('saved')
    }catch{setAlertStatus('error')}
  }
  const removeAlert=async(id:number)=>{
    try{
      await api<void>(`/technical-analysis/${symbol}/price-alerts/${id}`,{method:'DELETE'})
      setPriceAlerts(current=>current.filter(item=>item.id!==id))
    }catch{setAlertStatus('error')}
  }

  const visibleDrawings=drawings.filter(item=>item.timeframe===timeframe)
  const renderDrawing=(drawing:Pick<Drawing,'id'|'type'|'points'>,previewing=false)=>{
    const a=toCoordinates(drawing.points[0])
    const b=toCoordinates(drawing.points[1])
    if(!a||!b) return null
    const dash=previewing?'5 5':undefined
    if(drawing.type==='trend') return <line key={drawing.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="drawing-trend" strokeDasharray={dash}/>
    if(drawing.type==='rectangle') return <rect key={drawing.id} x={Math.min(a.x,b.x)} y={Math.min(a.y,b.y)} width={Math.max(1,Math.abs(b.x-a.x))} height={Math.max(1,Math.abs(b.y-a.y))} className="drawing-rectangle" strokeDasharray={dash}/>
    if(drawing.type==='fibonacci') return <g key={drawing.id} className="drawing-fibonacci">{fibonacciPrices(drawing.points[0].price,drawing.points[1].price).map(item=>{
      const y=priceY(item.price)
      return y==null?null:<g key={item.level}><line x1={Math.min(a.x,b.x)} x2={Math.max(a.x,b.x)} y1={y} y2={y} strokeDasharray={dash}/><text x={Math.max(a.x,b.x)+4} y={y-3}>{item.level} · {fmt(item.price)}</text></g>
    })}</g>
    const deltaX=b.x-a.x||1
    const deltaY=b.y-a.y
    return <g key={drawing.id} className="drawing-gann">{[.5,1,2].map(ratio=>{
      const endX=dimensions.width
      const endY=a.y+(endX-a.x)*(deltaY/deltaX)*ratio
      return <g key={ratio}><line x1={a.x} y1={a.y} x2={endX} y2={endY} strokeDasharray={dash}/><text x={Math.min(endX-28,a.x+48)} y={a.y+(Math.min(endX-28,a.x+48)-a.x)*(deltaY/deltaX)*ratio-3}>{ratio===1?'1×1':ratio===2?'2×1':'1×2'}</text></g>
    })}</g>
  }

  if(!data.candles.length) return <div className="technical-dynamic-chart technical-chart-fallback">
    <div className="technical-chart-empty">该周期 OHLC 数据不足，暂无法绘制动态图表。</div>
    {staticChartUrl&&<div className="technical-chart-actions"><span>未请求外部行情</span><StaticChartLink url={staticChartUrl} symbol={symbol}/></div>}
  </div>
  if(failed) return staticChartUrl?<StaticChartLink url={staticChartUrl} symbol={symbol} visible/>:<div className="technical-chart-empty">动态图表初始化失败，且没有可用的静态缓存。</div>

  return <div className="technical-chart-shell">
    <div className="technical-chart-toolbar">
      <div className="technical-timeframes" aria-label="K 线周期">
        {([['day','日'],['week','周'],['month','月']] as const).map(([key,label])=><button type="button" key={key} className={timeframe===key?'active':''} onClick={()=>setTimeframe(key)}>{label}</button>)}
      </div>
      <div className="technical-layer-controls" aria-label="图表图层">
        <LayerButton active={layers.ma} onClick={()=>setLayers(value=>({...value,ma:!value.ma}))}>均线</LayerButton>
        <LayerButton active={layers.heatmap} onClick={()=>setLayers(value=>({...value,heatmap:!value.heatmap}))}>热度</LayerButton>
        <LayerButton active={layers.fibonacci} onClick={()=>setLayers(value=>({...value,fibonacci:!value.fibonacci}))}>自动斐波那契</LayerButton>
        <LayerButton active={layers.trend} onClick={()=>setLayers(value=>({...value,trend:!value.trend}))}>系统趋势</LayerButton>
        <LayerButton active={layers.events} onClick={()=>setLayers(value=>({...value,events:!value.events}))}>事件</LayerButton>
        <LayerButton active={layers.volumeProfile} onClick={()=>setLayers(value=>({...value,volumeProfile:!value.volumeProfile}))}>量价分布</LayerButton>
        <LayerButton active={layers.cost} onClick={()=>setLayers(value=>({...value,cost:!value.cost}))}>成本/提醒</LayerButton>
      </div>
    </div>
    <div className="technical-drawing-tools" aria-label="绘图工具">
      {([
        ['trend','趋势线'],['rectangle','箱体'],['fibonacci','手动斐波那契'],
        ['gann','江恩扇形'],['alert','价格提醒'],
      ] as const).map(([key,label])=><button type="button" key={key} className={tool===key?'active':''} aria-pressed={tool===key} onClick={()=>chooseTool(key)}>{label}</button>)}
      <button type="button" className="danger" disabled={!visibleDrawings.length} onClick={()=>setDrawings(current=>current.filter(item=>item.timeframe!==timeframe))}>清除本周期绘图</button>
      {tool&&<small>{tool==='alert'?'在图中拖到目标价格后松开':'按住起点并拖到终点；松开即保存'}{tool==='gann'?'，第二点定义价格/时间比例。':''}</small>}
    </div>
    <div className={`technical-dynamic-chart${tool?' is-drawing':''}`}>
      <div className="technical-chart-stage" ref={stageRef}>
        <div className="technical-chart-legend" ref={legendRef}/>
        <div className="technical-chart-canvas" ref={hostRef} role="img" aria-label={`${symbol} 可缩放技术蜡烛图，包含成交量、均线与交互图层`}/>
        <svg className="technical-chart-overlay" style={{height:dimensions.height}} viewBox={`0 0 ${Math.max(1,dimensions.width)} ${Math.max(1,dimensions.height)}`} preserveAspectRatio="none" onPointerDown={onDrawStart} onPointerMove={onDrawMove} onPointerUp={onDrawEnd} onPointerCancel={()=>{dragStart.current=null;setPreview(null)}}>
          {layers.heatmap&&heatZones.map((zone,index)=>{
            const top=priceY(zone.upper),bottom=priceY(zone.lower)
            if(top==null||bottom==null) return null
            return <rect key={`zone-${index}`} x="0" y={Math.min(top,bottom)} width={dimensions.width} height={Math.max(2,Math.abs(bottom-top))} className={`heat-zone ${zone.role}`} opacity={Math.max(.05,Math.min(.24,zone.normalizedIntensity*.2))}/>
          })}
          {layers.volumeProfile&&(()=>{
            const max=Math.max(1,...volumeProfile.map(item=>item.volume))
            return volumeProfile.map((item,index)=>{
              const top=priceY(item.upper),bottom=priceY(item.lower)
              if(top==null||bottom==null) return null
              const width=item.volume/max*Math.min(150,dimensions.width*.22)
              return <rect key={`vp-${index}`} x={dimensions.width-width} y={Math.min(top,bottom)} width={width} height={Math.max(1,Math.abs(bottom-top)-1)} className="volume-profile-bar"/>
            })
          })()}
          {layers.fibonacci&&fibonacci?.available&&Object.entries(fibonacci.levels||{}).map(([label,price])=>{
            const y=priceY(price)
            return y==null?null:<g key={label} className="auto-fibonacci"><line x1="0" x2={dimensions.width} y1={y} y2={y}/><text x="6" y={y-3}>{label} · {fmt(price)}</text></g>
          })}
          {layers.trend&&timeframe==='week'&&trendLines.map((line,index)=>{
            if(!line.anchors||line.anchors.length<2) return null
            const a={x:timeX(line.anchors[0].date),y:priceY(line.anchors[0].price)}
            const b={x:timeX(line.anchors[1].date),y:priceY(line.anchors[1].price)}
            return a.x==null||a.y==null||b.x==null||b.y==null?null:<line key={`auto-trend-${index}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="auto-trend"/>
          })}
          {layers.events&&events.map(event=>{
            const x=timeX(event.time)
            return x==null?null:<line key={`event-line-${event.id}`} x1={x} x2={x} y1="0" y2={dimensions.height} className={`event-line ${event.type}`}/>
          })}
          {layers.cost&&portfolioCost&&(()=>{
            const y=priceY(portfolioCost.average_cost)
            return y==null?null:<g className="portfolio-cost-line"><line x1="0" x2={dimensions.width} y1={y} y2={y}/><text x={Math.max(6,dimensions.width-132)} y={y-4}>持仓成本 {fmt(portfolioCost.average_cost)}</text></g>
          })()}
          {layers.cost&&priceAlerts.filter(item=>item.enabled).map(item=>{
            const y=priceY(item.target_price)
            return y==null?null:<g key={`alert-${item.id}`} className={`price-alert-line ${item.direction}`}><line x1="0" x2={dimensions.width} y1={y} y2={y}/><text x={Math.max(6,dimensions.width-122)} y={y-4}>提醒 {fmt(item.target_price)}</text></g>
          })}
          {visibleDrawings.map(item=>renderDrawing(item))}
          {preview&&renderDrawing({id:'preview',...preview},true)}
        </svg>
        {layers.events&&<div className="technical-event-pins">{events.map((event,index)=>{
          const x=timeX(event.time)
          if(x==null) return null
          const external=/^https?:\/\//.test(event.href)
          return <a key={event.id} href={event.href} target={external?'_blank':undefined} rel={external?'noreferrer':undefined} className={`event-pin ${event.type}`} style={{left:x,top:34+(index%3)*20,borderColor:EVENT_COLORS[event.type]}} title={`${event.time} · ${event.title}`}>{event.label}</a>
        })}</div>}
      </div>
      <div className="technical-chart-actions"><span>滚轮/双指缩放 · 拖动画面查看历史</span>{staticChartUrl&&<StaticChartLink url={staticChartUrl} symbol={symbol}/>}</div>
    </div>
    {pendingAlert&&<form className="technical-alert-editor" onSubmit={saveAlert}>
      <label>目标价格<input type="number" min="0.0001" step="any" value={pendingAlert.price} onChange={event=>setPendingAlert(value=>value?{...value,price:Number(event.target.value)}:value)}/></label>
      <label>触发方向<select value={pendingAlert.direction} onChange={event=>setPendingAlert(value=>value?{...value,direction:event.target.value as 'above'|'below'}:value)}><option value="above">达到或高于</option><option value="below">达到或低于</option></select></label>
      <button type="submit" disabled={!finite(pendingAlert.price)||pendingAlert.price<=0||alertStatus==='saving'}>{alertStatus==='saving'?'保存中…':'保存提醒'}</button>
      <button type="button" onClick={()=>setPendingAlert(null)}>取消</button>
      {alertStatus==='error'&&<small>保存失败，请稍后重试。</small>}
    </form>}
    {priceAlerts.length>0&&<div className="technical-alert-list">
      {priceAlerts.map(item=><div key={item.id} className={item.enabled?'':'inactive'}><span>{item.direction==='above'?'≥':'≤'} {fmt(item.target_price)}</span><small>{item.triggered_at?`已触发 ${new Date(item.triggered_at).toLocaleString('zh-CN')}`:'监控中'}</small>{item.enabled&&<button type="button" onClick={()=>removeAlert(item.id)}>移除</button>}</div>)}
    </div>}
  </div>
}
