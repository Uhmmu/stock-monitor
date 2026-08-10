import { FormEvent, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'
import { api, patch, post } from './api'
import { Sheet } from './Sheet'
import { SecuritySearchAutocomplete, securityPayload, type SecuritySearchResult } from './SecuritySearchAutocomplete'
import { PortfolioModule } from './Portfolio'
import { DiscoverySettingsPanel, OpportunityDiscovery } from './OpportunityDiscovery'
import { AdanosQuotaPanel, SentimentModule } from './Sentiment'
import { InvestmentCalendar } from './InvestmentCalendar'
import { OwnershipSection } from './Ownership'
import { AIChatPage } from './features/ai-chat'
import { InvestmentDecisionsPage } from './features/ai-memory'
import { MarketSnapshot } from './MarketSnapshot'
import { RealtimeProviderHealthPanel } from './RealtimeProviderHealthPanel'
import { IbkrIntegrationTest } from './IbkrIntegrationTest'
import { IbkrAccount } from './IbkrAccount'
import { MacroDataSourcePanel, MacroFundamentals } from './MacroFundamentals'
import { ThemeToggle } from './ThemeToggle'
import { providerValuesDiffer } from './financialComparison'
import { subscribeTheme, getResolvedTheme, type ThemeMode } from './theme'
import './macro.css'
import {
  TechnicalChart,
  type TechnicalChartEvent,
  type TechnicalChartSeries,
  type TechnicalMovingAverages,
  type TechnicalPriceAlert,
  type WeeklyCandle,
} from './TechnicalChart'

type WatchItem = { id:number; ticker:string; enabled:boolean; alert_enabled:boolean; user_group_id:number|null; display_order:number; threshold_20m:number|null; threshold_1h:number|null; threshold_day:number|null }
type ManagedStock = {ticker:string;company_name:string|null;official_sector:string|null;official_industry:string|null;user_group_id:number|null;display_order:number;is_watchlisted:boolean;is_peer_referenced:boolean;peer_referenced_by:string[];stock_type:'watchlist'|'matched';price:number|null;change_percent:number|null;alert_enabled:boolean;threshold_20m:number|null;threshold_1h:number|null;threshold_day:number|null;watchlist_id:number|null}
type StockManagementData = {groups:{id:number;name:string;display_order:number}[];watchlisted:ManagedStock[];matched:ManagedStock[]}
type PeerItem = {ticker:string;source:'official'|'manual';excluded:boolean;display_order:number;is_watchlisted:boolean}
type PeerList = {base_ticker:string;items:PeerItem[]}
type Dashboard = { market:{is_open:boolean; checked_at:string}; stocks:{ticker:string;company_name?:string|null;logo_url?:string|null;price:number|null;previous_close:number|null;updated_at:string|null;volume:number|null;volume_ratio:number|null;volume_label:string|null}[] }
type CompanyProfile = {symbol:string;status:string;company_name:string|null;logo_url?:string|null;website?:string|null;ceo?:string|null;exchange?:string|null;exchange_full_name?:string|null;ipo_date?:string|null;employee_count?:number|null;description_en?:string|null;description_zh?:string|null;translation_status?:string;profile_fetched_at?:string|null;local_classification:{sector:string|null;industry:string|null}}
type Zone = {low:number;high:number;center:number;type:'support'|'resistance';touchCount:number;strength:number;mostRecentTouchDate:string;distancePercent:number}
type TechnicalHeatZone = {lower:number;upper:number;center:number;role:'support'|'resistance'|'neutral';rawCount:number;sourceCount:number;familyCount:number;weightedScore:number;normalizedIntensity:number;distancePercent:number;sources?:string[];methodFamilies?:string[]}
type TechnicalPriceLevel = {source:string;methodFamily:string;price:number;role:'support'|'resistance'|'neutral';confidence:number;distancePercent:number}
type HistoricalCausalHeatmap = {version:string;mode:'historical_causal';timeframe:'weekly';priceBinCount:number;timeColumnCount:number;priceMin:number;priceMax:number;minimumFamilyCount:number;renderTimeBlockBars:number;renderPriceBlockBins:number;projectionSpaceBars?:number;projectionExtensionBars?:number;paletteVersion:string;methodsIncluded:string[];methodsExcluded:string[];calculationMs:number;currentLevels?:TechnicalPriceLevel[];currentZones:TechnicalHeatZone[]}
type TechnicalItem = {symbol:string;status:string;company_name:string|null;logo_url:string|null;chart_url:string|null;data_through?:string;generated_at?:string;stale?:boolean;chart_data_status?:'ready'|'insufficient';chart_data_reason?:string|null;chart_data_source?:string|null;weekly?:WeeklyCandle[];moving_averages?:TechnicalMovingAverages;chart_series?:TechnicalChartSeries;events?:TechnicalChartEvent[];portfolio_cost?:{average_cost:number;quantity:number;currency:string}|null;price_alerts?:TechnicalPriceAlert[];analysis?:{latestClose:number;weeklyTrend:string;nearestSupport:Zone|null;nearestResistance:Zone|null;supportZones:Zone[];resistanceZones:Zone[];fibonacci:{available:boolean;direction?:string;levels?:Record<string,number>;omissionReason?:string};trendLines:{type:string;projectedPrice:number;priceRelation:string;confidence:number;anchors?:{date:string;price:number}[]}[];indicators:Record<string,number|null>;omittedReasons:string[];historicalCausalHeatmap?:HistoricalCausalHeatmap};profile?:CompanyProfile;data_status?:Record<string,string|null>}
type IndexQuote = {symbol:string;name:string;price:number|null;previous_close:number|null;change_points:number|null;change_percent:number|null}
type Indices = {indices:IndexQuote[];market:{is_open:boolean;checked_at:string}}
type Alert = {id:number;ticker:string;period:string;change_percent:number;triggered_at:string}
type Investigation = {id:number;ticker:string;status:string;started_at:string;ends_at:string;news_count:number;last_error:string|null}
type Report = {id:number;ticker:string|null;report_type:string;title:string;model:string;created_at:string;confidence?:'高'|'中'|'低'|null}
type ReportDetail = Report & {content:string;sources:{title:string;url:string}[]}
type Settings = {threshold_20m:number;threshold_1h:number;threshold_day:number;alert_cooldown_minutes:number;investigation_interval_minutes:number;investigation_duration_minutes:number;price_poll_minutes:number}
type NewsAIAnalysis = {summary_zh:string|null;key_points:string[];companies:string[];tickers:string[];industries:string[];event_type:string|null;sentiment:string|null;market_impact:string|null;importance:number|null;source_quality:string|null;confidence:number|null}
type NewsRow = {id:number;ticker:string;provider:string;title:string;translated_title:string|null;title_translation_model:string|null;title_translated_at:string|null;url:string;source:string|null;summary:string|null;symbols:string[];news_type:string;scope:'market'|'company';topic:string|null;importance_score:number|null;quality_score:number|null;published_at:string|null;found_at:string;relevance_score:number|null;sentiment_score:number|null;ai_summary:string|null;ai_summary_model:string|null;ai_summary_status:'idle'|'pending'|'queued'|'processing'|'completed'|'degraded'|'failed';ai_summary_requested_at:string|null;ai_summary_error:string|null;article_content?:string|null;content_final_url?:string|null;content_fetch_method?:string|null;content_fetch_status?:string|null;content_fetch_quality?:number|null;ai_analysis?:NewsAIAnalysis|null;ai_event_type?:string|null;ai_sentiment?:string|null;ai_importance?:number|null;ai_market_impact?:string|null;ai_summary_version?:string|null;ai_summary_generated_at?:string|null}
type MarketNewsResponse = {items:NewsRow[];total:number;generated_at:string;last_updated_at:string|null;sources:string[]}
type NewsArchive = {ticker:string;market_date:string;content:string;model:string;version:number;updated_at:string;included_news_ids:number[]}
type WeeklyArchive = {ticker:string;iso_year:number;iso_week:number;week_start:string;week_end:string;content:string;included_dates:string[];model:string;version:number;updated_at:string}
type Financial = {fiscal_year:number;fiscal_period:string;period_end:string;filed_at:string|null;currency:string|null;revenue:number|null;eps:number|null;net_income:number|null;operating_income:number|null;gross_margin:number|null;net_margin:number|null;operating_cash_flow:number|null;free_cash_flow:number|null;source:string;synced_at:string}
type StatementValues = Record<string,number|null>
type FinancialStatement = {fiscal_year:number;fiscal_period:string;period_end:string;currency:string|null;income_statement:StatementValues;balance_sheet:StatementValues;cash_flow:StatementValues;source:string;synced_at:string}
type StatementMetric = {label:string;english:string;description:string;impact:string;formula?:string}
type Rating = {period:string|null;strongBuy:number;buy:number;hold:number;sell:number;strongSell:number}
type Fundamentals = {ticker:string;metrics:{label:string;value:number|null;source:'yahoo'|'finnhub'|null}[];rating:Rating|null;as_of:string;data_mode:'live';source_support:{yahoo:boolean;finnhub:boolean}}
type CrossMetric = {key:string;label:string;value:number|null;unit:string;status:'available'|'partial'|'insufficient'|'not_applicable';display?:string|null;missing_fields?:string[];warnings?:string[];available_components?:number;total_components?:number;components?:Record<string,boolean|null>;applicability?:'medium'|'low'|'not_applicable';formula_version?:string;inputs?:Record<string,unknown>;peer_median:number|null;peer_count:number;peer_delta_percent:number|null;comparison:string|null;formula:string;recommended_range:string;explanation:string;note:string|null}
type WeightAdjustment = {tag:string;label:string;confidence:number;raw_adjustment:number;applied_adjustment:number}
type WeightDetail = {key:string;label:string;base_score:number;adjustments:WeightAdjustment[];final_score:number;weight:number}
type ModelSignal = {key:string;label:string;verdict:string;stars:number;detail:string}
type GrahamPoint = {value:number|null;source:string;field?:string|null;as_of?:string|null;quality:string;raw_value?:number;clamped?:boolean;original?:GrahamPoint}
type GrahamScenario = {name:string;growth_rate:number|null;intrinsic_value:number|null;current_price:number|null;margin_of_safety:number|null;premium_or_discount:number|null;status:GrahamStatus;available:boolean}
type GrahamStatus = 'undervalued'|'fairly_valued'|'overvalued'|'not_applicable'
type GrahamAnalysis = {symbol:string;currency:string;current_price:number|null;graham_number:{value:number|null;margin_of_safety:number|null;status:GrahamStatus;available:boolean};growth_formula:{conservative:GrahamScenario;base:GrahamScenario;optimistic:GrahamScenario};inputs:{current_price:GrahamPoint;eps_ttm:GrahamPoint;book_value_per_share:GrahamPoint;growth_rate:GrahamPoint;aaa_yield:GrahamPoint};applicability:{status:'applicable'|'limited'|'not_applicable';confidence:string;reasons:string[];missing_fields:string[]};overall_status:GrahamStatus;financial_period:string|null;updated_at:string}
type CrossModel = {ticker:string;company:string;classification:{sector:string|null;industry:string|null;industry_key:string|null;profile:string;label:string;primary:string[];secondary:string[];focus:string};peers:{source:string;symbols:string[];official_symbols?:string[];coverage:number;medians:Record<string,number>};tags:{name:string;label:string;confidence:number}[];weights:Record<string,number>;weight_details:WeightDetail[];valuation:CrossMetric[];growth:CrossMetric[];health:CrossMetric[];graham:GrahamAnalysis|null;dcf_scenarios:{bear:number|null;base:number|null;bull:number|null;current:number|null;assumptions:Record<string,{growth:number;discount_rate:number;terminal_growth:number}>};reverse_dcf:{implied_fcf_growth:number|null;unit:string};consensus:{items:{key:string;label:string;value:number}[];value:number|null;current:number|null};model_signals:ModelSignal[];model_conflict:boolean;ai_opinion:string;ai_model:string|null;snapshot_date:string;generated_at:string|null}
type SecEvent = {id:number;form:string;item_code:string;item_label:string;priority:string;text:string|null;summary_zh:string|null;summary_model:string|null;summary_status:string;filing_date:string|null;filing_url:string}
type SecFin = {fiscal_year:number;fiscal_period:string;form:string;period_end:string|null;currency:string|null;source:string;synced_at:string;revenue:number|null;net_income:number|null;operating_income:number|null;gross_profit:number|null;eps_basic:number|null;eps_diluted:number|null;cash_and_equivalents:number|null;total_debt:number|null;shares_outstanding:number|null;operating_cash_flow:number|null}
type SecInsider = {id:number;insider_name:string;insider_title:string|null;transaction_date:string|null;transaction_code:string|null;shares:number|null;price:number|null;value:number|null;shares_owned_after:number|null;flag:string|null;filing_url:string}
type Sec13FHolding = {id:number;manager_name:string;shares:number|null;value_usd:number|null;put_call:string|null;share_change:number|null;is_new:boolean;filing_date:string|null}
type Sec13F = {report_period:string|null;prev_period:string|null;holdings:Sec13FHolding[]}
type TemporarySnapshot = {ticker:string;section:string;expires_at:string}
type Figure = {slug:string;display_name:string;kind:string;photo_url:string|null;note:string|null;is_seed:boolean;has_positions:boolean}
type FilerHit = {filer_id:string;full_name:string;chamber:string|null;branch:string|null;party:string|null;state:string|null;trade_count:number|null}
type TradeLogRow = {security_id?:number|null;ticker:string;direction:string;quantity:number|null;price:number|null;fee:number|null;strategy:string;result:string}
type TradeLog = {id:number;trade_date:string;ticker:string|null;direction:string|null;quantity:number|null;price:number|null;note:string|null;content:string|null;table_rows:TradeLogRow[];photo_urls:string[];ai_summary:string|null;ai_summary_model:string|null;ai_summary_created_at:string|null;status:'draft'|'published';source_type:'manual'|'ibkr_sync';objective_facts:Record<string,unknown>;ibkr_sync_run_id:number|null;ibkr_position_id:number|null;created_at:string}

const formatPrice = (value:number|null) => value == null ? '等待行情' : `$${value.toFixed(2)}`
const formatDate = (value:string) => new Date(value).toLocaleString('zh-CN')
const normalizeTab = (tab:string) => tab==='sentiment'?'news':tab==='congress'?'settings':tab
// 同一股票在同一美东交易日的多次异动调查归并为一张卡片（后端已限制一天一个，此处兜底并处理历史数据）
const marketDayKey = (value:string) => new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value))
type InvestigationGroup = {key:string;ticker:string;status:string;started_at:string;ends_at:string;news_count:number;last_error:string|null;items:Investigation[]}
const groupInvestigations = (rows:Investigation[]|undefined):InvestigationGroup[] => {
  if(!rows?.length) return []
  const order:string[] = []
  const map = new Map<string,InvestigationGroup>()
  const rank:Record<string,number> = {active:0,reporting:1,completed:2}
  for(const item of rows){
    const key = `${item.ticker}:${marketDayKey(item.started_at)}`
    const existing = map.get(key)
    if(!existing){
      order.push(key)
      map.set(key,{key,ticker:item.ticker,status:item.status,started_at:item.started_at,ends_at:item.ends_at,news_count:item.news_count,last_error:item.last_error,items:[item]})
      continue
    }
    existing.items.push(item)
    existing.news_count += item.news_count
    if(item.started_at < existing.started_at) existing.started_at = item.started_at
    if(item.ends_at > existing.ends_at) existing.ends_at = item.ends_at
    if((rank[item.status]??9) < (rank[existing.status]??9)) existing.status = item.status
    if(!existing.last_error && item.last_error) existing.last_error = item.last_error
  }
  return order.map(key=>map.get(key)!)
}
const typeNames:Record<string,string> = {premarket:'盘前',postmarket:'盘后',movement:'价格异动',earnings_before:'财报前',earnings_after:'财报后'}
const sectorNames:Record<string,string> = {
  'Basic Materials':'基础材料','Communication Services':'通信服务','Consumer Cyclical':'可选消费','Consumer Defensive':'必需消费',
  'Energy':'能源','Financial Services':'金融服务','Healthcare':'医疗保健','Industrials':'工业','Real Estate':'房地产','Technology':'信息技术','Utilities':'公用事业',
}
const industryNames:Record<string,string> = {
  'Aerospace & Defense':'航空航天与国防','Agricultural Inputs':'农业投入品','Airlines':'航空公司','Airports & Air Services':'机场与航空服务','Aluminum':'铝业',
  'Asset Management':'资产管理','Auto & Truck Dealerships':'汽车经销商','Auto Manufacturers':'汽车制造','Auto Parts':'汽车零部件',
  'Banks - Diversified':'多元化银行','Banks - Regional':'区域银行','Beverages - Brewers':'啤酒酿造','Beverages - Non-Alcoholic':'非酒精饮料','Beverages - Wineries & Distilleries':'葡萄酒与烈酒',
  'Biotechnology':'生物技术','Building Materials':'建筑材料','Building Products & Equipment':'建筑产品与设备','Capital Markets':'资本市场','Chemicals':'化工','Coking Coal':'焦煤',
  'Communication Equipment':'通信设备','Computer Hardware':'计算机硬件','Confectioners':'糖果食品','Conglomerates':'综合企业','Consulting Services':'咨询服务','Consumer Electronics':'消费电子','Copper':'铜业','Credit Services':'信贷服务',
  'Department Stores':'百货商店','Diagnostics & Research':'诊断与研究','Discount Stores':'折扣零售','Drug Manufacturers - General':'综合制药','Drug Manufacturers - Specialty & Generic':'专科药与仿制药',
  'Education & Training Services':'教育与培训服务','Electrical Equipment & Parts':'电气设备与零部件','Electronic Components':'电子元件','Electronic Gaming & Multimedia':'电子游戏与多媒体','Engineering & Construction':'工程与建筑','Entertainment':'娱乐',
  'Farm & Heavy Construction Machinery':'农业与重型工程机械','Farm Products':'农产品','Financial Conglomerates':'金融综合企业','Financial Data & Stock Exchanges':'金融数据与证券交易所','Food Distribution':'食品分销','Footwear & Accessories':'鞋履与配饰',
  'Furnishings, Fixtures & Appliances':'家居用品与家电','Gambling':'博彩','Gold':'黄金','Grocery Stores':'食品杂货零售','Healthcare Plans':'健康保险','Health Information Services':'医疗信息服务','Home Improvement Retail':'家居建材零售','Household & Personal Products':'家居与个人用品',
  'Industrial Distribution':'工业品分销','Information Technology Services':'信息技术服务','Insurance Brokers':'保险经纪','Insurance - Diversified':'综合保险','Insurance - Life':'人寿保险','Insurance - Property & Casualty':'财产与意外保险','Insurance - Reinsurance':'再保险','Insurance - Specialty':'专业保险',
  'Internet Content & Information':'互联网内容与信息','Internet Retail':'互联网零售','Leisure':'休闲娱乐','Lodging':'住宿业','Luxury Goods':'奢侈品','Marine Shipping':'海运',
  'Medical Care Facilities':'医疗服务机构','Medical Devices':'医疗器械','Medical Distribution':'医疗产品分销','Medical Instruments & Supplies':'医疗仪器与耗材','Metal Fabrication':'金属加工','Mortgage Finance':'抵押贷款金融',
  'Oil & Gas Drilling':'油气钻探','Oil & Gas E&P':'油气勘探与生产','Oil & Gas Equipment & Services':'油气设备与服务','Oil & Gas Integrated':'综合油气','Oil & Gas Midstream':'油气中游','Oil & Gas Refining & Marketing':'油气炼化与销售',
  'Other Industrial Metals & Mining':'其他工业金属与采矿','Other Precious Metals & Mining':'其他贵金属与采矿','Packaged Foods':'包装食品','Packaging & Containers':'包装与容器','Paper & Paper Products':'纸业','Personal Services':'个人服务','Pharmaceutical Retailers':'药品零售','Pollution & Treatment Controls':'污染治理设备','Publishing':'出版',
  'Railroads':'铁路运输','Real Estate - Diversified':'综合房地产','Real Estate - Development':'房地产开发','Real Estate Services':'房地产服务','Recreational Vehicles':'休闲车辆',
  'REIT - Diversified':'综合型房地产信托','REIT - Healthcare Facilities':'医疗设施房地产信托','REIT - Hotel & Motel':'酒店房地产信托','REIT - Industrial':'工业地产信托','REIT - Mortgage':'抵押贷款房地产信托','REIT - Office':'办公地产信托','REIT - Residential':'住宅地产信托','REIT - Retail':'零售地产信托','REIT - Specialty':'专业地产信托',
  'Rental & Leasing Services':'租赁服务','Restaurants':'餐饮','Scientific & Technical Instruments':'科学与技术仪器','Security & Protection Services':'安防服务','Semiconductors':'半导体','Semiconductor Equipment & Materials':'半导体设备与材料','Shell Companies':'空壳公司',
  'Software - Application':'应用软件','Software - Infrastructure':'基础软件','Solar':'太阳能','Specialty Business Services':'专业商业服务','Specialty Chemicals':'特种化工','Specialty Industrial Machinery':'专用工业机械','Specialty Retail':'专业零售','Staffing & Employment Services':'人力资源服务','Steel':'钢铁',
  'Telecom Services':'电信服务','Textile Manufacturing':'纺织制造','Thermal Coal':'动力煤','Tobacco':'烟草','Tools & Accessories':'工具与配件','Travel Services':'旅游服务','Trucking':'公路货运',
  'Utilities - Diversified':'综合公用事业','Utilities - Independent Power Producers':'独立发电商','Utilities - Regulated Electric':'受监管电力','Utilities - Regulated Gas':'受监管燃气','Utilities - Regulated Water':'受监管水务','Utilities - Renewable':'可再生能源公用事业','Waste Management':'废弃物管理',
  'Advertising Agencies':'广告代理','Apparel Manufacturing':'服装制造','Apparel Retail':'服装零售','Broadcasting':'广播电视','Business Equipment & Supplies':'商业设备与用品',
  'Closed-End Fund - Debt':'封闭式债券基金','Closed-End Fund - Equity':'封闭式股票基金','Closed-End Fund - Foreign':'封闭式海外基金','Integrated Freight & Logistics':'综合货运与物流','Lumber & Wood Production':'木材生产',
  'Residential Construction':'住宅建筑','Resorts & Casinos':'度假村与赌场','Silver':'白银','Uranium':'铀矿','Furnishings Fixtures & Appliances':'家居用品与家电',
}
const localizeSector = (value:string|null|undefined,fallback='未分类') => value ? sectorNames[value]||value : fallback
const localizeIndustry = (value:string|null|undefined,fallback='行业待同步') => value ? industryNames[value]||value : fallback

function SnapshotTickerBar({section,tickers,current,onSelect,leading}:{section:'news'|'fundamentals'|'financials'|'valuation'|'sec'|'sentiment';tickers:string[];current:string;onSelect:(ticker:string)=>void;leading?:React.ReactNode}) {
  const [selectedSecurity,setSelectedSecurity] = useState<SecuritySearchResult|null>(null)
  const client = useQueryClient()
  const snapshots = useQuery({queryKey:['snapshots',section],queryFn:()=>api<TemporarySnapshot[]>(`/snapshots/${section}`)})
  const search = useMutation({mutationFn:(security:SecuritySearchResult)=>{const params=new URLSearchParams();Object.entries(securityPayload(security)).forEach(([key,value])=>{if(value!=null)params.set(key,String(value))});return post<TemporarySnapshot>(`/snapshots/${section}?${params}`,{})},onSuccess:item=>{setSelectedSecurity(null);onSelect(item.ticker);client.invalidateQueries({queryKey:['snapshots',section]})}})
  const remove = useMutation({mutationFn:(ticker:string)=>api(`/snapshots/${section}/${ticker}`,{method:'DELETE'}),onSuccess:(_,ticker)=>{if(current===ticker) onSelect(tickers[0]||'');client.invalidateQueries({queryKey:['snapshots',section]});client.removeQueries({queryKey:[section,ticker]})}})
  const temporary = snapshots.data||[]
  const shown = [...tickers, ...temporary.map(item=>item.ticker).filter(ticker=>!tickers.includes(ticker))]
  return <><form className="snapshot-search" onSubmit={event=>{event.preventDefault();if(selectedSecurity)search.mutate(selectedSecurity)}}><SecuritySearchAutocomplete value={selectedSecurity} onSelect={setSelectedSecurity} placeholder="临时查看代码或公司名称" compact/><button disabled={!selectedSecurity||search.isPending}>{search.isPending?'正在采集…':'查看快照'}</button></form><div className="news-tickers">{leading}{shown.map(ticker=>{const isTemporary=temporary.some(item=>item.ticker===ticker);return <span className={`ticker-chip${ticker===current?' active':''}${isTemporary?' temporary':''}`} key={ticker}><button onClick={()=>onSelect(ticker)}>{ticker}</button>{isTemporary&&<button className="ticker-remove" aria-label={`删除 ${ticker} 临时快照`} onClick={()=>remove.mutate(ticker)}>×</button>}</span>})}</div>{search.isError&&<p className="error">候选证券已失效或暂时无法采集，请重新搜索。</p>}</>
}

const demoDashboard:Dashboard = {
  market:{is_open:true,checked_at:new Date().toISOString()},
  stocks:[
    {ticker:'AAPL',price:214.37,previous_close:211.18,updated_at:new Date().toISOString(),volume:52180300,volume_ratio:1.18,volume_label:'放量'},
    {ticker:'NVDA',price:141.22,previous_close:143.61,updated_at:new Date().toISOString(),volume:183410200,volume_ratio:.91,volume_label:'正常'},
    {ticker:'MSFT',price:468.91,previous_close:465.82,updated_at:new Date().toISOString(),volume:19284600,volume_ratio:1.04,volume_label:'正常'},
    {ticker:'TSLA',price:322.05,previous_close:315.63,updated_at:new Date().toISOString(),volume:84630200,volume_ratio:1.31,volume_label:'放量'},
  ],
}
const demoIndices:Indices = {market:demoDashboard.market,indices:[
  {symbol:'^GSPC',name:'标普 500',price:6216.44,previous_close:6198.01,change_points:18.43,change_percent:.30},
  {symbol:'^IXIC',name:'纳斯达克',price:20273.46,previous_close:20192.18,change_points:81.28,change_percent:.40},
  {symbol:'^DJI',name:'道琼斯',price:44484.49,previous_close:44502.12,change_points:-17.63,change_percent:-.04},
]}
const demoAlerts:Alert[] = [
  {id:-1,ticker:'TSLA',period:'20 分钟',change_percent:2.04,triggered_at:new Date().toISOString()},
  {id:-2,ticker:'NVDA',period:'1 小时',change_percent:-1.66,triggered_at:new Date().toISOString()},
  {id:-3,ticker:'AAPL',period:'当日',change_percent:1.51,triggered_at:new Date().toISOString()},
]
const demoReports:Report[] = [
  {id:-1,ticker:'AAPL',report_type:'movement',title:'Apple 盘中放量上行：关键驱动与风险观察',model:'preview',created_at:new Date().toISOString()},
  {id:-2,ticker:'TSLA',report_type:'movement',title:'Tesla 短线动量增强，市场在交易什么？',model:'preview',created_at:new Date(Date.now()-36e5).toISOString()},
]

function NavIcon({name}:{name:string}) {
  const paths:Record<string,React.ReactNode> = {
    overview:<><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></>,
    watchlist:<><path d="M4 19V9"/><path d="M10 19V5"/><path d="M16 19v-7"/><path d="M22 19H2"/></>,
    holdings:<><path d="M3 7h18v13H3z"/><path d="M3 7l3-4h12l3 4"/><path d="M9 11a3 3 0 0 0 6 0"/></>,
    discovery:<><circle cx="12" cy="12" r="8"/><path d="m15.5 8.5-2.1 4.9-4.9 2.1 2.1-4.9z"/><circle cx="12" cy="12" r="1"/></>,
    ai:<><path d="M5 4h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H10l-5 4v-4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/><path d="M8 9h8M8 13h5"/></>,
    memory:<><path d="M8 5a4 4 0 0 1 7-2 4 4 0 0 1 4 4 4 4 0 0 1 1 7 4 4 0 0 1-5 6l-3 2-3-2a4 4 0 0 1-5-6 4 4 0 0 1 1-7 4 4 0 0 1 3-2z"/><path d="M9 9h6M9 13h4"/></>,
    decisions:<><path d="M5 3h14v18H5z"/><path d="m8 8 2 2 4-4M8 15h8"/></>,
    alerts:<><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></>,
    news:<><path d="M4 5h16v14H4z"/><path d="M8 9h8M8 13h5"/></>,
    sentiment:<><path d="M4 15.5c1.4-1.8 2.8-2.7 4.2-2.7 2.2 0 2.8 3.4 5 3.4 1.5 0 3-1.4 4.8-4.2"/><path d="M4 9c1.1-1.2 2.2-1.8 3.3-1.8 1.8 0 2.5 2.5 4.2 2.5 1.3 0 2.5-.9 3.7-2.7"/><circle cx="19" cy="7" r="2"/><path d="M3 20h18"/></>,
    fundamentals:<><path d="m3 17 5-5 4 3 8-9"/><path d="M15 6h5v5"/></>,
    macro:<><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/><path d="M7 8h10M7 16h10"/></>,
    calendar:<><path d="M6 2v4M18 2v4M3 9h18"/><rect x="3" y="4" width="18" height="17" rx="3"/><path d="M8 13h2M14 13h2M8 17h2M14 17h2"/></>,
    financials:<><path d="M5 3h14v18H5z"/><path d="M8 8h8M8 12h3M13 12h3M8 16h3M13 16h3"/></>,
    crossmodel:<><path d="M4 18V7M10 18V4M16 18v-8M22 18H2"/><path d="m5 11 5-3 4 4 6-6"/></>,
    technical:<><path d="M3 17 8 12l4 3 8-9"/><path d="M4 21h16M7 9v6M12 11v7M17 4v8"/></>,
    sec:<><path d="M6 2h9l4 4v16H6z"/><path d="M14 2v5h5M9 12h6M9 16h6"/></>,
    congress:<><circle cx="12" cy="8" r="4"/><path d="M4 21c1-5 4-7 8-7s7 2 8 7"/></>,
    reports:<><path d="M5 3h14v18H5z"/><path d="M9 8h6M9 12h6M9 16h4"/></>,
    journal:<><path d="M5 4h14v16H5z"/><path d="M9 4v16M12 8h4M12 12h4"/></>,
    settings:<><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1z"/></>,
    ibkr:<><path d="M4 7h16v12H4z"/><path d="M8 7V4h8v3M8 12h8M8 15h5"/><path d="M17 11v5"/></>,
    'ibkr-test':<><path d="M4 7h16v12H4z"/><path d="M8 7V4h8v3M8 12h8M8 15h5"/><path d="M17 11v5"/></>,
  }
  return <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>
}

function ProfileLogo({symbol,url,className='' }:{symbol:string;url?:string|null;className?:string}) {
  const [failed,setFailed] = useState(false)
  useEffect(()=>setFailed(false),[url])
  if(!url||failed) return <span className={`profile-logo fallback ${className}`}>{symbol.slice(0,2)}</span>
  return <img className={`profile-logo ${className}`} src={url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={()=>setFailed(true)}/>
}

function TradingViewStockHeatmap() {
  const widgetRef = useRef<HTMLDivElement>(null)
  const [theme,setTheme]=useState<ThemeMode>(()=>getResolvedTheme())

  useEffect(()=>subscribeTheme(setTheme),[])

  useEffect(()=>{
    const host = widgetRef.current
    if(!host) return

    const widget = document.createElement('div')
    widget.className = 'tradingview-widget-container__widget'
    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js'
    script.type = 'text/javascript'
    script.async = true
    script.textContent = JSON.stringify({
      exchanges:[],
      dataSource:'SPX500',
      grouping:'sector',
      blockSize:'market_cap_basic',
      blockColor:'change',
      locale:'zh_CN',
      symbolUrl:'',
      colorTheme:theme==='dark'?'dark':'light',
      hasTopBar:false,
      isDataSetEnabled:false,
      isZoomEnabled:true,
      hasSymbolTooltip:true,
      isMonoSize:false,
      width:'100%',
      height:'100%',
    })
    host.replaceChildren(widget,script)

    return ()=>host.replaceChildren()
  },[theme])

  return <section className="overview-heatmap">
    <div className="section-title">
      <div><p>MARKET BREADTH</p><h2>Stock Heatmap</h2></div>
      <small>标普 500 · 按行业与市值分组</small>
    </div>
    <div className="tradingview-heatmap-shell">
      <div className="tradingview-widget-container" ref={widgetRef}/>
      <noscript>请启用 JavaScript 以查看 TradingView 股票热力图。</noscript>
    </div>
    <a className="tradingview-attribution" href="https://www.tradingview.com/markets/stocks-usa/market-movers-large-cap/" target="_blank" rel="noopener nofollow">Stock Heatmap <span>by TradingView</span></a>
  </section>
}

function TechnicalLevelSummary({latestClose,heatmap}:{latestClose:number;heatmap?:HistoricalCausalHeatmap}) {
  const zones=heatmap?.currentZones||[]
  const support=zones.filter(zone=>zone.role==='support'&&zone.upper<latestClose).sort((a,b)=>b.upper-a.upper)[0]
  const resistance=zones.filter(zone=>zone.role==='resistance'&&zone.lower>latestClose).sort((a,b)=>a.lower-b.lower)[0]
  const strength=(zone:TechnicalHeatZone)=>zone.familyCount>=5?'强':zone.familyCount>=3?'较强':'一般'
  const card=(role:'support'|'resistance',zone?:TechnicalHeatZone)=>{
    const supportRole=role==='support'
    return <section className={`technical-level-card ${role}`}>
      <div className="technical-level-card-title"><span>{supportRole?'最近支撑':'最近压力'}</span>{zone&&<em>{strength(zone)}</em>}</div>
      {zone?<><strong>${zone.lower.toFixed(2)}–${zone.upper.toFixed(2)}</strong><small>{zone.familyCount} 类方法 · {zone.sourceCount} 个技术点位</small><b>{`距现价 ${zone.distancePercent>=0?'+':''}${zone.distancePercent.toFixed(1)}%`}</b></>:<><strong className="unavailable">暂无有效{supportRole?'支撑':'压力'}热区</strong><small>等待更多独立技术方法形成交汇</small></>}
    </section>
  }
  return <div className="technical-level-summary" aria-label="当前技术点位热区">{card('support',support)}{card('resistance',resistance)}</div>
}

const technicalFamilyLabels:Record<string,string>={
  moving_average:'均线系统',
  volatility_band:'波动通道',
  rolling_extreme:'周期高低点',
  previous_period_pivot:'周枢轴',
  swing_structure:'确认结构',
  fibonacci:'斐波那契',
  trendline:'趋势线',
}

function technicalSourceLabel(source:string) {
  let match=source.match(/^ma(\d+)$/)
  if(match)return `MA ${match[1]} 周`
  match=source.match(/^ema(\d+)$/)
  if(match)return `EMA ${match[1]} 周`
  const fixed:Record<string,string>={
    bollinger_low:'布林下轨',
    bollinger_middle:'布林中轨',
    bollinger_high:'布林上轨',
    pivot_p:'中心枢轴 P',
    pivot_r1:'第一压力 R1',
    pivot_s1:'第一支撑 S1',
    pivot_r2:'第二压力 R2',
    pivot_s2:'第二支撑 S2',
  }
  if(fixed[source])return fixed[source]
  match=source.match(/^rolling_(high|low)_(\d+)$/)
  if(match)return `${match[2]} 周${match[1]==='high'?'高点':'低点'}`
  match=source.match(/^confirmed_swing_(high|low)_(\d+)$/)
  if(match)return `确认摆动${match[1]==='high'?'高点':'低点'} · #${match[2]}`
  match=source.match(/^causal_fibonacci_([0-9.]+)_/)
  if(match)return `回撤 ${Math.round(Number(match[1])*1000)/10}%`
  if(source.startsWith('causal_low_trendline_'))return '上升支撑线'
  if(source.startsWith('causal_high_trendline_'))return '下降压力线'
  return source.replaceAll('_',' ')
}

function TechnicalIndicatorPositions({heatmap}:{heatmap?:HistoricalCausalHeatmap}) {
  const levels=heatmap?.currentLevels||[]
  if(!heatmap)return null
  if(!levels.length)return <section className="technical-indicator-positions">
    <header><div><p>PRICE-BASED INDICATORS</p><h3>各指标当前位置</h3></div><small>价格坐标尚不可用</small></header>
    <p className="technical-indicator-empty">周线历史样本不足，暂不能形成可靠的均线、结构与交汇点位；补齐至少 52 周数据后自动显示。</p>
  </section>
  const familyOrder=Object.keys(technicalFamilyLabels)
  const families=familyOrder.map(family=>({
    family,
    levels:levels.filter(level=>level.methodFamily===family),
  })).filter(group=>group.levels.length)
  return <section className="technical-indicator-positions" aria-labelledby="technical-position-title">
    <header><div><p>PRICE-BASED INDICATORS</p><h3 id="technical-position-title">各指标当前位置</h3></div><small>{levels.length} 个有效价格坐标 · 以最新周线收盘为基准</small></header>
    <div className="technical-indicator-groups">{families.map(group=><article key={group.family}>
      <h4>{technicalFamilyLabels[group.family]} <small>{group.levels.length}</small></h4>
      <div>{group.levels.map(level=><div className={`technical-indicator-row ${level.role}`} key={level.source}>
        <span><i aria-hidden="true"/>{technicalSourceLabel(level.source)}</span>
        <strong>{level.price.toFixed(2)}</strong>
        <small>{`${level.distancePercent>=0?'+':''}${level.distancePercent.toFixed(1)}%`}</small>
      </div>)}</div>
    </article>)}</div>
    <footer><span className="support">低于现价 / 支撑侧</span><span className="neutral">贴近现价</span><span className="resistance">高于现价 / 压力侧</span></footer>
  </section>
}

function CompanyProfileSheet({symbol,onClose,onAskAI}:{symbol:string|null;onClose:()=>void;onAskAI:(symbol:string)=>void}) {
  const profile = useQuery({queryKey:['company-profile',symbol],queryFn:()=>api<CompanyProfile>(`/company-profile/${symbol}`),enabled:!!symbol})
  const [section,setSection]=useState<'overview'|'market'>('overview')
  useEffect(()=>setSection('overview'),[symbol])
  const p=profile.data
  return <Sheet open={symbol!==null} onClose={onClose} title="公司概览"><div className="company-profile-tabs"><nav aria-label="公司概览分区"><button className={section==='overview'?'active':''} onClick={()=>setSection('overview')}>总览</button><button className={section==='market'?'active':''} onClick={()=>setSection('market')}>市场快照</button></nav>{section==='overview'?(p?.status==='ready'?<article className="company-profile"><header><ProfileLogo symbol={p.symbol} url={p.logo_url}/><div><p className="eyebrow">FMP CACHED PROFILE</p><h2>{p.company_name||p.symbol} <small>{p.symbol}</small></h2></div></header><div className="company-profile-actions"><button onClick={()=>onAskAI(p.symbol)}>询问 AI <span>→</span></button>{p.website&&<a href={p.website} target="_blank" rel="noreferrer">访问公司网站 ↗</a>}</div><dl><div><dt>CEO</dt><dd>{p.ceo||'数据不足'}</dd></div><div><dt>交易所</dt><dd>{p.exchange_full_name||p.exchange||'数据不足'}</dd></div><div><dt>IPO 日期</dt><dd>{p.ipo_date||'数据不足'}</dd></div><div><dt>员工数</dt><dd>{p.employee_count?.toLocaleString()||'数据不足'}</dd></div><div><dt>本地分类</dt><dd>{localizeSector(p.local_classification.sector,'数据不足')} · {localizeIndustry(p.local_classification.industry,'数据不足')}</dd></div><div><dt>资料更新</dt><dd>{p.profile_fetched_at?formatDate(p.profile_fetched_at):'数据不足'}</dd></div></dl><section><h3>公司简介</h3><p>{p.description_zh||p.description_en||'公司简介暂不可用。'}</p>{p.description_zh&&p.description_en&&<details><summary>查看英文原文</summary><p>{p.description_en}</p></details>}{p.translation_status==='pending'&&<small>中文简介正在后台翻译，当前展示英文原文。</small>}</section></article>:<div className="empty">{profile.isLoading?'正在读取本地资料…':'公司资料尚未同步，股票其他功能不受影响。'}</div>):symbol&&<MarketSnapshot symbol={symbol}/>}</div></Sheet>
}

function TechnicalAnalysisCenter() {
  const [selected,setSelected] = useState<string|null>(null)
  const list = useQuery({queryKey:['technical-analysis'],queryFn:()=>api<TechnicalItem[]>('/technical-analysis'),staleTime:60_000})
  const detail = useQuery({queryKey:['technical-analysis',selected],queryFn:()=>api<TechnicalItem>(`/technical-analysis/${selected}`),enabled:!!selected,staleTime:60_000})
  const d=detail.data, a=d?.analysis
  const trendLabel:Record<string,string>={bullish:'偏多',bearish:'偏空',neutral:'中性'}
  const zone=(value:Zone|null|undefined)=>value?`$${value.low.toFixed(2)}–${value.high.toFixed(2)}`:'数据不足'
  return <div className="technical-workspace">
    <div className="section-title"><div><p>CACHED EOD · LOCAL CALCULATION</p><h2>交互式技术分析</h2></div><small>图表与指标来自数据库缓存，打开页面不会请求外部行情源。</small></div>
    <div className="technical-list">{list.data?.map(item=><button key={item.symbol} className={selected===item.symbol?'active':''} onClick={()=>setSelected(item.symbol)}>
      <ProfileLogo symbol={item.symbol} url={item.logo_url}/>
      <span className="tech-card-id"><b>{item.symbol}</b><small>{item.company_name||'公司资料待同步'}</small></span>
      {item.analysis?<>
        <span className="tech-card-quote"><strong>${item.analysis.latestClose.toFixed(2)}</strong><em className={`trend-${item.analysis.weeklyTrend}`}>{trendLabel[item.analysis.weeklyTrend]||item.analysis.weeklyTrend}</em></span>
        <span className="zone-mini"><small>支撑 {zone(item.analysis.nearestSupport)}</small><small>阻力 {zone(item.analysis.nearestResistance)}</small></span>
        <time>{item.data_through}{item.stale?' · 已过期':''}</time>
      </>:<em className="tech-card-pending">分析{item.status==='pending'?'排队中':'暂不可用'}</em>}
    </button>)}{list.isLoading&&<div className="empty">正在读取技术分析缓存…</div>}{!list.isLoading&&!list.data?.length&&<div className="empty">自选列表为空。</div>}</div>
    <Sheet open={selected!==null} onClose={()=>setSelected(null)} title={selected?`${selected} 技术分析`:'技术分析'} size="wide">
      {d?.status==='ready'&&a?<article className="technical-sheet">
        <header><ProfileLogo symbol={d.symbol} url={d.logo_url}/><div className="tech-sheet-id"><p className="eyebrow">WEEKLY TECHNICAL SNAPSHOT</p><h2>{d.symbol} <small>{d.company_name}</small></h2></div><strong>${a.latestClose.toFixed(2)}<small>数据截至 {d.data_through}{d.stale?' · 已过期':''}</small></strong></header>
        <div className="technical-metrics">
          <div><span>周线趋势</span><b className={`trend-${a.weeklyTrend}`}>{trendLabel[a.weeklyTrend]||a.weeklyTrend}</b></div>
          <div><span>RSI 14</span><b>{a.indicators.rsi14?.toFixed(1)||'—'}</b></div>
          <div><span>MACD</span><b>{(a.indicators.macdHistogram||0)>0?'偏多':(a.indicators.macdHistogram||0)<0?'偏空':'中性'}</b></div>
          <div><span>ATR 14</span><b>{a.indicators.atr14?.toFixed(2)||'—'}</b></div>
        </div>
        <TechnicalLevelSummary latestClose={a.latestClose} heatmap={a.historicalCausalHeatmap}/>
        <figure className="technical-chart-frame">
          <TechnicalChart
            key={d.symbol}
            symbol={d.symbol}
            series={d.chart_series||{
              day:{candles:[],moving_averages:{ma20:[],ma50:[]}},
              week:{candles:d.weekly||[],moving_averages:d.moving_averages||{ma20:[],ma50:[]}},
              month:{candles:[],moving_averages:{ma20:[],ma50:[]}},
            }}
            staticChartUrl={d.chart_url}
            heatZones={a.historicalCausalHeatmap?.currentZones}
            fibonacci={a.fibonacci}
            trendLines={a.trendLines}
            events={d.events}
            portfolioCost={d.portfolio_cost}
            initialPriceAlerts={d.price_alerts}
          />
          <figcaption>{d.chart_data_status==='ready'?'周线级别 · 数据来自本地历史缓存 · 均线由后端统一计算':'周线 OHLC 数据不足，未请求外部行情；静态缓存如可用仍可查看。'}</figcaption>
        </figure>
        <TechnicalIndicatorPositions heatmap={a.historicalCausalHeatmap}/>
        <div className="technical-columns">
          <section><h3>支撑与阻力区域</h3><div className="zone-table">{[...a.supportZones,...a.resistanceZones].map(z=><div key={`${z.type}-${z.center}`}><b className={z.type==='support'?'positive':'negative'}>{z.type==='support'?'支撑':'阻力'}</b><span>{zone(z)}</span><span>{Math.round(z.strength*100)} 分</span><span>{z.touchCount} 次触及</span><time>{z.mostRecentTouchDate}</time></div>)}{![...a.supportZones,...a.resistanceZones].length&&<p>暂无已确认的支撑或阻力区域。</p>}</div></section>
          <section><h3>斐波那契与趋势线</h3>{a.fibonacci.available?<p>{a.fibonacci.direction==='up'?'上升':'下降'}主摆动；关键回撤位由最近已确认周线枢轴确定。</p>:<p>{a.fibonacci.omissionReason}</p>}{a.trendLines.map(line=><p key={line.type}>{line.type==='rising_support'?'上升支撑线':'下降阻力线'}投影 ${line.projectedPrice.toFixed(2)} · 置信度 {Math.round(line.confidence*100)}%</p>)}{a.omittedReasons.map(reason=><small key={reason}>{reason}</small>)}</section>
        </div>
        <footer>来源：{d.chart_data_source==='yahoo'?'Yahoo':d.chart_data_source==='fmp'?'FMP':'数据不足'} 历史日线缓存；本地确定性计算 · 图表生成 {d.generated_at&&formatDate(d.generated_at)}</footer>
      </article>:<div className="empty">{detail.isLoading?'正在读取详情…':'历史数据或分析正在后台同步；已有有效缓存会继续保留。'}</div>}
    </Sheet>
  </div>
}

export default function App() {
  const previewRequested = new URLSearchParams(window.location.search).get('preview')==='1'
  const [token,setToken] = useState(()=>localStorage.getItem('auth_token')||sessionStorage.getItem('auth_token')||'')
  const [demoMode,setDemoMode] = useState(previewRequested)
  const [authUser,setAuthUser] = useState<{username:string;role:string}|null>(()=>previewRequested?{username:'访客',role:'viewer'}:null)
  const [authLoading,setAuthLoading] = useState(()=>!!(localStorage.getItem('auth_token')||sessionStorage.getItem('auth_token')))
  const [tab,setTab] = useState(()=>normalizeTab(window.location.pathname.startsWith('/admin/integrations/ibkr')?'ibkr-test':window.location.pathname==='/ibkr'?'ibkr':window.location.pathname.startsWith('/ai')?'ai':window.location.pathname.startsWith('/investment-decisions')?'decisions':new URLSearchParams(window.location.search).get('tab')||'overview'))
  const [mobileNavOpen,setMobileNavOpen] = useState(false)
  const [selectedReport,setSelectedReport] = useState<number|null>(null)
  const [selectedModel,setSelectedModel] = useState<CrossMetric|null>(null)
  const [selectedWeight,setSelectedWeight] = useState<WeightDetail|null>(null)
  const [selectedStatementMetric,setSelectedStatementMetric] = useState<StatementMetric|null>(null)
  const [selectedProfileSymbol,setSelectedProfileSymbol] = useState<string|null>(null)
  const [stocksExpanded,setStocksExpanded] = useState(false)
  const [activeTicker,setActiveTicker] = useState(()=>new URLSearchParams(window.location.search).get('symbol')||'')
  const client = useQueryClient()
  const live = !!authUser&&!demoMode
  const dashboard = useQuery({queryKey:['dashboard'],queryFn:()=>api<Dashboard>('/dashboard'),refetchInterval:30000,enabled:live})
  const indices = useQuery({queryKey:['indices'],queryFn:()=>api<Indices>('/indices'),refetchInterval:60000,enabled:live})
  const watchlist = useQuery({queryKey:['watchlist'],queryFn:()=>api<WatchItem[]>('/watchlist'),enabled:live})
  const alerts = useQuery({queryKey:['alerts'],queryFn:()=>api<Alert[]>('/alerts'),refetchInterval:30000,enabled:live})
  const investigations = useQuery({queryKey:['investigations'],queryFn:()=>api<Investigation[]>('/investigations'),refetchInterval:30000,enabled:live})
  const reports = useQuery({queryKey:['reports'],queryFn:()=>api<Report[]>('/reports'),enabled:live})
  const report = useQuery({queryKey:['report',selectedReport],queryFn:()=>api<ReportDetail>(`/reports/${selectedReport}`),enabled:live&&selectedReport!==null})
  const settings = useQuery({queryKey:['settings'],queryFn:()=>api<Settings>('/settings'),enabled:live})
  useQuery({queryKey:['portfolio-strategy-profile'],queryFn:()=>api<unknown>('/portfolio/strategy-profile'),enabled:live,staleTime:60_000})

  useEffect(()=>{
    if(demoMode){setAuthLoading(false);return}
    if(!token){setAuthUser(null);setAuthLoading(false);return}
    setAuthLoading(true)
    api<{username:string;role:string}>('/auth/me')
      .then(u=>{setAuthUser(u);setAuthLoading(false)})
      .catch(()=>{localStorage.removeItem('auth_token');sessionStorage.removeItem('auth_token');setToken('');setAuthUser(null);setAuthLoading(false)})
  },[token,demoMode])

  useEffect(()=>{
    const onLogout=()=>{setToken('');setAuthUser(null)}
    window.addEventListener('auth:logout',onLogout)
    return ()=>window.removeEventListener('auth:logout',onLogout)
  },[])

  useEffect(()=>{
    const onPop=()=>setTab(normalizeTab(window.location.pathname.startsWith('/admin/integrations/ibkr')?'ibkr-test':window.location.pathname==='/ibkr'?'ibkr':window.location.pathname.startsWith('/ai')?'ai':window.location.pathname.startsWith('/investment-decisions')?'decisions':new URLSearchParams(window.location.search).get('tab')||'overview'))
    window.addEventListener('popstate',onPop)
    return ()=>window.removeEventListener('popstate',onPop)
  },[])

  if(authLoading) return <div style={{minHeight:'100vh',display:'flex',alignItems:'center',justifyContent:'center',background:'var(--bg)',color:'var(--text-muted)'}}>加载中…</div>
  if(!authUser) return <AuthGate setToken={setToken} setAuthUser={setAuthUser} onPreview={()=>{setDemoMode(true);setAuthUser({username:'访客',role:'viewer'})}}/>

  const mobileTabs = [['overview','总览'],['watchlist','自选股'],['holdings','持仓'],['ibkr','IBKR'],['ai','Chat'],['decisions','投资决策'],['calendar','投资日历'],['discovery','机会发现'],['alerts','异动中心'],['news','新闻中心'],['fundamentals','基本面'],['macro','美国宏观'],['financials','财务报表'],['crossmodel','估值'],['technical','技术分析'],['reports','报告中心'],['journal','交易日志'],['settings','管理设置'],...(authUser.role==='admin'?[['ibkr-test','IBKR 测试']]:[])]
  const desktopNavGroups = [
    {title:'概览与资产',items:[['overview','总览'],['watchlist','自选股'],['holdings','持仓']]},
    {title:'研究与决策',items:[['ai','Chat'],['decisions','投资决策'],['calendar','投资日历'],['discovery','机会发现']]},
    {title:'市场情报',items:[['news','新闻中心'],['macro','美国宏观']]},
    {title:'公司分析',items:[['fundamentals','基本面'],['financials','财务报表'],['crossmodel','估值'],['technical','技术分析']]},
    {title:'记录与系统',items:[['reports','报告中心'],['journal','交易日志'],['settings','管理设置']]},
    {title:'IBKR',items:[['ibkr','IBKR'],...(authUser.role==='admin'?[['ibkr-test','IBKR 测试']]:[])]},
  ]
  const tabTitle = tab==='overview'?'投资组合雷达':[['watchlist','自选股管理'],['holdings','持仓'],['ibkr','IBKR 账户'],['ai','Chat'],['decisions','投资决策日志'],['calendar','投资日历'],['discovery','机会发现'],['alerts','价格异动中心'],['news','新闻中心'],['fundamentals','基本面'],['macro','美国宏观'],['financials','财务报表'],['crossmodel','估值'],['technical','技术分析'],['sec','SEC 官方公告'],['reports','智能报告'],['journal','交易日志'],['settings','管理设置'],['ibkr-test','IBKR 集成测试']].find(x=>x[0]===tab)?.[1]
  const selectTab=(key:string)=>{setTab(key);setMobileNavOpen(false);if(key==='ibkr-test')window.history.pushState({},'','/admin/integrations/ibkr');else if(key==='ibkr')window.history.pushState({},'','/ibkr');else if(key==='ai'){if(!window.location.pathname.startsWith('/ai'))window.history.pushState({},'', '/ai/new')}else if(key==='decisions')window.history.pushState({},'','/investment-decisions');else if(window.location.pathname.startsWith('/ai')||window.location.pathname.startsWith('/investment-decisions')||window.location.pathname.startsWith('/admin/integrations/ibkr')||window.location.pathname==='/ibkr')window.history.pushState({},'',`/?tab=${key}`)}
  const askAI=(symbol:string)=>{setSelectedProfileSymbol(null);setActiveTicker(symbol);setTab('ai');window.history.pushState({},'',`/ai/new?symbol=${encodeURIComponent(symbol)}&context=company`);window.dispatchEvent(new PopStateEvent('popstate'))}
  const viewDashboard = demoMode ? demoDashboard : dashboard.data
  const viewIndices = demoMode ? demoIndices : indices.data
  const viewAlerts = demoMode ? demoAlerts : alerts.data
  const viewReports = demoMode ? demoReports : reports.data
  const overviewStocks = [...(viewDashboard?.stocks||[])].sort((a,b)=>{
    const change = (stock:typeof a) => stock.price!=null&&stock.previous_close ? Math.abs((stock.price-stock.previous_close)/stock.previous_close*100) : -1
    return change(b)-change(a)
  })
  return <div className="app">
    <div className="ambient ambient-one"/><div className="ambient ambient-two"/>
    <aside className={mobileNavOpen?'mobile-open':''}>
      <div className="brand"><div className="brand-orb"><img src="/logo.png" className="brand-logo" alt="logo"/></div><div className="brand-copy"><strong>小日向美香</strong><small>Powered by 和泉妃爱</small></div><ThemeToggle className="brand-theme-toggle"/><div className="mobile-quick-stats"><span><b>{viewDashboard?.stocks.length||0}</b><small>监控</small></span><span><b>{viewAlerts?.length||0}</b><small>异动</small></span><span><b>{groupInvestigations(investigations.data).length}</b><small>调查</small></span></div><button className="mobile-menu-btn" onClick={()=>setMobileNavOpen(v=>!v)} aria-expanded={mobileNavOpen}>{mobileNavOpen?'关闭':'菜单'}</button></div>
      <nav className="desktop-nav" aria-label="主导航">{desktopNavGroups.map(group=><div className="desktop-nav-group" key={group.title}><p>{group.title}</p>{group.items.map(([key,label])=><button className={tab===key?'active':''} onClick={()=>selectTab(key)} key={key}><NavIcon name={key}/><span>{label}</span>{tab===key&&<i className="nav-active-dot"/>}</button>)}</div>)}</nav>
      <nav className="mobile-nav" aria-label="主导航">{mobileTabs.map(([key,label])=><button className={tab===key?'active':''} onClick={()=>selectTab(key)} key={key}>{key==='journal'&&<span className="nav-separator"/>}<NavIcon name={key}/><span>{label}</span>{tab===key&&<i className="nav-active-dot"/>}</button>)}</nav>
      <div className="account-card"><span className="account-avatar">{authUser.username.slice(0,1)}</span><span><b>{demoMode?'演示空间':authUser.username}</b><small>{demoMode?'本地预览模式':'已安全连接'}</small></span><i className={viewDashboard?.market.is_open?'online':''}/></div>
      <button className="logout-btn" onClick={()=>{localStorage.removeItem('auth_token');sessionStorage.removeItem('auth_token');setDemoMode(false);setToken('');setAuthUser(null)}}>{demoMode?'退出预览':'退出登录'}</button></aside>
    {mobileNavOpen&&<button className="mobile-nav-scrim" onClick={()=>setMobileNavOpen(false)} aria-label="关闭菜单"/>}
    <main className={tab==='ai'?'ai-main':''}>
      {tab!=='ai'&&tab!=='decisions'&&<header><div><p className="eyebrow">MARKET INTELLIGENCE</p><h1>{tabTitle}</h1></div><div className="header-tools"><span className="market-pill"><i className={viewDashboard?.market.is_open?'online':''}/>{viewDashboard?.market.is_open?'市场开放':'市场休市'}</span><div className="clock">{viewDashboard ? formatDate(viewDashboard.market.checked_at) : '等待同步'}</div></div></header>}
      {tab!=='ai'&&demoMode&&<div className="preview-banner"><span><b>演示预览</b> 当前展示本地示例行情，所有真实数据仍以服务端为准。</span><button onClick={()=>{setDemoMode(false);setAuthUser(null)}}>连接账户</button></div>}
      {tab!=='ai'&&!demoMode&&(dashboard.error||watchlist.error)&&<div className="error">后端暂不可用，请确认服务已启动。</div>}
      <div className="view-stage" key={tab}>
      {tab==='overview'&&<>
        <section className="hero index-hero"><div className="hero-copy"><span className={`badge${viewIndices?.market.is_open?'':' closed'}`}><i/>{viewIndices?.market.is_open?'LIVE MARKET':'MARKET CLOSED'}</span><h2>早上好，{authUser.username}</h2><p>你的市场雷达保持安静。我们只在真正值得注意时打扰你。</p></div><div className="index-row">{(viewIndices?.indices||[{symbol:'^GSPC',name:'标普500'},{symbol:'^IXIC',name:'纳斯达克'},{symbol:'^DJI',name:'道琼斯'}] as IndexQuote[]).map(idx=>{const up=idx.change_percent!=null&&idx.change_percent>=0;return <div className="index-card" key={idx.symbol}><span className="index-name">{idx.name}</span><strong>{idx.price!=null?idx.price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—'}</strong><span className={idx.change_percent==null?'':up?'positive':'negative'}>{idx.change_points==null||idx.change_percent==null?'数据不足':`${up?'+':''}${idx.change_points.toFixed(2)} (${up?'+':''}${idx.change_percent.toFixed(2)}%)`}</span></div>})}</div></section>
        <section><div className="section-title"><div><p>WATCHLIST</p><h2>市场快照</h2></div><div className="section-actions"><button className="stock-collapse-btn" onClick={()=>setStocksExpanded(v=>!v)}>{stocksExpanded?'收起':'展开更多'} <span>{stocksExpanded?'↑':'↓'}</span></button><button onClick={()=>setTab('watchlist')}>管理自选股 <span>→</span></button></div></div><div className={`stock-grid${stocksExpanded?' is-expanded':' is-collapsed'}`}>{overviewStocks.map(stock=>{const change=stock.price&&stock.previous_close?(stock.price-stock.previous_close)/stock.previous_close*100:null;return <article className="stock-card" key={stock.ticker}><div className="stock-card-head"><ProfileLogo symbol={stock.ticker} url={stock.logo_url}/><div className="stock-card-id"><span className="ticker">{stock.ticker}</span><small>{stock.updated_at?'刚刚更新':'等待首次采集'}</small></div></div><strong>{formatPrice(stock.price)}</strong><span className={change!=null&&change<0?'negative':'positive'}>{change==null?'—':`${change>=0?'+':''}${change.toFixed(2)}% 今日`}</span><button className="company-overview-btn" onClick={()=>setSelectedProfileSymbol(stock.ticker)}>公司概览</button>{stock.volume_label&&stock.volume_label!=='正常'&&<span className={`vol-tag ${stock.volume_label==='放量'?'heavy':'light'}`}>{stock.volume_label} · {stock.volume_ratio?.toFixed(2)}×</span>}<div className="card-glow"/></article>})}{!overviewStocks.length&&<div className="empty">添加第一只股票，开始建立你的市场雷达。</div>}</div></section>
        <TradingViewStockHeatmap/>
        <section className="split"><div><div className="section-title"><div><p>SIGNALS</p><h2>最近异动</h2></div><button className="overview-alerts-link" onClick={()=>selectTab('alerts')}>查看异动中心 <span>→</span></button></div>{viewAlerts?.slice(0,5).map(a=><div className="list-row" key={a.id}><span className="signal-symbol">{a.ticker.slice(0,1)}</span><b>{a.ticker}</b><span>{a.period}</span><em className={a.change_percent<0?'negative':'positive'}>{a.change_percent>=0?'+':''}{a.change_percent.toFixed(2)}%</em></div>)}</div><div><div className="section-title"><div><p>INTELLIGENCE</p><h2>最新报告</h2></div></div>{viewReports?.slice(0,5).map(r=><button className="report-row" key={r.id} onClick={()=>!demoMode&&setSelectedReport(r.id)}><span>{typeNames[r.report_type]||r.report_type}</span><b>{r.title}</b><small>{demoMode?'刚刚生成':formatDate(r.created_at)}</small></button>)}</div></section>
      </>}
      {tab==='watchlist'&&<StockManagement onWatchlistChanged={()=>{client.invalidateQueries({queryKey:['watchlist']});client.invalidateQueries({queryKey:['dashboard']})}}/>}
      {tab==='holdings'&&<PortfolioModule/>}
      {tab==='ibkr'&&<IbkrAccount/>}
      {tab==='ai'&&<AIChatPage enabled={!demoMode}/>}
      {tab==='decisions'&&<InvestmentDecisionsPage/>}
      {tab==='calendar'&&<InvestmentCalendar/>}
      {tab==='discovery'&&<OpportunityDiscovery/>}
      {tab==='alerts'&&<div className="investigations">{groupInvestigations(investigations.data).map(group=><article key={group.key}><div><span className={`status ${group.status}`}>{group.status}</span><h2>{group.ticker} 异动调查{group.items.length>1&&<em className="group-count"> ×{group.items.length}</em>}</h2><p>{formatDate(group.started_at)} — {formatDate(group.ends_at)}</p></div><strong>{group.news_count}<small> 条新闻线索</small></strong>{group.last_error&&<p className="error">{group.last_error}</p>}</article>)}{!investigations.data?.length&&<div className="empty">尚未触发价格异动调查。</div>}</div>}
      {tab==='reports'&&<div className="report-grid">{reports.data?.map(r=><button className={`report-tile${selectedReport===r.id?' selected':''}`} key={r.id} onClick={()=>setSelectedReport(r.id)}><span className="report-tag">{typeNames[r.report_type]||r.report_type}{r.confidence&&<><span className="report-tag-sep">|</span><span className={`report-conf conf-${r.confidence==='高'?'high':r.confidence==='中'?'mid':'low'}`}>置信度{r.confidence}</span></>}</span><b>{r.title}</b><small>{formatDate(r.created_at)}</small></button>)}{!reports.data?.length&&<div className="empty">暂无报告。</div>}</div>}
      {tab==='news'&&<NewsCenter tickers={watchlist.data?.map(w=>w.ticker)||[]} active={activeTicker} setActive={setActiveTicker}/>}
      {tab==='fundamentals'&&<FundamentalsCenter tickers={watchlist.data?.map(w=>w.ticker)||[]} active={activeTicker} setActive={setActiveTicker} onOpenSec={()=>selectTab('sec')}/>}
      {tab==='macro'&&<MacroFundamentals isAdmin={authUser.role==='admin'}/>}
      {tab==='financials'&&<FinancialStatementsCenter tickers={watchlist.data?.map(w=>w.ticker)||[]} onStatementMetric={setSelectedStatementMetric} active={activeTicker} setActive={setActiveTicker}/>}
      {tab==='crossmodel'&&<CrossModelCenter tickers={watchlist.data?.map(w=>w.ticker)||[]} onMetric={setSelectedModel} onWeight={setSelectedWeight} active={activeTicker} setActive={setActiveTicker}/>}
      {tab==='technical'&&<TechnicalAnalysisCenter/>}
      {tab==='sec'&&<SecCenter tickers={watchlist.data?.map(w=>w.ticker)||[]} active={activeTicker} setActive={setActiveTicker}/>}
      {tab==='journal'&&authUser&&<JournalSection username={authUser.username}/>}
      {tab==='settings'&&<>{settings.data&&<SettingsForm initial={settings.data} onSaved={()=>client.invalidateQueries({queryKey:['settings']})}/>}<AdanosQuotaPanel/><CongressSettings/><RealtimeProviderHealthPanel/><MacroDataSourcePanel isAdmin={authUser.role==='admin'}/><DiscoverySettingsPanel/>{authUser.role==='admin'&&<AdminOperationsPanel/>}</> }
      {tab==='ibkr-test'&&authUser.role==='admin'&&<IbkrIntegrationTest/>}
      </div>
    </main>
    <Sheet open={selectedReport!==null} onClose={()=>setSelectedReport(null)} title={report.data?typeNames[report.data.report_type]||report.data.report_type:'报告'}>
      {report.data?<article className="report-detail sheet-report"><p className="eyebrow">{typeNames[report.data.report_type]} · {report.data.model}</p><h2>{report.data.title}</h2><div className="report-content"><ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{report.data.content}</ReactMarkdown></div><h3>信息来源</h3>{report.data.sources.map((s,i)=><a href={s.url} target="_blank" rel="noreferrer" key={i}>{i+1}. {s.title}</a>)}</article>:<div className="empty">加载中…</div>}
    </Sheet>
    <CompanyProfileSheet symbol={selectedProfileSymbol} onClose={()=>setSelectedProfileSymbol(null)} onAskAI={askAI}/>
    <Sheet open={selectedModel!==null} onClose={()=>setSelectedModel(null)} title={selectedModel?.label||'指标说明'}>
      {selectedModel&&<article className="model-drawer"><p className="eyebrow">MODEL EXPLAINER · 指标学习</p><h2>{selectedModel.label}</h2><strong>{formatCrossMetric(selectedModel)}</strong>{selectedModel.applicability&&<div className={`applicability ${selectedModel.applicability}`}>适用性：{{medium:'中',low:'低',not_applicable:'不适用'}[selectedModel.applicability]}</div>}{selectedModel.peer_median!=null&&<div className="drawer-peer"><span>同行中位数</span><b>{selectedModel.peer_median.toFixed(2)}{selectedModel.unit==='multiple'?'×':selectedModel.unit==='%'?'%':''}</b><em>{selectedModel.comparison}</em></div>}<p>{selectedModel.explanation}</p>{selectedModel.missing_fields?.length?<div className="missing-data"><b>{selectedModel.status==='not_applicable'?'不适用':'数据不足'}</b><p>{selectedModel.status==='not_applicable'?'该公司类型不使用此模型。':`缺少：${selectedModel.missing_fields.map(fieldLabel).join('、')}`}</p></div>:null}{selectedModel.warnings?.map(warning=><div className="metric-warning" key={warning}>{warning}</div>)}<div className="learn-block"><b>公式 Formula</b><p>{selectedModel.formula}</p></div><div className="learn-block"><b>参考区间 Reference Range</b><p>{selectedModel.recommended_range}</p></div>{selectedModel.note&&<div className="explainer"><b>计算说明</b><p>{selectedModel.note}</p></div>}</article>}
    </Sheet>
    <Sheet open={selectedWeight!==null} onClose={()=>setSelectedWeight(null)} title={selectedWeight?.label||'权重来源'}>
      {selectedWeight&&<article className="weight-drawer"><p className="eyebrow">WEIGHT EVIDENCE · 权重证据</p><h2>{selectedWeight.label}</h2><div className="weight-result"><span>基础分 <b>{selectedWeight.base_score}</b></span><span>最终权重 <strong>{(selectedWeight.weight*100).toFixed(0)}%</strong></span></div><div className="weight-evidence-list">{selectedWeight.adjustments.map(a=><div key={`${a.tag}${a.raw_adjustment}`}><span>✓ {a.label}<small>置信度 {Math.round(a.confidence*100)}%</small></span><b className={a.applied_adjustment<0?'negative':'positive'}>{a.applied_adjustment>=0?'+':''}{a.applied_adjustment}</b></div>)}{!selectedWeight.adjustments.length&&<div className="empty">当前仅使用基础权重。</div>}</div><div className="weight-final">调整后得分 <b>{selectedWeight.final_score}</b><span>归一化后</span><strong>{(selectedWeight.weight*100).toFixed(0)}%</strong></div></article>}
    </Sheet>
    <Sheet open={selectedStatementMetric!==null} onClose={()=>setSelectedStatementMetric(null)} title={selectedStatementMetric?.label||'指标说明'}>
      {selectedStatementMetric&&<article className="statement-explainer"><p className="eyebrow">FINANCIAL STATEMENT · 指标释义</p><h2>{selectedStatementMetric.label}</h2><p className="statement-english">{selectedStatementMetric.english}</p><div className="learn-block"><b>这是什么</b><p>{selectedStatementMetric.description}</p></div><div className="learn-block"><b>对分析有什么影响</b><p>{selectedStatementMetric.impact}</p></div>{selectedStatementMetric.formula&&<div className="learn-block"><b>计算方式</b><p>{selectedStatementMetric.formula}</p></div>}<p className="statement-source">数据源：Yahoo Finance / yfinance。缺失字段会显示“数据不足”，不会以估算值替代。</p></article>}
    </Sheet>
  </div>
}

const grahamStatusLabel:Record<GrahamStatus,string> = {undervalued:'Undervalued · 低估',fairly_valued:'Fairly Valued · 合理',overvalued:'Overvalued · 偏贵',not_applicable:'Not Applicable · 不适用'}
const grahamQualityLabel:Record<string,string> = {reported:'Reported · 财报值',calculated:'Calculated · 计算值',estimated:'Estimated · 估算值',historical:'Historical · 历史值',analyst_estimate:'Analyst Estimate · 分析师预期',market_data:'Market Data · 市场数据',user_input:'User Input · 用户输入',missing:'Unavailable · 缺失'}

function GrahamPanel({ticker,initial}:{ticker:string;initial:GrahamAnalysis}) {
  const [result,setResult] = useState<GrahamAnalysis|null>(null)
  const [growth,setGrowth] = useState('')
  const [aaaYield,setAaaYield] = useState('')
  const [normalizedEps,setNormalizedEps] = useState('')
  useEffect(()=>{setResult(null);setGrowth('');setAaaYield('');setNormalizedEps('')},[ticker,initial.updated_at])
  const applyOverride = useMutation({
    mutationFn:()=>post<GrahamAnalysis>(`/cross-model/graham?ticker=${ticker}`,{
      growth_rate:growth===''?null:Number(growth),aaa_yield:aaaYield===''?null:Number(aaaYield),normalized_eps:normalizedEps===''?null:Number(normalizedEps),
    }),
    onSuccess:setResult,
  })
  const data = result||initial
  const money = (value:number|null) => value==null?'数据不足':new Intl.NumberFormat('en-US',{style:'currency',currency:data.currency||'USD',maximumFractionDigits:2}).format(value)
  const percent = (value:number|null) => value==null?'—':`${(value*100).toFixed(1)}%`
  const points = [
    ['eps_ttm','EPS TTM',data.inputs.eps_ttm],['book_value_per_share','BVPS',data.inputs.book_value_per_share],
    ['growth_rate','Growth Rate · 采用增长率',data.inputs.growth_rate],['aaa_yield','AAA Yield · 公司债收益率',data.inputs.aaa_yield],
  ] as const
  const reset = () => {setResult(null);setGrowth('');setAaaYield('');setNormalizedEps('')}
  return <section className="graham-section">
    <div className="section-title"><div><h2>Graham Analysis（格莱厄姆估值）</h2><small>历史盈利与账面价值模型 · 不构成投资建议</small></div><span className={`graham-applicability ${data.applicability.status}`}>{{applicable:'适用',limited:'有限适用',not_applicable:'不适用'}[data.applicability.status]}</span></div>
    <div className="graham-summary">
      <div><span>Current Price（现价）</span><strong>{money(data.current_price)}</strong><small>{data.inputs.current_price.source}</small></div>
      <div><span>Graham Number</span><strong>{money(data.graham_number.value)}</strong><small>安全边际 {percent(data.graham_number.margin_of_safety)}</small></div>
      <div><span>Base Growth Value（基准成长估值）</span><strong>{money(data.growth_formula.base.intrinsic_value)}</strong><small>增长率 {data.growth_formula.base.growth_rate==null?'—':`${data.growth_formula.base.growth_rate.toFixed(1)}%`}</small></div>
      <div className={`graham-verdict ${data.overall_status}`}><span>Composite Status（综合状态）</span><strong>{grahamStatusLabel[data.overall_status]}</strong><small>仅为模型比较，不是买卖信号</small></div>
    </div>
    <div className="graham-scenario-wrap"><table className="graham-scenario-table"><thead><tr><th>Scenario</th><th>Growth Rate</th><th>Intrinsic Value</th><th>Margin of Safety</th><th>Valuation Status</th></tr></thead><tbody>{(['conservative','base','optimistic'] as const).map(key=>{const row=data.growth_formula[key];return <tr key={key}><td>{{conservative:'Conservative（保守）',base:'Base（基准）',optimistic:'Optimistic（乐观）'}[key]}</td><td>{row.growth_rate==null?'—':`${row.growth_rate.toFixed(1)}%`}</td><td>{money(row.intrinsic_value)}</td><td className={(row.margin_of_safety||0)>=0?'positive':'negative'}>{percent(row.margin_of_safety)}</td><td><span className={`graham-status ${row.status}`}>{grahamStatusLabel[row.status]}</span></td></tr>})}</tbody></table></div>
    <div className="graham-detail-grid">
      <div className="graham-inputs"><div className="section-title"><h3>Inputs & Sources（输入与来源）</h3><small>财报值、计算值和估算值分开展示</small></div>{points.map(([key,label,point])=><div className="graham-input-row" key={key}><span>{label}</span><b>{point.value==null?'数据不足':`${point.value.toFixed(2)}${key==='growth_rate'||key==='aaa_yield'?'%':''}`}</b><em>{point.source}</em><small>{point.as_of||'日期不可用'}</small><i>{grahamQualityLabel[point.quality]||point.quality}</i></div>)}</div>
      <form className="graham-overrides" onSubmit={event=>{event.preventDefault();applyOverride.mutate()}}><div className="section-title"><h3>User Override（用户覆盖）</h3><small>仅临时重算，不修改原始快照</small></div><label>增长率 %（-4 至 15）<input type="number" min="-4" max="15" step="0.1" value={growth} onChange={e=>setGrowth(e.target.value)} placeholder="使用默认来源"/></label><label>AAA Yield %（可选）<input type="number" min="0.01" step="0.01" value={aaaYield} onChange={e=>setAaaYield(e.target.value)} placeholder="使用 FRED DAAA"/></label><label>Normalized EPS（可选）<input type="number" min="0.01" step="0.01" value={normalizedEps} onChange={e=>setNormalizedEps(e.target.value)} placeholder="使用 EPS TTM"/></label><div><button type="submit" disabled={applyOverride.isPending}>{applyOverride.isPending?'计算中…':'应用覆盖'}</button><button type="button" className="ghost-btn" onClick={reset}>恢复默认</button></div>{applyOverride.isError&&<p>输入无效或重算失败，请检查数值。</p>}</form>
    </div>
    {(data.applicability.reasons.length>0||data.applicability.missing_fields.length>0)&&<div className="graham-notes"><b>模型适用性说明</b>{data.applicability.reasons.map(reason=><p key={reason}>• {reason}</p>)}</div>}
    <div className="graham-disclaimer">格莱厄姆估值依赖历史盈利、账面价值和增长率假设。该模型不适用于所有行业，也不构成投资建议。<span>公式：√(22.5 × EPS TTM × BVPS)；EPS × (8.5 + 2g) × 4.4 ÷ AAA Yield</span></div>
  </section>
}

function CrossModelCenter({tickers,onMetric,onWeight,active,setActive}:{tickers:string[];onMetric:(metric:CrossMetric)=>void;onWeight:(weight:WeightDetail)=>void;active:string;setActive:(ticker:string)=>void}) {
  const [editingPeers,setEditingPeers] = useState(false)
  const [peerSecurity,setPeerSecurity] = useState<SecuritySearchResult|null>(null)
  const current = active||tickers[0]||''
  const client = useQueryClient()
  const result = useQuery({queryKey:['cross-model',current],queryFn:()=>api<CrossModel>(`/cross-model?ticker=${current}`),enabled:!!current,refetchInterval:current?60000:false})
  const peerList = useQuery({queryKey:['peers',current],queryFn:()=>api<PeerList>(`/peers/${current}`),enabled:!!current&&editingPeers})
  const refresh = useMutation({mutationFn:()=>post(`/cross-model/refresh?ticker=${current}`,{}),onSuccess:()=>setTimeout(()=>client.invalidateQueries({queryKey:['cross-model',current]}),12000)})
  const peersChanged = () => {client.invalidateQueries({queryKey:['peers',current]});client.invalidateQueries({queryKey:['stock-management']});setTimeout(()=>client.invalidateQueries({queryKey:['cross-model',current]}),12000)}
  const addPeer = useMutation({mutationFn:()=>post(`/peers/${current}`,securityPayload(peerSecurity!)),onSuccess:()=>{setPeerSecurity(null);peersChanged()}})
  const removePeer = useMutation({mutationFn:(item:PeerItem)=>item.source==='manual'?api(`/peers/${current}/${item.ticker}`,{method:'DELETE'}):post(`/peers/${current}/${item.ticker}/exclude`,{}),onSuccess:peersChanged})
  const restorePeer = useMutation({mutationFn:(ticker:string)=>api(`/peers/${current}/${ticker}/exclude`,{method:'DELETE'}),onSuccess:peersChanged})
  const movePeer = async (item:PeerItem,delta:number) => {await patch(`/peers/${current}/${item.ticker}/order`,{display_order:Math.max(0,item.display_order+delta)});peersChanged()}
  const data = result.data
  const MetricGroup = ({title,subtitle,items,tone}:{title:string;subtitle:string;items:CrossMetric[];tone:string}) => <section className={`cross-group ${tone}`}><div className="section-title"><h2>{title}</h2><small>{subtitle}</small></div><div className="cross-metric-grid">{items.map(item=><button key={item.key} className={`cross-metric ${item.status}`} onClick={()=>onMetric(item)}><span>{item.label}</span><strong>{formatCrossMetric(item)}</strong>{item.peer_median!=null?<div className="peer-compare"><small>同行中位数</small><b>{item.peer_median.toFixed(2)}{item.unit==='multiple'?'×':item.unit==='%'?'%':''}</b><em className={(item.peer_delta_percent||0)>0?'negative':'positive'}>{item.comparison}</em></div>:<small>{metricHint(item)}</small>}<i aria-hidden="true">→</i></button>)}</div></section>
  const consensusGap = data?.consensus.value!=null&&data.consensus.current!=null&&data.consensus.current!==0?(data.consensus.value-data.consensus.current)/data.consensus.current*100:null
  return <div className="news-center cross-model">
    <SnapshotTickerBar section="valuation" tickers={tickers} current={current} onSelect={setActive}/>
    {!current&&<div className="empty">搜索并选择证券，生成仅保留一天的临时估值快照。</div>}
    {result.isLoading&&<div className="empty">正在读取每日估值快照…</div>}{result.isError&&<div className="snapshot-empty"><p>该股票还没有每日估值快照。</p><button onClick={()=>refresh.mutate()} disabled={refresh.isPending}>{refresh.isPending?'正在抓取同行与估值…':'立即生成'}</button></div>}
    {data&&<><section className="cross-hero"><div><p className="eyebrow">{localizeSector(data.classification.sector)} · {localizeIndustry(data.classification.industry,'数据不足')}</p><h2>{data.company} <span>{data.classification.label}</span></h2><p>主模型：{data.classification.primary.map(modelLabel).join('、')||'数据不足'}　·　辅助模型：{data.classification.secondary.map(modelLabel).join('、')||'—'}</p><div className="tag-row">{data.tags.filter(t=>!t.name.includes(':')).map(t=><span key={t.name}>{t.label} <b>{Math.round(t.confidence*100)}%</b></span>)}</div></div><div className="valuation-focus"><small>本次估值重点</small><b>{data.classification.focus}</b></div></section>
      <section className="valuation-glance" aria-label="估值摘要"><div><span>当前市场价格</span><strong>{data.consensus.current==null?'数据不足':`$${data.consensus.current.toFixed(2)}`}</strong><small>市场正在支付的价格</small></div><div><span>模型估值共识</span><strong>{data.consensus.value==null?'数据不足':`$${data.consensus.value.toFixed(2)}`}</strong><small>{data.consensus.items.length} 个独立模型参与</small></div><div className={consensusGap==null?'':consensusGap>=0?'positive':'negative'}><span>共识相对现价</span><strong>{consensusGap==null?'数据不足':`${consensusGap>=0?'+':''}${consensusGap.toFixed(1)}%`}</strong><small>仅表示模型差值，不是预期收益</small></div><div><span>模型一致性</span><strong>{data.model_conflict?'存在分歧':'方向一致'}</strong><small>{data.peers.coverage}/{data.peers.symbols.length} 家同行可比</small></div></section>
      <section className="peer-strip"><div><span>同行公司</span><small>{data.peers.coverage}/{data.peers.symbols.length} 家具备可比数据</small></div><div>{data.peers.symbols.map(symbol=><b key={symbol}>{symbol}</b>)}{!data.peers.symbols.length&&<em>同行数据不足</em>}<button className="peer-edit-btn" onClick={()=>setEditingPeers(value=>!value)}>{editingPeers?'收起编辑':'编辑同行'}</button></div></section>
      {editingPeers&&<section className="peer-editor"><form onSubmit={event=>{event.preventDefault();if(peerSecurity)addPeer.mutate()}}><SecuritySearchAutocomplete value={peerSecurity} onSelect={setPeerSecurity} excludeSymbols={[current]} disabledSymbols={peerList.data?.items.filter(item=>!item.excluded).map(item=>item.ticker)||[]} placeholder="搜索同行代码或公司名称"/><button disabled={!peerSecurity||addPeer.isPending}>添加同行</button></form>{addPeer.error&&<p className="error">{addPeer.error.message}</p>}<div>{peerList.data?.items.map(item=><article key={`${item.source}-${item.ticker}`} className={item.excluded?'excluded':''}><span><b>{item.ticker}</b><small>{item.is_watchlisted?'自选股':'匹配股票'} · {item.source==='official'?'官方同行':'手动同行'}</small></span>{item.source==='manual'&&<div><button onClick={()=>movePeer(item,-1)}>↑</button><button onClick={()=>movePeer(item,1)}>↓</button></div>}{item.excluded?<button onClick={()=>restorePeer.mutate(item.ticker)}>恢复默认</button>:<button onClick={()=>removePeer.mutate(item)}>{item.source==='official'?'排除':'删除'}</button>}</article>)}</div><small>官方同行来自 Finnhub；这里仅保存手动新增、排除与排序，不修改官方行业分类。</small></section>}
      <div className="valuation-chapter"><MetricGroup tone="pricing" title="市场定价与相对估值" subtitle="与同行和自身经营尺度比较" items={data.valuation}/><MetricGroup tone="growth" title="增长能力" subtitle="判断增长速度、质量与可持续性" items={data.growth}/><MetricGroup tone="quality" title="财务质量与资本效率" subtitle="检查盈利、偿债与资本使用效率" items={data.health}/></div>
      {data.graham?<GrahamPanel ticker={current} initial={data.graham}/>:<section className="graham-section graham-empty"><h2>Graham Analysis（格莱厄姆估值）</h2><p>当前是旧版估值快照，请点击底部“刷新今日数据”生成 Graham 数据。</p></section>}
      <div className="valuation-pair"><section className="scenario-section"><div className="section-title"><h2>DCF 情景估值</h2><small>区间比单一数字更重要</small></div><div className="scenario-grid">{(['bear','base','bull','current'] as const).map(key=><div key={key} className={key}><span>{{bear:'悲观情景',base:'基准情景',bull:'乐观情景',current:'当前价格'}[key]}</span><strong>{data.dcf_scenarios[key]==null?'数据不足':`$${data.dcf_scenarios[key]!.toFixed(2)}`}</strong>{key!=='current'&&data.dcf_scenarios.assumptions[key]&&<small>增长 {data.dcf_scenarios.assumptions[key].growth}% · 折现 {data.dcf_scenarios.assumptions[key].discount_rate}%</small>}</div>)}</div>{data.reverse_dcf.implied_fcf_growth!=null&&<p className="reverse-dcf">反向 DCF：现价隐含未来五年 FCF 年增长约 <b>{data.reverse_dcf.implied_fcf_growth}%</b></p>}</section><section className="consensus-section"><div className="section-title"><h2>估值共识</h2><small>只聚合独立可计算的公允价值</small></div><div className="consensus-list">{data.consensus.items.map(item=><div key={item.key}><span>{item.label}</span><b>${item.value.toFixed(2)}</b></div>)}<div className="consensus-final"><span>估值共识</span><strong>{data.consensus.value==null?'数据不足':`$${data.consensus.value.toFixed(2)}`}</strong></div></div></section></div>
      <div className="valuation-evidence"><section className="signal-section"><div className="section-title"><h2>模型交叉验证</h2><small>{data.model_conflict?'存在分歧':'方向一致'}</small></div><div className="signal-grid">{data.model_signals.map(signal=><div key={signal.key}><span>{signal.label}</span><b>{signal.verdict}</b><em>{'★'.repeat(signal.stars)}{'☆'.repeat(5-signal.stars)}</em><small>{signal.detail}</small></div>)}</div></section><section className="cross-weights"><div className="section-title"><h2>模型权重</h2><small>点击查看证据</small></div>{data.weight_details.filter(item=>item.weight>0).sort((a,b)=>b.weight-a.weight).map(item=><button key={item.key} onClick={()=>onWeight(item)}><span>{item.label}</span><i><b style={{width:`${item.weight*100}%`}}/></i><em>{(item.weight*100).toFixed(0)}%</em><small>来源 →</small></button>)}</section></div>
      <section className="ai-opinion"><div><span>Luna 分析师解释</span><small>{data.model_conflict?'模型存在分歧，Luna 解释分歧来自哪里。':'主要模型方向较一致，Luna 概括共同证据。'}</small></div><p>{data.ai_opinion}</p><footer>数值全部由确定性公式计算，AI 不参与计算。{data.ai_model&&` · ${data.ai_model}`}</footer></section>
      <div className="snapshot-footer"><span>数据快照：{data.snapshot_date}</span><button onClick={()=>refresh.mutate()} disabled={refresh.isPending}>{refresh.isPending?'更新中…':'刷新今日数据'}</button></div></>}
  </div>
}

function modelLabel(key:string) { return ({forward_pe:'Forward PE',peg:'PEG',ev_sales:'EV/Sales',ev_ebitda:'EV/EBITDA',dcf:'DCF',fcf_yield:'FCF Yield',price_to_book:'P/B',rule_of_40:'Rule of 40',roe:'ROE',roic:'ROIC'} as Record<string,string>)[key]||key }

function formatCrossMetric(item:CrossMetric) {
  if(item.status==='not_applicable') return '不适用'
  if(item.display) return item.display
  if(item.value==null) return '数据不足'
  return `${item.value.toLocaleString('en-US',{maximumFractionDigits:2})}${item.unit==='multiple'?'×':item.unit==='%'?'%':item.unit==='score'?'':` ${item.unit}`}`
}

function metricHint(item:CrossMetric) {
  if(item.status==='not_applicable') return '该公司类型不适用'
  if(item.status==='partial') return `部分数据 · ${item.available_components||0}/${item.total_components||9} 项可计算`
  if(item.status==='available') return '查看说明与参考值 →'
  return item.missing_fields?.length?`缺少 ${item.missing_fields.slice(0,2).map(fieldLabel).join('、')}`:'当前数据不足'
}

function StockManagement({onWatchlistChanged}:{onWatchlistChanged:()=>void}) {
  const client = useQueryClient()
  const [newSecurity,setNewSecurity] = useState<SecuritySearchResult|null>(null)
  const [groupName,setGroupName] = useState('')
  const [selected,setSelected] = useState<ManagedStock|null>(null)
  const [collapsed,setCollapsed] = useState<Record<string,boolean>>({})
  const management = useQuery({queryKey:['stock-management'],queryFn:()=>api<StockManagementData>('/stock-management')})
  const refresh = () => {client.invalidateQueries({queryKey:['stock-management']});onWatchlistChanged()}
  const add = useMutation({mutationFn:()=>post('/watchlist',securityPayload(newSecurity!)),onSuccess:()=>{setNewSecurity(null);refresh()}})
  const addGroup = useMutation({mutationFn:()=>post('/stock-groups',{name:groupName}),onSuccess:()=>{setGroupName('');client.invalidateQueries({queryKey:['stock-management']})}})
  const remove = useMutation({mutationFn:(id:number)=>api(`/watchlist/${id}`,{method:'DELETE'}),onSuccess:()=>{setSelected(null);refresh()}})
  const promote = useMutation({mutationFn:(value:string)=>post('/watchlist',{ticker:value}),onSuccess:()=>{setSelected(null);refresh()}})
  const update = useMutation({mutationFn:({id,body}:{id:number;body:Record<string,unknown>})=>patch(`/watchlist/${id}`,body),onSuccess:()=>{client.invalidateQueries({queryKey:['stock-management']});client.invalidateQueries({queryKey:['watchlist']})}})
  const data = management.data
  const groupMap = new Map(data?.groups.map(group=>[group.id,group.name]))
  const sections = new Map<string,ManagedStock[]>()
  for(const stock of data?.watchlisted||[]) {
    const key = stock.user_group_id ? `自定义 · ${groupMap.get(stock.user_group_id)||'未知分区'}` : `${localizeSector(stock.official_sector)} · ${localizeIndustry(stock.official_industry)}`
    sections.set(key,[...(sections.get(key)||[]),stock])
  }
  const moveSelected = (group:string) => {
    if(!selected?.watchlist_id) return
    update.mutate({id:selected.watchlist_id,body:{user_group_id:group===''?null:Number(group)}})
    setSelected({...selected,user_group_id:group===''?null:Number(group)})
  }
  const renameGroup = async (id:number,name:string) => {
    const next = window.prompt('新的分区名称',name)?.trim()
    if(next) {await patch(`/stock-groups/${id}`,{name:next});client.invalidateQueries({queryKey:['stock-management']})}
  }
  const deleteGroup = async (id:number) => {
    try {await api(`/stock-groups/${id}`,{method:'DELETE'});client.invalidateQueries({queryKey:['stock-management']})}
    catch(error) {window.alert(error instanceof Error?error.message:'无法删除分区')}
  }
  const StockNote = ({stock,index,matched=false}:{stock:ManagedStock;index:number;matched?:boolean}) => <button key={stock.ticker} className={`managed-stock-note note-tone-${index%4}${matched?' matched':''}`} onClick={()=>setSelected(stock)} title={stock.company_name||stock.ticker}><span className="stock-note-ticker">{stock.ticker}</span><small>{stock.company_name||'公司资料待同步'}</small></button>
  return <div className="stock-manager">
    <section className="stock-manager-intro"><div><h2>自选股概览</h2></div><dl><div><dt>自选股</dt><dd>{data?.watchlisted.length||0}</dd></div><div><dt>观察分区</dt><dd>{sections.size}</dd></div><div><dt>同行样本</dt><dd>{data?.matched.length||0}</dd></div></dl></section>
    <div className="stock-manager-tools">
      <form className="add-form" onSubmit={event=>{event.preventDefault();if(newSecurity)add.mutate()}}><SecuritySearchAutocomplete label="添加公司" value={newSecurity} onSelect={setNewSecurity} disabledSymbols={data?.watchlisted.map(stock=>stock.ticker)||[]} placeholder="搜索股票代码或公司名称"/><button disabled={!newSecurity||add.isPending}>{add.isPending?'正在同步…':'添加到自选股'}</button></form>
      <form className="group-form" onSubmit={event=>{event.preventDefault();if(groupName.trim())addGroup.mutate()}}><div><label>新建个人分区</label><input value={groupName} onChange={event=>setGroupName(event.target.value)} placeholder="例如：长期复利、等待回调"/></div><button disabled={addGroup.isPending}>创建分区</button></form>
    </div>
    {(add.error||addGroup.error)&&<p className="error">{(add.error||addGroup.error)?.message}</p>}
    {!!data?.groups.length&&<div className="custom-group-admin"><span className="group-admin-label">个人分区</span>{data.groups.map(group=><span key={group.id}><b>{group.name}</b><button aria-label={`${group.name} 上移`} onClick={async()=>{await patch(`/stock-groups/${group.id}`,{display_order:Math.max(0,group.display_order-1)});client.invalidateQueries({queryKey:['stock-management']})}}>↑</button><button aria-label={`${group.name} 下移`} onClick={async()=>{await patch(`/stock-groups/${group.id}`,{display_order:group.display_order+1});client.invalidateQueries({queryKey:['stock-management']})}}>↓</button><button onClick={()=>renameGroup(group.id,group.name)}>重命名</button><button className="group-delete" onClick={()=>deleteGroup(group.id)}>删除</button></span>)}</div>}
    <div className="stock-note-board">{[...sections.entries()].map(([name,stocks],sectionIndex)=><section className={`stock-section board-tone-${sectionIndex%3}`} key={name}><button className="stock-section-head" onClick={()=>setCollapsed(value=>({...value,[name]:!value[name]}))}><span><i aria-hidden="true"/>{name}</span><b>{stocks.length} 只 <em>{collapsed[name]?'展开':'收起'}</em></b></button>{!collapsed[name]&&<div className="managed-stock-list">{stocks.map((stock,index)=><StockNote key={stock.ticker} stock={stock} index={index}/>)}</div>}</section>)}</div>
    <section className="stock-section matched-section"><button className="stock-section-head" onClick={()=>setCollapsed(value=>({...value,matched:!value.matched}))}><span><i aria-hidden="true"/>估值同行样本</span><b>{data?.matched.length||0} 只 <em>{collapsed.matched?'展开':'收起'}</em></b></button><p className="matched-section-note">这些公司只参与同行比较，不进入你的日常自选股监控。</p>{!collapsed.matched&&<div className="managed-stock-list">{data?.matched.map((stock,index)=><StockNote key={stock.ticker} stock={stock} index={index} matched/>)}{!data?.matched.length&&<div className="empty">暂无仅用于估值比较的股票。</div>}</div>}</section>
    <Sheet open={selected!==null} onClose={()=>setSelected(null)} title={selected?.ticker||'股票设置'}>{selected&&<article className="stock-settings"><p className="eyebrow">{selected.is_watchlisted?'WATCHLIST · 自选股':'MATCHED PEER · 匹配股票'}</p><h2>{selected.ticker} <small>{selected.company_name||'公司资料待同步'}</small></h2><dl><div><dt>官方行业分类</dt><dd>{localizeSector(selected.official_sector,'数据不足')}</dd></div><div><dt>细分行业</dt><dd>{localizeIndustry(selected.official_industry,'数据不足')}</dd></div></dl>{selected.is_watchlisted&&selected.watchlist_id?<><label>显示分区<select value={selected.user_group_id??''} onChange={event=>moveSelected(event.target.value)}><option value="">恢复官方分类</option>{data?.groups.map(group=><option key={group.id} value={group.id}>{group.name}</option>)}</select></label><div className="stock-order-actions"><button onClick={()=>update.mutate({id:selected.watchlist_id!,body:{display_order:Math.max(0,selected.display_order-1)}})}>上移</button><button onClick={()=>update.mutate({id:selected.watchlist_id!,body:{display_order:selected.display_order+1}})}>下移</button></div><label className="alert-toggle"><input type="checkbox" checked={selected.alert_enabled} onChange={event=>{update.mutate({id:selected.watchlist_id!,body:{alert_enabled:event.target.checked}});setSelected({...selected,alert_enabled:event.target.checked})}}/> 波动报警</label><div className="threshold-tags"><ThresholdCell item={{id:selected.watchlist_id,ticker:selected.ticker,enabled:true,alert_enabled:selected.alert_enabled,user_group_id:selected.user_group_id,display_order:selected.display_order,threshold_20m:selected.threshold_20m,threshold_1h:selected.threshold_1h,threshold_day:selected.threshold_day}} field="threshold_20m" onSaved={refresh}/><ThresholdCell item={{id:selected.watchlist_id,ticker:selected.ticker,enabled:true,alert_enabled:selected.alert_enabled,user_group_id:selected.user_group_id,display_order:selected.display_order,threshold_20m:selected.threshold_20m,threshold_1h:selected.threshold_1h,threshold_day:selected.threshold_day}} field="threshold_1h" onSaved={refresh}/><ThresholdCell item={{id:selected.watchlist_id,ticker:selected.ticker,enabled:true,alert_enabled:selected.alert_enabled,user_group_id:selected.user_group_id,display_order:selected.display_order,threshold_20m:selected.threshold_20m,threshold_1h:selected.threshold_1h,threshold_day:selected.threshold_day}} field="threshold_day" onSaved={refresh}/></div><button className="danger-btn" onClick={()=>remove.mutate(selected.watchlist_id!)}>从自选股移除</button></>:<><p>被以下自选股用于同行比较：{selected.peer_referenced_by.join('、')}</p><button onClick={()=>promote.mutate(selected.ticker)} disabled={promote.isPending}>加入自选股并启动完整同步</button></>}</article>}</Sheet>
  </div>
}

function fieldLabel(key:string) {
  const previous = key.endsWith('_previous')
  const base = previous?key.slice(0,-9):key
  const label = ({operating_income:'Operating Income / EBIT',pretax_income:'Pretax Income',tax_expense:'Tax Expense',net_income:'Net Income',operating_cash_flow:'Operating Cash Flow',gross_profit:'Gross Profit',total_debt:'Total Debt',long_term_debt:'Long-Term Debt',stockholders_equity:'Stockholders Equity',shares_issued:'Ordinary Shares Number',cash:'Cash',retained_earnings:'Retained Earnings',current_assets:'Current Assets',current_liabilities:'Current Liabilities',total_assets:'Total Assets',total_liabilities:'Total Liabilities',revenue:'Revenue',market_cap:'Market Cap',positive_invested_capital:'正投入资本',positive_total_assets:'正总资产',positive_total_liabilities:'正总负债'} as Record<string,string>)[base]||base.replaceAll('_',' ')
  return `${label}${previous?'（上一年度）':''}`
}

function RatingGauge({r}:{r:Rating}) {
  const items=[
    {k:'strongBuy',label:'强烈买入',n:r.strongBuy},
    {k:'buy',label:'买入',n:r.buy},
    {k:'hold',label:'持有',n:r.hold},
    {k:'sell',label:'卖出',n:r.sell},
    {k:'strongSell',label:'强烈卖出',n:r.strongSell},
  ]
  const total=items.reduce((s,x)=>s+x.n,0)
  if(!total) return <div className="empty">暂无分析师评级。</div>
  const score=items.reduce((s,x,i)=>s+x.n*i,0)/total
  const pos=10+score/4*80
  const consensus=items[Math.round(score)].label
  return <div className="rating-gauge">
    <div className="rg-track">
      <div className="rg-pointer" style={{left:`${pos}%`}}><b>共识：{consensus}</b></div>
    </div>
    <div className="rg-ticks">{items.map(x=><span key={x.k} className="rg-tick"><em>{x.label}</em><small>{x.n}</small></span>)}</div>
    {r.period&&<div className="rg-period">数据期间：{r.period}</div>}
  </div>
}

const statementMetricInfo:Record<string,StatementMetric> = {
  revenue:{label:'营业收入',english:'Revenue',description:'公司在报告期内从主营业务取得的总收入。',impact:'收入增长是规模扩张的起点，但需要结合毛利、利润和现金流判断增长质量。'},
  gross_profit:{label:'毛利润',english:'Gross Profit',description:'收入扣除直接生产或采购成本后留下的利润。',impact:'毛利越高，通常代表定价能力或成本结构更优；应与同行和历史趋势一起看。'},
  operating_income:{label:'营业利润',english:'Operating Income / EBIT',description:'主营业务在扣除营业费用后的利润，不含利息和所得税。',impact:'用于观察核心经营效率，也常作为 EBITDA 和 ROIC 的基础。'},
  net_income:{label:'净利润',english:'Net Income',description:'扣除利息、税项及非经营项目后的最终利润。',impact:'反映归属经营成果，但会受到一次性项目、税项和资本结构影响。'},
  eps:{label:'每股收益',english:'Diluted EPS',description:'按稀释后流通股数分摊的每股净利润。',impact:'是市盈率的重要分母；稀释股数上升会削弱每股价值。'},
  ebitda:{label:'息税折旧摊销前利润',english:'EBITDA',description:'营业利润加回折旧与摊销；Yahoo 未提供时按该口径计算。',impact:'便于比较资本结构和折旧政策不同的非金融企业；金融公司通常不适用 EV/EBITDA。',formula:'Operating Income + Depreciation + Amortization'},
  cash:{label:'现金及等价物',english:'Cash and Cash Equivalents',description:'可迅速用于支付、投资或偿债的现金及高流动性资产。',impact:'净现金更高通常增强抗风险能力，但过多现金也可能意味着资金效率有待提升。'},
  inventory:{label:'存货',english:'Inventory',description:'尚未售出的原材料、在制品和商品。',impact:'存货持续快于收入增长可能预示需求走弱或库存管理压力。'},
  current_assets:{label:'流动资产',english:'Current Assets',description:'预计一年内可变现、出售或消耗的资产。',impact:'与流动负债结合可判断短期流动性。'},
  total_assets:{label:'总资产',english:'Total Assets',description:'公司控制的全部经济资源。',impact:'用于判断资产规模、资产周转与资本效率。'},
  total_debt:{label:'总债务',english:'Total Debt',description:'短期和长期有息债务的合计。',impact:'债务需结合现金、利息覆盖和经营现金流判断偿债压力。'},
  shareholders_equity:{label:'股东权益',english:'Stockholders Equity',description:'资产减去负债后归属于股东的账面净资产。',impact:'是 ROE、账面价值和 P/B 的重要基础，银行与保险公司尤其关注。'},
  operating_cash_flow:{label:'经营活动现金流',english:'Operating Cash Flow',description:'主营经营活动实际产生或消耗的现金。',impact:'能检验利润的现金含量；长期为正且与净利润匹配通常更健康。'},
  capital_expenditure:{label:'资本开支',english:'Capital Expenditure',description:'用于厂房、设备和长期资产的现金投入。Yahoo 通常将现金流出显示为负数。',impact:'高资本开支会压低当期自由现金流，但也可能支持未来增长。'},
  free_cash_flow:{label:'自由现金流',english:'Free Cash Flow',description:'经营现金流扣除资本开支后可供债权人和股东使用的现金。',impact:'是 DCF、回购、分红和去杠杆能力的重要观察项。',formula:'Operating Cash Flow − Capital Expenditure（Yahoo 为负数时等价于相加）'},
  financing_cash_flow:{label:'融资活动现金流',english:'Financing Cash Flow',description:'债务、股票发行、回购和分红等融资活动产生的现金流。',impact:'可帮助辨别公司是依赖外部融资，还是在向股东返还资本。'},
  investing_cash_flow:{label:'投资活动现金流',english:'Investing Cash Flow',description:'收购、出售投资及长期资产投资相关的现金流。',impact:'需区分正常投资、并购扩张和资产处置等不同驱动。'},
}

function FundamentalsCenter({tickers,active,setActive,onOpenSec}:{tickers:string[];active:string;setActive:(ticker:string)=>void;onOpenSec:()=>void}) {
  const current = active||tickers[0]||''
  const fundamentals = useQuery({queryKey:['fundamentals',current],queryFn:()=>api<Fundamentals>(`/fundamentals?ticker=${current}`),enabled:!!current,staleTime:60_000})
  const financials = useQuery({queryKey:['financials',current],queryFn:()=>api<Financial[]>(`/financials?ticker=${current}`),enabled:!!current,staleTime:5*60_000})
  const secFinancials = useQuery({queryKey:['sec-financials',current],queryFn:()=>api<SecFin[]>(`/sec-financials?ticker=${current}`),enabled:!!current,staleTime:5*60_000})
  const secEvents = useQuery({queryKey:['sec-events',current],queryFn:()=>api<SecEvent[]>(`/sec-events?ticker=${current}`),enabled:!!current,staleTime:5*60_000})
  const fmtNum = (v:number|null) => {
    if(v==null) return '数据不足'
    const abs=Math.abs(v), sign=v<0?'-':''
    if(abs>=1e8) return `${sign}${(abs/1e8).toFixed(2)}亿`
    if(abs>=1e4) return `${sign}${(abs/1e4).toFixed(2)}万`
    return v.toLocaleString('en-US',{maximumFractionDigits:2})
  }
  const fmtMetric = (v:number|null) => v==null?'—':v.toLocaleString('en-US',{maximumFractionDigits:2})
  const r = fundamentals.data?.rating
  const priorityEvents=(secEvents.data||[]).filter(event=>event.priority==='urgent'||event.priority==='important').slice(0,6)
  const periods=new Map<string,{yahoo?:Financial;sec?:SecFin}>()
  financials.data?.forEach(row=>periods.set(`${row.fiscal_year}-${row.fiscal_period}`,{...periods.get(`${row.fiscal_year}-${row.fiscal_period}`),yahoo:row}))
  secFinancials.data?.forEach(row=>periods.set(`${row.fiscal_year}-${row.fiscal_period}`,{...periods.get(`${row.fiscal_year}-${row.fiscal_period}`),sec:row}))
  const compared=[...periods.entries()].sort(([,a],[,b])=>(b.yahoo?.period_end||b.sec?.period_end||'').localeCompare(a.yahoo?.period_end||a.sec?.period_end||'')).slice(0,4)
  const secAsFinancial=(row:SecFin):Financial=>({fiscal_year:row.fiscal_year,fiscal_period:row.fiscal_period,period_end:row.period_end||'',filed_at:null,currency:row.currency,revenue:row.revenue,eps:row.eps_diluted,net_income:row.net_income,operating_income:row.operating_income,gross_margin:row.revenue!=null&&row.revenue!==0&&row.gross_profit!=null?row.gross_profit/row.revenue*100:null,net_margin:row.revenue!=null&&row.revenue!==0&&row.net_income!=null?row.net_income/row.revenue*100:null,operating_cash_flow:row.operating_cash_flow,free_cash_flow:null,source:row.source,synced_at:row.synced_at})
  const financialCells=(row:Financial,other?:Financial)=>{
    const values=[row.revenue,row.net_income,row.operating_income,row.eps,row.net_margin,row.operating_cash_flow]
    const otherValues=[other?.revenue,other?.net_income,other?.operating_income,other?.eps,other?.net_margin,other?.operating_cash_flow]
    return values.map((value,index)=>{const different=providerValuesDiffer(value,otherValues[index]??null);return <span className={different?'source-different':''} title={different?'Yahoo 与 SEC 披露存在超过 1% 的差异':undefined} key={index}>{index===4?(value==null?'数据不足':value.toFixed(1)+'%'):fmtNum(value)}</span>})
  }
  return <div className="news-center">
    <SnapshotTickerBar section="fundamentals" tickers={tickers} current={current} onSelect={setActive}/>
    {!current&&<div className="empty">搜索并选择证券，临时查看基本面数据。</div>}
    {fundamentals.data&&<div className={`source-notice ${fundamentals.data.source_support.yahoo?'source-ok':'source-error'}`}><span><i aria-hidden="true"/>{fundamentals.data.source_support.yahoo?'Yahoo 实时基本面已连接':'Yahoo 基本面暂不可用'}</span><time>{formatDate(fundamentals.data.as_of)}</time>{!fundamentals.data.source_support.finnhub&&<small>Finnhub 仅作可选补充，不影响下方 Yahoo 数据。</small>}</div>}
    <div className="section-title"><h2>{current} 基本面指标</h2></div>
    <div className="metric-grid">{fundamentals.data?.metrics.map(m=><div className="metric-card" key={m.label}><span>{m.label}</span><strong>{fmtMetric(m.value)}</strong>{m.source&&<em>{m.source==='yahoo'?'Yahoo':'Finnhub'}</em>}</div>)}{fundamentals.isError&&<div className="empty">基本面数据暂不可用。</div>}</div>
    <section className="fundamental-sec-preview"><div className="section-title"><div><p>SEC DISCLOSURES</p><h2>重要 SEC 公告</h2></div><button onClick={onOpenSec}>进入公告详情 <span>→</span></button></div>{secEvents.isLoading?<div className="empty">正在读取 SEC 公告…</div>:priorityEvents.length?<div className="priority-sec-list">{priorityEvents.map(event=><article className={`sec-${event.priority}`} key={event.id}><div><span className={`sec-prio ${event.priority}`}>{event.priority==='urgent'?'紧急':'重要'}</span><b>{event.item_label}</b><small>{event.form} · Item {event.item_code} · {event.filing_date||'日期未披露'}</small></div><em>来源：SEC EDGAR</em></article>)}</div>:<div className="empty">暂无紧急或重要 SEC 公告。</div>}</section>
    {!!current&&<OwnershipSection symbol={current}/>}
    <div className="section-title"><h2>分析师评级</h2></div>
    {r?<RatingGauge r={r}/>:<div className="empty">暂无分析师评级。</div>}
    <div className="section-title"><div><h2>近四季度财务数据</h2><small>Yahoo 与 SEC 同期数据并列；黄色表示两来源差异超过 1%。</small></div></div>
    <div className="table"><div className="table-head fin"><span>季度 / 来源</span><span>报告期</span><span>营收</span><span>净利润</span><span>营业利润</span><span>EPS</span><span>净利率</span><span>经营现金流</span></div>{compared.flatMap(([period,pair])=>{const sec=pair.sec&&secAsFinancial(pair.sec);return [pair.yahoo&&<div className="table-row fin" key={`${period}-yahoo`}><b>{period}<small className="source-badge">Yahoo</small></b><span>{pair.yahoo.period_end}</span>{financialCells(pair.yahoo,sec||undefined)}</div>,sec&&<div className="table-row fin" key={`${period}-sec`}><b>{period}<small className="source-badge sec">SEC EDGAR</small></b><span>{sec.period_end||'—'}</span>{financialCells(sec,pair.yahoo)}</div>]})}{!compared.length&&<div className="empty">暂无 Yahoo 或 SEC 财务数据。</div>}</div>
  </div>
}

function FinancialStatementsCenter({tickers,onStatementMetric,active,setActive}:{tickers:string[];onStatementMetric:(metric:StatementMetric)=>void;active:string;setActive:(ticker:string)=>void}) {
  const [frequency,setFrequency] = useState<'annual'|'quarterly'>('annual')
  const current = active||tickers[0]||''
  const statements = useQuery({queryKey:['financial-statements',current,frequency],queryFn:()=>api<FinancialStatement[]>(`/financial-statements?ticker=${current}&frequency=${frequency}`),enabled:!!current,staleTime:5*60_000})
  return <div className="news-center"><SnapshotTickerBar section="financials" tickers={tickers} current={current} onSelect={setActive}/>{!current?<div className="empty">搜索并选择证券，临时查看财务报表。</div>:<FinancialStatementsPanel frequency={frequency} setFrequency={setFrequency} rows={statements.data||[]} loading={statements.isLoading} onMetric={onStatementMetric}/>}</div>
}

function FinancialStatementsPanel({frequency,setFrequency,rows,loading,onMetric}:{frequency:'annual'|'quarterly';setFrequency:(value:'annual'|'quarterly')=>void;rows:FinancialStatement[];loading:boolean;onMetric:(metric:StatementMetric)=>void}) {
  const fmt = (value:number|null) => {
    if(value==null) return '数据不足'
    const sign=value<0?'−':''; const abs=Math.abs(value)
    if(abs>=1e12) return `${sign}${(abs/1e12).toFixed(2)}T`
    if(abs>=1e9) return `${sign}${(abs/1e9).toFixed(1)}B`
    if(abs>=1e6) return `${sign}${(abs/1e6).toFixed(1)}M`
    return value.toLocaleString('en-US',{maximumFractionDigits:2})
  }
  const groups:{title:string;key:keyof Pick<FinancialStatement,'income_statement'|'balance_sheet'|'cash_flow'>;items:string[]}[] = [
    {title:'利润表',key:'income_statement',items:['revenue','gross_profit','operating_income','net_income','eps','ebitda']},
    {title:'资产负债表',key:'balance_sheet',items:['cash','inventory','current_assets','total_assets','total_debt','shareholders_equity']},
    {title:'现金流量表',key:'cash_flow',items:['operating_cash_flow','capital_expenditure','free_cash_flow','financing_cash_flow','investing_cash_flow']},
  ]
  return <section className="financial-statements">
    <div className="statement-toolbar"><div><p className="eyebrow">YAHOO FINANCE · THREE STATEMENTS</p><h2>财务报表</h2><small>与 Yahoo Finance 三表同源；点击指标查看释义。{rows[0]?.synced_at&&` · 同步于 ${formatDate(rows[0].synced_at)}`}</small></div><div className="frequency-toggle" role="tablist" aria-label="报表周期"><button role="tab" aria-selected={frequency==='annual'} className={frequency==='annual'?'active':''} onClick={()=>setFrequency('annual')}>年度</button><button role="tab" aria-selected={frequency==='quarterly'} className={frequency==='quarterly'?'active':''} onClick={()=>setFrequency('quarterly')}>季度</button></div></div>
    {loading&&<div className="empty">正在读取 Yahoo Finance 财务报表…</div>}
    {!loading&&!rows.length&&<div className="empty">尚未同步三大报表。系统会在下一次财务同步时拉取年度与季度数据。</div>}
    {rows.length>0&&groups.map(group=><section className="statement-card" key={group.key}><h3>{group.title}</h3><div className="statement-table">{[<div className="statement-row statement-head" style={{gridTemplateColumns:`minmax(142px,.85fr) repeat(${rows.length},minmax(68px,1fr))`}} key="head"><span>指标</span>{rows.map(row=><span key={row.period_end}>{frequency==='annual'?row.fiscal_year:row.period_end.slice(0,10)}</span>)}</div>,...group.items.map(key=>{const info=statementMetricInfo[key];return <button className="statement-row" style={{gridTemplateColumns:`minmax(142px,.85fr) repeat(${rows.length},minmax(68px,1fr))`}} onClick={()=>onMetric(info)} key={key}><span><b>{info.label}</b><small>{info.english}</small></span>{rows.map(row=><span key={row.period_end}>{fmt(row[group.key][key])}</span>)}</button>})]}</div></section>)}
  </section>
}

function SecCenter({tickers,active,setActive}:{tickers:string[];active:string;setActive:(ticker:string)=>void}) {
  const [view,setView] = useState<'events'|'financials'|'insider'|'holdings'>('events')
  const client = useQueryClient()
  const current = active||tickers[0]||''
  const events = useQuery({queryKey:['sec-events',current],queryFn:()=>api<SecEvent[]>(`/sec-events?ticker=${current}`),enabled:!!current&&view==='events'})
  const fins = useQuery({queryKey:['sec-financials',current],queryFn:()=>api<SecFin[]>(`/sec-financials?ticker=${current}`),enabled:!!current&&view==='financials'})
  const insider = useQuery({queryKey:['sec-insider',current],queryFn:()=>api<SecInsider[]>(`/sec-insider?ticker=${current}`),enabled:!!current&&view==='insider'})
  const holdings = useQuery({queryKey:['sec-13f',current],queryFn:()=>api<Sec13F>(`/sec-13f?ticker=${current}`),enabled:!!current&&view==='holdings'})
  const refresh13f = useMutation({mutationFn:()=>post(`/sec-13f/refresh`,{}),onSuccess:()=>setTimeout(()=>client.invalidateQueries({queryKey:['sec-13f',current]}),8000)})
  const refresh = useMutation({mutationFn:()=>post(`/sec-filings/refresh?ticker=${current}`,{}),onSuccess:()=>setTimeout(()=>{client.invalidateQueries({queryKey:['sec-events',current]});client.invalidateQueries({queryKey:['sec-financials',current]});client.invalidateQueries({queryKey:['sec-insider',current]})},5000)})
  const priorityName:Record<string,string> = {urgent:'紧急',important:'重要',normal:'常规'}
  const fmtNum = (v:number|null) => {
    if(v==null) return '数据不足'
    const abs=Math.abs(v), sign=v<0?'-':''
    if(abs>=1e8) return `${sign}${(abs/1e8).toFixed(2)}亿`
    if(abs>=1e4) return `${sign}${(abs/1e4).toFixed(2)}万`
    return v.toLocaleString('en-US',{maximumFractionDigits:2})
  }
  const codeName:Record<string,string> = {P:'买入',S:'卖出',M:'期权行权',F:'税务代扣',A:'授予',G:'赠予',D:'处置'}
  return <div className="news-center">
    <SnapshotTickerBar section="sec" tickers={tickers} current={current} onSelect={setActive}/>
    {!current&&<div className="empty">搜索并选择证券，临时查看 SEC 公告。</div>}
    <div className="section-title"><h2>{current} SEC 官方数据</h2><button onClick={()=>refresh.mutate()} disabled={refresh.isPending}>{refresh.isPending?'刷新中…':'刷新数据'}</button></div>
    {refresh.isSuccess&&<p className="saved">已触发后台采集（含 XBRL 解析，约需 1-2 分钟），稍后自动刷新。</p>}
    <div className="news-tickers" style={{marginTop:4}}>{([['events','重大事件'],['financials','财务数据'],['insider','内幕交易'],['holdings','机构持仓']] as const).map(([k,l])=><button key={k} className={view===k?'active':''} onClick={()=>setView(k)}>{l}</button>)}</div>
    <small className="chart-note">数据来自 SEC EDGAR 官方披露（edgartools 解析），仅供参考</small>

    {view==='events'&&<div className="news-list">{events.data?.map(e=><article className={`news-card sec-${e.priority}`} key={e.id}>
      <div className="news-body">
        <div className="news-meta"><span className={`sec-prio ${e.priority}`}>{priorityName[e.priority]||e.priority}</span><span className="sec-form">{e.form}</span><span className="sec-event-tag">Item {e.item_code} · {e.item_label}</span>{e.filing_date&&<span>披露 {e.filing_date}</span>}</div>
        {e.summary_zh
          ? <div className="ai-summary sec-summary"><ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{e.summary_zh}</ReactMarkdown></div>
          : (e.summary_status==='failed'
              ? (e.text&&<p className="news-summary" style={{whiteSpace:'pre-wrap'}}>{e.text.length>600?e.text.slice(0,600)+'…':e.text}</p>)
              : (e.text?<p className="news-summary sec-summary-pending">AI 中文总结生成中…</p>:null))}
        {e.text&&<details className="sec-original"><summary>展开查看英文原文</summary><p className="news-summary" style={{whiteSpace:'pre-wrap'}}>{e.text}</p></details>}
        <a className="news-title" href={e.filing_url} target="_blank" rel="noreferrer">查看 SEC 原文</a>
      </div>
    </article>)}{!events.data?.length&&<div className="empty">暂无重大事件，点击"刷新数据"触发采集。</div>}</div>}

    {view==='financials'&&<div className="table"><div className="table-head fin"><span>期间</span><span>营收</span><span>净利润</span><span>营业利润</span><span>毛利</span><span>EPS(摊薄)</span><span>现金</span><span>负债/经营现金流</span></div>{fins.data?.map(f=><div className="table-row fin" key={`${f.fiscal_year}${f.fiscal_period}${f.form}`}><b>{f.fiscal_year} {f.fiscal_period}</b><span>{fmtNum(f.revenue)}</span><span>{fmtNum(f.net_income)}</span><span>{fmtNum(f.operating_income)}</span><span>{fmtNum(f.gross_profit)}</span><span>{f.eps_diluted==null?'数据不足':f.eps_diluted.toFixed(2)}</span><span>{fmtNum(f.cash_and_equivalents)}</span><span>{fmtNum(f.total_debt)} / {fmtNum(f.operating_cash_flow)}</span></div>)}{!fins.data?.length&&<div className="empty">暂无 SEC 财务数据（需存在 10-K/10-Q 披露）。</div>}</div>}

    {view==='insider'&&<><div className="explainer"><b>什么是内部人交易（Form 4）？</b><p>公司高管、董事及持股 5% 以上的大股东，买卖本公司股票后须在两个工作日内向 SEC 申报，即 Form 4。这是了解"最懂公司的人"如何用真金白银投票的窗口。<b>CEO 等核心高管的公开市场买入</b>（🌟）通常被视为信心信号；<b>短期内的大额抛售</b>（⚠️）则值得留意，但也可能只是行权、税务或分散配置等中性原因，需结合背景判断。金额栏为该笔交易的市值估算。</p></div><div className="table"><div className="table-head fin"><span>日期</span><span>内幕人</span><span>职务</span><span>类型</span><span>股数</span><span>价格</span><span>金额</span><span>交易后持股</span></div>{insider.data?.map(t=><div className="table-row fin" key={t.id}><b>{t.transaction_date||'—'}{t.flag==='ceo_buy'&&' 🌟'}{t.flag==='heavy_sell'&&' ⚠️'}</b><span>{t.insider_name}</span><span>{t.insider_title||'—'}</span><span className={t.transaction_code==='P'?'positive':t.transaction_code==='S'?'negative':''}>{t.transaction_code?(codeName[t.transaction_code]||t.transaction_code):'—'}</span><span>{fmtNum(t.shares)}</span><span>{t.price==null?'—':`$${t.price.toFixed(2)}`}</span><span>{fmtNum(t.value)}</span><span>{fmtNum(t.shares_owned_after)}</span></div>)}{!insider.data?.length&&<div className="empty">暂无内幕交易记录（Form 4）。</div>}</div></>}

    {view==='holdings'&&<>
      <div className="explainer"><b>什么是机构持仓（13F）？</b><p>管理资产超 1 亿美元的机构投资者（对冲基金、资管、养老金等）须在每个自然季度结束后 <b>45 天内</b>向 SEC 申报所持美股，即 Form 13F。它让我们看到"聪明钱"在这只股票上的整体布局。注意两点：<b>① 数据有约一个季度的滞后</b>，反映的是上季度末的持仓而非当下；<b>② 只含多头（做多），不含做空</b>，且不代表机构全部仓位。下方"环比"是相对上一季度的加减仓，<b>本季新建仓</b>与大幅增持通常被视为看多信号，清仓/大幅减持则相反。</p></div>
      <div className="section-title" style={{marginTop:8}}><span>{holdings.data?.report_period?`季度截至 ${holdings.data.report_period}`:'机构持仓'}{holdings.data?.prev_period&&`（对比 ${holdings.data.prev_period}）`}</span><button onClick={()=>refresh13f.mutate()} disabled={refresh13f.isPending}>{refresh13f.isPending?'采集中…':'重新采集'}</button></div>
      {refresh13f.isSuccess&&<p className="saved">已触发全市场 13F 数据集采集（约需数分钟下载解析），稍后自动刷新。</p>}
      <div className="table"><div className="table-head fin"><span>机构</span><span>持股数</span><span>持仓市值</span><span>类型</span><span>环比变动</span><span>申报日</span></div>{holdings.data?.holdings.map(h=><div className="table-row fin" key={h.id}><b>{h.manager_name}</b><span>{fmtNum(h.shares)}</span><span>{fmtNum(h.value_usd)}</span><span>{h.put_call||'股票'}</span><span className={h.is_new?'positive':h.share_change==null?'':h.share_change>0?'positive':h.share_change<0?'negative':''}>{h.is_new?'本季新建仓':h.share_change==null?'—':`${h.share_change>0?'+':''}${fmtNum(h.share_change)}`}</span><span>{h.filing_date||'—'}</span></div>)}{!holdings.data?.holdings.length&&<div className="empty">暂无 13F 机构持仓数据，点击"重新采集"触发（13F 每季度更新一次）。</div>}</div>
    </>}
  </div>
}

function NewsCenter({tickers,active,setActive}:{tickers:string[];active:string;setActive:(ticker:string)=>void}) {
  const [weeklyOpen,setWeeklyOpen] = useState(false)
  const [selectedNewsId,setSelectedNewsId] = useState<number|null>(null)
  const [scope,setScope] = useState<'market'|'company'>('company')
  const [sortMode,setSortMode] = useState<'ranked'|'latest'>('ranked')
  const current = active||tickers[0]||''
  const companyNews = useQuery({queryKey:['news',current,sortMode],queryFn:()=>api<NewsRow[]>(`/news?ticker=${current}&sort=${sortMode}`),enabled:scope==='company'&&!!current,refetchInterval:q=>(q.state.data as NewsRow[]|undefined)?.some(n=>['pending','queued','processing'].includes(n.ai_summary_status))?2000:false})
  const marketNews = useQuery({queryKey:['news','market',sortMode],queryFn:()=>api<MarketNewsResponse>(`/news/market?sort=${sortMode}`),enabled:scope==='market',refetchInterval:q=>(q.state.data as MarketNewsResponse|undefined)?.items.some(n=>['pending','queued','processing'].includes(n.ai_summary_status))?2000:false})
  const news = scope==='market' ? marketNews.data?.items : companyNews.data
  const archive = useQuery({queryKey:['news-archive',current],queryFn:()=>api<NewsArchive|null>(`/news/archive?ticker=${current}`),enabled:scope==='company'&&!!current})
  const weekly = useQuery({queryKey:['news-weekly',current],queryFn:()=>api<WeeklyArchive[]>(`/news/weekly?ticker=${current}`),enabled:scope==='company'&&!!current&&weeklyOpen})
  const detail = useQuery({queryKey:['news-detail',selectedNewsId],queryFn:()=>api<NewsRow>(`/news/${selectedNewsId}`),enabled:selectedNewsId!==null,refetchInterval:q=>{const status=(q.state.data as NewsRow|undefined)?.ai_summary_status;return status==='idle'||status==='pending'?8000:status==='queued'||status==='processing'?2000:false}})
  const refresh = useMutation({mutationFn:()=>post(scope==='market'?'/news/market/refresh':`/news/refresh?ticker=${current}`,{})})
  // 隐藏“采用与合并”和“剔除”过程段，只留关键事实归纳（兼容历史旧结构定档）
  const keyFactsOnly = (md:string) => md.replace(/###\s*(?:采用与合并|剔除)[\s\S]*?(?=\n###\s|$)/g,'').trim()
  const includedIds = archive.data?.included_news_ids || []
  const orderNo = (id:number) => { const i = includedIds.indexOf(id); return i>=0 ? i+1 : null }
  const detailItem = detail.data
  const detailAnalysis = detailItem?.ai_analysis
  const detailStatus = detailItem?.ai_summary_status || 'idle'
  const detailSummary = detailAnalysis?.summary_zh || detailItem?.ai_summary || null
  const detailReady = detailStatus==='completed'||detailStatus==='degraded'
  const detailPending = detailStatus==='idle'||detailStatus==='pending'||detailStatus==='queued'||detailStatus==='processing'
  const detailEventType = detailItem?.ai_event_type || detailAnalysis?.event_type || null
  const detailSentiment = detailItem?.ai_sentiment || detailAnalysis?.sentiment || null
  const detailMarketImpact = detailItem?.ai_market_impact || detailAnalysis?.market_impact || null
  const detailImportance = detailItem?.ai_importance ?? detailAnalysis?.importance ?? null
  const detailTickers = detailItem ? Array.from(new Set([...(detailItem.symbols || []), ...(detailAnalysis?.tickers || [])])) : []
  const contentFlags = [detailItem?.content_fetch_status,detailItem?.content_fetch_quality].filter(Boolean).map(value=>String(value).toLowerCase())
  const contentDegraded = detailStatus==='degraded'||contentFlags.some(value=>['degraded','partial','incomplete','insufficient','failed','unavailable'].includes(value))
  return <div className="news-center">
    <SnapshotTickerBar section="news" tickers={tickers} current={scope==='company'?current:''} onSelect={ticker=>{setActive(ticker);setScope('company')}} leading={<button className={`market-entry ${scope==='market'?'active':''}`} onClick={()=>setScope('market')}>全市场</button>}/>
    {scope==='company'&&!current&&<div className="empty">搜索并选择证券，临时查看新闻。</div>}
    {scope==='company'&&current&&<section className="news-sentiment-preview"><div className="section-title"><div><p>SENTIMENT PREVIEW</p><h2>舆情预览</h2></div></div><SentimentModule ticker={current} compact/></section>}
    {scope==='company'&&<><div className="section-title"><h2>每日定档（Luna 去重）</h2><button onClick={()=>setWeeklyOpen(true)}>历史每周新闻</button></div>
    {archive.data?<article className="report-detail"><p className="eyebrow">{archive.data.market_date} · v{archive.data.version} · {archive.data.model}</p><div className="report-content"><ReactMarkdown rehypePlugins={[rehypeSanitize]}>{keyFactsOnly(archive.data.content)}</ReactMarkdown></div></article>:<div className="empty">尚未生成每日定档。</div>}
    <Sheet open={weeklyOpen} onClose={()=>setWeeklyOpen(false)} title={`${current} 历史每周新闻`}>
      {weekly.isLoading?<div className="empty">加载中…</div>:weekly.data?.length?<div className="weekly-list">{weekly.data.map(w=><article className="report-detail" key={`${w.iso_year}-${w.iso_week}`}><p className="eyebrow">{w.week_start} ~ {w.week_end} · {w.iso_year}W{w.iso_week} · v{w.version} · {w.model}</p><div className="report-content"><ReactMarkdown rehypePlugins={[rehypeSanitize]}>{keyFactsOnly(w.content)}</ReactMarkdown></div></article>)}</div>:<div className="empty">暂无历史每周新闻。</div>}
    </Sheet></>}
    <div className="section-title"><h2>{scope==='market'?'市场要闻':`${current} 新闻`}</h2><div className="rating-bar"><div className="segmented compact" role="group" aria-label="新闻排序方式">{([['ranked','综合排序'],['latest','最新优先']] as const).map(([key,label])=><button type="button" key={key} className={sortMode===key?'active':''} aria-pressed={sortMode===key} onClick={()=>setSortMode(key)}>{label}</button>)}</div><button onClick={()=>refresh.mutate()} disabled={refresh.isPending}>{refresh.isPending?'刷新中…':'刷新新闻'}</button></div></div>
    {scope==='market'&&marketNews.data?.last_updated_at&&<p className="market-updated">最近更新：{formatDate(marketNews.data.last_updated_at)}</p>}
    {refresh.isSuccess&&<p className="saved">已触发后台采集，稍后刷新查看。</p>}
    <div className="news-list">{news?.map(item=>{const no=orderNo(item.id);return <article className="news-card" key={item.id}>
      <div className="news-body">
        <div className="news-meta">{no&&<span className="news-no">[{no}]</span>}<span className={`prov ${item.provider}`}>{item.provider==='finnhub'?'Finnhub':item.provider==='tavily'?'Tavily':item.provider==='yfinance'?'Yahoo财经':item.provider==='marketaux'?'Marketaux':item.provider}</span>{item.topic&&<span className="news-topic">{item.topic}</span>}{item.importance_score!==null&&item.importance_score>=.65&&<span className="news-important">重要</span>}{item.source&&<span>{item.source}</span>}<span>{item.published_at?formatDate(item.published_at):formatDate(item.found_at)}</span></div>
        <a className="news-title" href={item.url} target="_blank" rel="noreferrer">{item.translated_title||item.title}</a>
        {item.translated_title&&item.translated_title!==item.title&&<p className="news-original-title">{item.title}</p>}
        {item.summary&&<p className="news-summary">{item.summary}</p>}
        <button type="button" className="ai-btn" onClick={()=>setSelectedNewsId(item.id)} aria-label={`查看 ${item.translated_title||item.title} 详情`}>详情</button>
      </div>
    </article>})}{!news?.length&&<div className="empty">暂无原始新闻，点击"刷新新闻"触发采集。</div>}</div>
    <Sheet open={selectedNewsId!==null} onClose={()=>setSelectedNewsId(null)} title={detailItem?.translated_title||detailItem?.title||'新闻详情'}>
      {detail.isLoading&&<div className="empty">正在读取已保存新闻详情…</div>}
      {detail.isError&&<div className="empty">已保存新闻详情暂不可用，请稍后重试。</div>}
      {detailItem&&<article className="report-detail sheet-report">
        <p className="eyebrow">{detailItem.provider} · {detailItem.source||'来源未标注'} · {formatDate(detailItem.published_at||detailItem.found_at)}</p>
        <h2>{detailItem.translated_title||detailItem.title}</h2>
        {detailItem.translated_title&&detailItem.translated_title!==detailItem.title&&<p className="news-original-title">{detailItem.title}</p>}
        <div className="news-meta"><span>{detailItem.ticker}</span>{detailTickers.map(ticker=><span key={ticker}>{ticker}</span>)}{detailItem.topic&&<span className="news-topic">{detailItem.topic}</span>}</div>
        {contentDegraded&&<p className="metric-warning">原文正文不完整，摘要可能存在遗漏，请打开原文核对。</p>}
        {detailPending&&<p className="news-summary">{detailStatus==='idle'||detailStatus==='pending'?'等待后台获取正文并生成摘要…':'正在生成摘要…'}</p>}
        {detailReady&&detailSummary&&<section><h3>中文摘要</h3><div className="ai-summary"><ReactMarkdown rehypePlugins={[rehypeSanitize]}>{detailSummary}</ReactMarkdown></div></section>}
        {detailItem.summary&&(!detailSummary||!detailReady)&&<section><h3>原始概要</h3><p className="news-summary">{detailItem.summary}</p></section>}
        {!detailPending&&!detailSummary&&!detailItem.summary&&<p className="news-summary">暂无已保存摘要。</p>}
        {detailStatus==='failed'&&<small className="summary-error">{detailItem.ai_summary_error||'摘要生成失败，当前仅显示可用原始信息。'}</small>}
        {detailReady&&!!detailAnalysis?.key_points?.length&&<section><h3>关键要点</h3><ul>{detailAnalysis.key_points.map((point,index)=><li key={`${point}-${index}`}>{point}</li>)}</ul></section>}
        {detailReady&&<div className="metric-grid">
          <div className="metric-card"><span>事件类型</span><strong>{detailEventType||'数据不足'}</strong></div>
          <div className="metric-card"><span>情绪</span><strong>{detailSentiment||'数据不足'}</strong></div>
          <div className="metric-card"><span>重要性</span><strong>{detailImportance==null?'数据不足':detailImportance.toLocaleString('zh-CN',{maximumFractionDigits:2})}</strong></div>
        </div>}
        {detailReady&&<div className="metric-card" style={{marginTop:14}}><span>市场影响</span><strong>{detailMarketImpact||'数据不足'}</strong></div>}
        {detailItem.article_content&&<details><summary>查看已保存正文</summary><p className="news-summary" style={{whiteSpace:'pre-wrap'}}>{detailItem.article_content}</p></details>}
        {(detailItem.ai_summary_version||detailItem.ai_summary_generated_at||detailItem.content_fetch_method)&&<p className="statement-source">{detailItem.ai_summary_version&&`摘要版本 ${detailItem.ai_summary_version}`}{detailItem.ai_summary_generated_at&&` · 生成于 ${formatDate(detailItem.ai_summary_generated_at)}`}{detailItem.content_fetch_method&&` · 正文来源 ${detailItem.content_fetch_method}`}</p>}
        <a className="news-title" href={detailItem.content_final_url||detailItem.url} target="_blank" rel="noreferrer">打开原文 ↗</a>
      </article>}
    </Sheet>
  </div>
}

function CongressSettings() {
  const client = useQueryClient()
  const [q,setQ] = useState('')
  const [doSearch,setDoSearch] = useState('')
  const figures = useQuery({queryKey:['congress-figures'],queryFn:()=>api<Figure[]>('/congress/figures')})
  const search = useQuery({queryKey:['congress-search',doSearch],queryFn:()=>api<FilerHit[]>(`/congress/search?q=${encodeURIComponent(doSearch)}`),enabled:doSearch.length>=2})
  const subscribe = useMutation({mutationFn:(h:FilerHit)=>post('/congress/subscribe',{filer_id:h.filer_id,full_name:h.full_name}),onSuccess:()=>{setDoSearch('');setQ('');client.invalidateQueries({queryKey:['congress-figures']})}})
  const unsub = useMutation({mutationFn:(slug:string)=>api(`/congress/figure/${slug}`,{method:'DELETE'}),onSuccess:()=>client.invalidateQueries({queryKey:['congress-figures']})})
  const partyName:Record<string,string> = {D:'民主党',R:'共和党',I:'独立'}
  return <details className="settings-card congress-settings"><summary>名人监控</summary><p>这里只管理关注对象。持仓估算质量不足，暂不在产品中展示。</p>
    <div className="news-tickers">{figures.data?.map(figure=><button key={figure.slug} disabled={figure.is_seed||unsub.isPending} onClick={()=>unsub.mutate(figure.slug)}>{figure.display_name}{figure.is_seed?' · 默认':' ×'}</button>)}</div>
    <form className="add-form" onSubmit={event=>{event.preventDefault();setDoSearch(q.trim())}}><div><label>添加关注对象</label><input value={q} onChange={event=>setQ(event.target.value)} placeholder="输入名字，如 Pelosi、Tuberville" maxLength={64}/></div><button>搜索</button></form>
    {search.data&&search.data.length>0&&<div className="search-hits">{search.data.map(h=><button key={h.filer_id} className="hit-row" onClick={()=>subscribe.mutate(h)} disabled={subscribe.isPending}><b>{h.full_name}</b><span>{h.chamber||h.branch} · {partyName[h.party||'']||h.party||'—'} {h.state||''}</span><em>{h.trade_count??0} 笔 · 点击订阅</em></button>)}</div>}
    {doSearch.length>=2&&search.data?.length===0&&<div className="empty">未找到匹配的政客。</div>}
  </details>
}

function TrashIcon() { return <svg className="trash-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 14h10l1-14M9 7V4h6v3"/></svg> }

function ThresholdCell({item,field,onSaved}:{item:WatchItem;field:'threshold_20m'|'threshold_1h'|'threshold_day';onSaved:()=>void}) {
  const [editing,setEditing] = useState(false)
  const [value,setValue] = useState('')
  const save = useMutation({mutationFn:(payload:{[k:string]:number|null})=>patch<WatchItem>(`/watchlist/${item.id}`,payload),onSuccess:()=>{setEditing(false);onSaved()}})
  const begin = () => { setValue(item[field]==null?'':String(item[field])); setEditing(true) }
  const commit = () => {
    const trimmed = value.trim()
    if(trimmed===''){ save.mutate({[field]:null}); return }
    const num = Number(trimmed)
    if(!Number.isFinite(num)||num<=0){ setEditing(false); return }
    save.mutate({[field]:num})
  }
  const labels:Record<string,string> = {threshold_20m:'20 分钟',threshold_1h:'1 小时',threshold_day:'当日'}
  return <>
    <button type="button" className="threshold-chip" onClick={begin}><span>{labels[field]}</span><b>{item[field]==null?'默认':`${item[field]}%`}</b></button>
    <Sheet open={editing} onClose={()=>setEditing(false)} title={`${labels[field]}涨跌阈值`}>
      <div className="threshold-drawer"><p>设置 <b>{labels[field]}</b> 内触发异动提醒的涨跌幅。清空后恢复系统默认值。</p><label>涨跌阈值 (%)<input autoFocus type="number" inputMode="decimal" min="0" step="0.1" value={value} placeholder="默认" onChange={e=>setValue(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')commit();if(e.key==='Escape')setEditing(false)}}/></label><div className="threshold-drawer-actions"><button type="button" className="ghost-btn" onClick={()=>setEditing(false)}>取消</button><button type="button" onClick={commit} disabled={save.isPending}>{save.isPending?'保存中…':'保存阈值'}</button></div></div>
    </Sheet>
  </>
}

function SettingsForm({initial,onSaved}:{initial:Settings;onSaved:()=>void}) {
  const [form,setForm]=useState(initial)
  const save=useMutation({mutationFn:()=>patch<Settings>('/settings',form),onSuccess:onSaved})
  const fields:[keyof Settings,string][]=[['threshold_20m','20 分钟涨跌阈值 (%)'],['threshold_1h','1 小时涨跌阈值 (%)'],['threshold_day','当日涨跌阈值 (%)'],['alert_cooldown_minutes','同类警报冷却时间 (分钟)'],['investigation_interval_minutes','异动新闻搜索间隔 (分钟)'],['investigation_duration_minutes','异动调查持续时间 (分钟)']]
  return <section className="settings-card"><h2>监控规则</h2><p>修改后将影响新触发的监控任务。API 密钥只在服务器环境变量中配置。</p><div className="settings-grid">{fields.map(([key,label])=><label key={key}>{label}<input type="number" inputMode="decimal" value={form[key]} onChange={e=>setForm({...form,[key]:Number(e.target.value)})}/></label>)}</div><div className="readonly">行情轮询间隔：{form.price_poll_minutes} 分钟（通过环境变量配置）</div><button onClick={()=>save.mutate()} disabled={save.isPending}>{save.isPending?'保存中…':'保存设置'}</button>{save.isSuccess&&<span className="saved">已保存</span>}</section>
}


// ── 登录 / 注册 ──────────────────────────────────────────────────
function AuthGate({setToken,setAuthUser,onPreview}:{setToken:(t:string)=>void;setAuthUser:(u:{username:string;role:string}|null)=>void;onPreview:()=>void}) {
  const [mode,setMode] = useState<'login'|'register'>('login')
  const [username,setUsername] = useState('')
  const [password,setPassword] = useState('')
  const [remember,setRemember] = useState(false)
  const [msg,setMsg] = useState('')
  const [ok,setOk] = useState(false)

  const handleLogin = async (e:React.FormEvent) => {
    e.preventDefault(); setMsg('')
    try {
      const res = await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password,remember})})
      const data = await res.json()
      if(!res.ok){setMsg(data.detail||'登录失败');return}
      if(remember) localStorage.setItem('auth_token',data.token)
      else sessionStorage.setItem('auth_token',data.token)
      setToken(data.token)
      setAuthUser({username:data.username,role:data.role})
    } catch{setMsg('网络错误')}
  }

  const handleRegister = async (e:React.FormEvent) => {
    e.preventDefault(); setMsg('')
    try {
      const res = await fetch('/api/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})})
      const data = await res.json()
      if(!res.ok){setMsg(data.detail||'注册失败');return}
      setOk(true); setMsg('注册申请已提交，等待管理员审核')
    } catch{setMsg('网络错误')}
  }

  return <div className="auth-gate">
    <div className="auth-aurora auth-aurora-one"/><div className="auth-aurora auth-aurora-two"/>
    <div className="auth-intro"><span className="auth-kicker">MARKET INTELLIGENCE</span><h1>Stock<br/>Monitor。</h1><p><br/></p><div className="auth-signal"><span><i/> AAPL</span><b>214.37</b><em>+1.51%</em></div></div>
    <div className="auth-card">
      <div className="brand"><div className="brand-orb"><img src="/logo.png" className="brand-logo" alt="logo"/></div><div><strong>小日向美香</strong><small>欢迎回来</small></div><ThemeToggle className="auth-theme-toggle"/></div>
      <div className="auth-tabs">
        <button className={mode==='login'?'active':''} onClick={()=>{setMode('login');setMsg('');setOk(false)}}>登录</button>
        <button className={mode==='register'?'active':''} onClick={()=>{setMode('register');setMsg('');setOk(false)}}>申请注册</button>
      </div>
      {mode==='login'
        ?<form onSubmit={handleLogin} className="auth-form">
          <input placeholder="用户名" value={username} onChange={e=>setUsername(e.target.value)} autoFocus/>
          <input type="password" placeholder="密码" value={password} onChange={e=>setPassword(e.target.value)}/>
          <label className="remember-label"><input type="checkbox" checked={remember} onChange={e=>setRemember(e.target.checked)}/> 记住我（30天）</label>
          {msg&&<p className="auth-msg">{msg}</p>}
          <button type="submit" className="auth-submit">登录 <span>→</span></button>
        </form>
        :ok
          ?<p className="auth-msg ok">{msg}</p>
          :<form onSubmit={handleRegister} className="auth-form">
            <input placeholder="用户名（至少2位）" value={username} onChange={e=>setUsername(e.target.value)} autoFocus/>
            <input type="password" placeholder="密码（至少6位）" value={password} onChange={e=>setPassword(e.target.value)}/>
            <p className="auth-hint">注册后需等待管理员审核激活</p>
            {msg&&<p className="auth-msg">{msg}</p>}
            <button type="submit" className="auth-submit">提交申请 <span>→</span></button>
          </form>}
      <button className="preview-btn" onClick={onPreview}><span className="preview-icon">⌁</span><span><b>浏览演示界面</b><small>无需账户 · 使用本地示例数据</small></span><em>→</em></button>
    </div>
  </div>
}

// ── 交易日志 ───────────────────────────────────────────────
const emptyTradeRow = ():TradeLogRow => ({security_id:null,ticker:'',direction:'',quantity:null,price:null,fee:null,strategy:'',result:''})
const legacySecurity = (ticker:string):SecuritySearchResult => ({provider_key:`legacy:${ticker}`,security_id:null,display_symbol:ticker,display_name:ticker,local_symbol:ticker,exchange:null,exchange_code:null,market:null,country_code:null,currency:null,instrument_type:'EQUITY',yahoo_symbol:ticker,finnhub_symbol:null,source:'local',is_local:true})

function JournalSection({username}:{username:string}) {
  const client = useQueryClient()
  const today = new Date().toISOString().slice(0,10)
  const logs = useQuery({queryKey:['trade-logs'],queryFn:()=>api<TradeLog[]>('/trade-logs')})
  const [editing,setEditing] = useState<TradeLog|null>(null)
  const [editorOpen,setEditorOpen] = useState(()=>new URLSearchParams(window.location.search).get('journal')==='new')
  const [form,setForm] = useState({trade_date:today,ticker:'',direction:'',quantity:'',price:'',note:'',content:'',table_rows:[emptyTradeRow()],photo_urls:[] as string[]})
  const [rowSecurities,setRowSecurities] = useState<(SecuritySearchResult|null)[]>([null])
  const payload = () => ({
    trade_date:form.trade_date,
    ticker:null,
    direction:null,
    quantity:null,
    price:null,
    note:form.note||null,
    content:form.content||null,
    table_rows:form.table_rows.filter(r=>r.ticker||r.direction||r.quantity!=null||r.price!=null||r.strategy||r.result).map(r=>({...r,fee:null})),
    photo_urls:form.photo_urls,
  })
  const reset = () => {setEditing(null);setEditorOpen(false);setRowSecurities([null]);setForm({trade_date:today,ticker:'',direction:'',quantity:'',price:'',note:'',content:'',table_rows:[emptyTradeRow()],photo_urls:[]})}
  const save = useMutation({
    mutationFn:()=>editing?patch<TradeLog>(`/trade-logs/${editing.id}`,payload()):post<TradeLog>('/trade-logs',payload()),
    onSuccess:()=>{reset();client.invalidateQueries({queryKey:['trade-logs']});client.invalidateQueries({queryKey:['portfolio-summary']});client.invalidateQueries({queryKey:['portfolio-health']});client.invalidateQueries({queryKey:['portfolio-interpretation']});client.invalidateQueries({queryKey:['portfolio-transactions']})},
  })
  const del = useMutation({mutationFn:(id:number)=>api<unknown>(`/trade-logs/${id}`,{method:'DELETE'}),onSuccess:()=>{client.invalidateQueries({queryKey:['trade-logs']});client.invalidateQueries({queryKey:['portfolio-summary']});client.invalidateQueries({queryKey:['portfolio-health']});client.invalidateQueries({queryKey:['portfolio-interpretation']});client.invalidateQueries({queryKey:['portfolio-transactions']})}})
  const summarize = useMutation({mutationFn:(id:number)=>post<TradeLog>(`/trade-logs/${id}/summarize`,{}),onSuccess:()=>client.invalidateQueries({queryKey:['trade-logs']})})
  const edit = (log:TradeLog) => {
    setEditing(log)
    setForm({
      trade_date:log.trade_date,
      ticker:log.ticker||'',
      direction:log.direction||'',
      quantity:log.quantity==null?'':String(log.quantity),
      price:log.price==null?'':String(log.price),
      note:log.note||'',
      content:log.content||'',
      table_rows:log.table_rows.length?log.table_rows:[emptyTradeRow()],
      photo_urls:log.photo_urls||[],
    })
    setRowSecurities((log.table_rows.length?log.table_rows:[emptyTradeRow()]).map(row=>row.ticker?legacySecurity(row.ticker):null))
    setEditorOpen(true)
  }
  const updateRow = (index:number, patch:Partial<TradeLogRow>) => setForm(f=>({...f,table_rows:f.table_rows.map((row,i)=>i===index?{...row,...patch}:row)}))
  const addPhotos = (files:FileList|null) => {
    if(!files) return
    Array.from(files).slice(0,6).forEach(file=>{
      const reader = new FileReader()
      reader.onload = () => setForm(f=>({...f,photo_urls:[...f.photo_urls,String(reader.result)].slice(0,12)}))
      reader.readAsDataURL(file)
    })
  }
  const beginNew = () => {setEditing(null);setRowSecurities([null]);setForm({trade_date:today,ticker:'',direction:'',quantity:'',price:'',note:'',content:'',table_rows:[emptyTradeRow()],photo_urls:[]});setEditorOpen(true)}
  const removeRow = (index:number) => {setForm(f=>({...f,table_rows:f.table_rows.length>1?f.table_rows.filter((_,i)=>i!==index):[emptyTradeRow()]}));setRowSecurities(items=>items.length>1?items.filter((_,i)=>i!==index):[null])}
  const drafts=logs.data?.filter(log=>log.status==='draft')||[]
  const published=logs.data?.filter(log=>log.status!=='draft')||[]
  const renderLog = (log:TradeLog) => <article className={`journal-card ${log.status==='draft'?'journal-draft':''}`} key={log.id}>
    <div className="journal-card-head"><div><b>{log.trade_date}</b><span>{[log.ticker,log.direction].filter(Boolean).join(' · ')||'未填写标的'}</span>{log.status==='draft'&&<em className="journal-status">待写复盘</em>}</div><small>{log.source_type==='ibkr_sync'?'IBKR 自动草稿':formatDate(log.created_at)}</small></div>
    {log.source_type==='ibkr_sync'&&<div className="journal-broker-facts"><b>券商事实已填好</b><span>仓位 {String(log.objective_facts.quantity_before??'—')} → {String(log.objective_facts.quantity_after??'—')}</span><span>成交点位 {log.price==null?'—':`${log.price} ${String(log.objective_facts.currency||'')}`}</span><span>费率/汇率 {log.objective_facts.fx_rate_to_base==null?'—':String(log.objective_facts.fx_rate_to_base)}</span><span>手续费 {log.objective_facts.commission==null?'—':String(log.objective_facts.commission)}</span></div>}
    {log.note&&<p>{log.note}</p>}
    {log.content&&<p className="journal-content">{log.content}</p>}
    {log.table_rows.length>0&&<div className="journal-mini-table">{log.table_rows.map((row,i)=><span key={i}>{row.ticker||'—'} {row.direction||''} {row.quantity??'—'} @ {row.price??'—'}{row.fee!=null?` · 费用 ${row.fee}`:''}</span>)}</div>}
    {log.photo_urls.length>0&&<div className="photo-strip">{log.photo_urls.map((src,i)=><img src={src} alt={`交易截图 ${i+1}`} key={i}/>)}</div>}
    {log.ai_summary&&<div className="ai-summary"><span className="ai-tag">AI · {log.ai_summary_model}</span><ReactMarkdown rehypePlugins={[rehypeSanitize]}>{log.ai_summary}</ReactMarkdown></div>}
    <div className="journal-card-actions"><button onClick={()=>summarize.mutate(log.id)} disabled={summarize.isPending||log.status==='draft'}>{summarize.isPending?'处理中…':'AI 优化总结'}</button><button onClick={()=>edit(log)}>{log.status==='draft'?'填写复盘':'编辑'}</button><button className="danger" aria-label="删除日志" onClick={()=>del.mutate(log.id)}><TrashIcon/></button></div>
  </article>
  return <div className="journal">
      <div className="journal-list">
        <div className="section-title journal-list-title"><div><p>TRADING JOURNAL</p><h2>我的日志</h2></div><div className="journal-list-actions"><span>{logs.data?.length||0} 条</span><button className="journal-new-btn" onClick={beginNew}><span>＋</span> 新建日志</button></div></div>
        {drafts.length>0&&<div className="journal-subheading"><div><b>待写区</b><span>IBKR 仓位变化已自动填入客观事实</span></div><em>{drafts.length}</em></div>}
        {drafts.map(renderLog)}
        {published.length>0&&drafts.length>0&&<div className="journal-subheading"><div><b>已完成</b><span>你的交易复盘</span></div><em>{published.length}</em></div>}
        {published.map(renderLog)}
        {logs.isLoading&&<div className="empty">加载交易日志中…</div>}
        {!logs.isLoading&&!logs.data?.length&&<div className="empty">还没有日志。每天收盘后写一条，数据只对当前登录用户可见。</div>}
      </div>
    <Sheet open={editorOpen} onClose={reset} title={editing?'编辑交易日志':'新建交易日志'}>
      <form className="journal-editor" onSubmit={event=>{event.preventDefault();save.mutate()}}>
        <div className="journal-editor-intro"><div><p className="eyebrow">{editing?'EDIT ENTRY':'NEW ENTRY'}</p><h2>{editing?'编辑交易日志':'把这次交易留下来'}</h2></div><span>当前用户：{username}</span></div>
        <label className="journal-date-field">日期<input type="date" value={form.trade_date} onChange={e=>setForm({...form,trade_date:e.target.value})} required disabled={editing?.source_type==='ibkr_sync'}/></label>
        <label className="journal-note">简短备注<input value={form.note} onChange={e=>setForm({...form,note:e.target.value})} placeholder="一句话记录当天最重要的交易背景"/></label>
        <label className="journal-note">文字记录<textarea value={form.content} onChange={e=>setForm({...form,content:e.target.value})} placeholder="记录交易计划、执行、情绪、复盘和明天要验证的条件"/></label>
        {editing?.source_type==='ibkr_sync'&&<div className="journal-objective-note"><b>以下为 IBKR 只读事实</b><span>成交、费用、汇率和仓位变化不会被日志编辑覆盖，也不会反向修改持仓。</span></div>}
        <div className={`journal-table ${editing?.source_type==='ibkr_sync'?'journal-table-readonly':''}`}>
          <div className="journal-table-heading"><div><b>交易明细</b><span>{form.table_rows.length} 张便签</span></div><small>{editing?.source_type==='ibkr_sync'?'来自 IBKR，不可编辑':'仅用于复盘，不会修改持仓'}</small></div>
          {form.table_rows.map((row,index)=><div className="journal-row-note" key={index}>
            <div className="journal-row-top"><label><span>标的</span><SecuritySearchAutocomplete compact value={rowSecurities[index]||null} onSelect={security=>{setRowSecurities(items=>items.map((item,i)=>i===index?security:item));updateRow(index,{ticker:security?.display_symbol||'',security_id:security?.security_id||null})}} placeholder="搜索代码或公司"/></label><label><span>方向</span><select value={row.direction} onChange={e=>updateRow(index,{direction:e.target.value})}><option value="">选择方向</option><option>买入</option><option>卖出</option><option>观望</option><option>挂单</option></select></label><button type="button" className="row-delete" aria-label="删除这笔交易" onClick={()=>removeRow(index)}><TrashIcon/></button></div>
            <div className="journal-row-bottom"><label><span>数量</span><input type="number" inputMode="decimal" min="0" step="any" value={row.quantity??''} onChange={e=>updateRow(index,{quantity:e.target.value===''?null:Number(e.target.value)})} placeholder="0"/></label><label><span>价格</span><input type="number" inputMode="decimal" min="0" step="any" value={row.price??''} onChange={e=>updateRow(index,{price:e.target.value===''?null:Number(e.target.value)})} placeholder="0.00"/></label><label><span>自定义标签</span><input value={row.strategy} onChange={e=>updateRow(index,{strategy:e.target.value})} placeholder="突破 / 试仓"/></label><label><span>其他</span><input value={row.result} onChange={e=>updateRow(index,{result:e.target.value})} placeholder="补充说明"/></label></div>
          </div>)}
          {editing?.source_type!=='ibkr_sync'&&<button type="button" className="add-note-btn" onClick={()=>{setForm(f=>({...f,table_rows:[...f.table_rows,emptyTradeRow()]}));setRowSecurities(items=>[...items,null])}}><span>＋</span> 添加交易便签</button>}
        </div>
        <div className="photo-uploader"><label>照片<input type="file" accept="image/*" multiple onChange={e=>addPhotos(e.target.files)}/></label><div className="photo-grid">{form.photo_urls.map((src,index)=><div className="photo-thumb" key={index}><img src={src} alt={`交易截图 ${index+1}`}/><button type="button" onClick={()=>setForm(f=>({...f,photo_urls:f.photo_urls.filter((_,i)=>i!==index)}))}>移除</button></div>)}</div></div>
        {save.error&&<p className="error">{save.error.message}</p>}
        <div className="journal-actions"><button disabled={save.isPending}>{save.isPending?'保存中…':'保存日志'}</button>{editing&&<button type="button" className="ghost-btn" onClick={reset}>取消编辑</button>}</div>
      </form>
    </Sheet>
  </div>
}

type FmpStatus = {quota_day:string;requests_used:number;requests_remaining:number;usable_limit:number;last_processed_ticker:string|null;pending_profile_count:number;pending_history_count:number;pending_analysis_count:number;failed_item_count:number;quota_timezone:string}

function AdminOperationsPanel() {
  const client = useQueryClient()
  const fmp = useQuery({queryKey:['admin-fmp-status'],queryFn:()=>api<FmpStatus>('/admin/fmp/status'),refetchInterval:60_000})
  const syncFmp = useMutation({mutationFn:()=>post('/admin/fmp/sync',{}),onSuccess:()=>setTimeout(()=>client.invalidateQueries({queryKey:['admin-fmp-status']}),1500)})
  return <div style={{marginTop:32}}>
    <div className="section-title"><div><p>FMP · UTC QUOTA</p><h2>资料与技术分析同步</h2></div><button onClick={()=>syncFmp.mutate()} disabled={syncFmp.isPending}>{syncFmp.isPending?'正在排队…':'排队同步'}</button></div>
    {fmp.data?<div className="technical-metrics admin-fmp"><div><span>今日已用</span><b>{fmp.data.requests_used} / {fmp.data.usable_limit}</b></div><div><span>剩余请求</span><b>{fmp.data.requests_remaining}</b></div><div><span>资料待处理</span><b>{fmp.data.pending_profile_count}</b></div><div><span>行情待处理</span><b>{fmp.data.pending_history_count}</b></div><div><span>分析待处理</span><b>{fmp.data.pending_analysis_count}</b></div><div><span>失败项目</span><b>{fmp.data.failed_item_count}</b><small>{fmp.data.last_processed_ticker&&`最近 ${fmp.data.last_processed_ticker}`}</small></div></div>:<div className="empty">正在读取 FMP 配额状态…</div>}
  </div>
}
