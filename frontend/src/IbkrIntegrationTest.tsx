import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api, getToken } from './api'

export type IbkrResult = {
  success:boolean; operation:string; timestamp:string; started_at?:string; completed_at?:string; duration_ms:number;
  request?:{method:string;path:string;query:Record<string,unknown>}; status_code:number|null; normalized:unknown; raw:unknown;
  warnings:string[]; error?:{code:string;message:string;detail?:string|null}|null
}
type Config = {cp_enabled:boolean;cp_login_url:string;cp_verify_ssl:boolean;username_hint:string;credential_storage_enabled:boolean;flex_enabled:boolean;flex_configured:boolean;proxy_enforced:boolean;read_only:boolean;warnings:string[]}
type CredentialStatus = {saved:boolean;username_hint:string}
type Account = {account_id:string;display_name:string|null;currency:string|null;brokerage_access:boolean|null}
type LogRow = {at:string;label:string;result:IbkrResult}

const labels:Record<string,string> = {
  gateway_health:'检查 Gateway',auth_status:'检查认证状态',initialize_session:'初始化 Brokerage Session',tickle:'发送 Tickle',
  get_accounts:'读取账户列表',get_account_summary:'读取账户摘要',get_positions:'读取当前仓位',get_open_orders:'读取未成交订单',
  get_trades:'读取当日成交',flex_test:'测试 Flex 配置',flex_run:'运行 Flex Query',
}
export const ibkrErrorText=(code?:string)=>({
  GATEWAY_DISABLED:'IBKR Client Portal Gateway 尚未启用。',
  GATEWAY_UNAVAILABLE:'无法连接 VPS 本机的 Client Portal Gateway。请检查 systemd 服务和 127.0.0.1:5000。',
  GATEWAY_TIMEOUT:'访问 Gateway 超时，请检查本机服务。',
  AUTHENTICATION_REQUIRED:'Gateway 已运行，但尚未登录 IBKR。请在上方直接登录，并在手机完成 IB Key 授权。',
  BROKERAGE_SESSION_NOT_CONNECTED:'Brokerage Session 尚未连接。请确认后再手动初始化。',
  COMPETING_SESSION:'检测到其他 IBKR 客户端正在占用 Brokerage Session。系统不会自动抢占会话。',
  FLEX_NOT_CONFIGURED:'Flex Web Service 尚未配置。请在 .env 中填写 Token 和 Query ID 后重启后端。',
  FLEX_REQUEST_FAILED:'Flex 请求失败，请检查配置与 10808 代理。',IBKR_INVALID_RESPONSE:'IBKR 返回了无法解析的响应。',
  IBKR_API_ERROR:'IBKR API 请求失败。',
}[code||'']||'请求失败')

export function loginRequest(username:string,password:string,saveCredentials:boolean){return {username,password,save_credentials:saveCredentials}}
export const IBKR_AUTOMATIC_REQUESTS=['/admin/integrations/ibkr/config','/admin/integrations/ibkr/login/credentials'] as const
export function filterRawResponse(raw:string,search:string){return search?raw.split('\n').filter(line=>line.toLowerCase().includes(search.toLowerCase())).join('\n'):raw}
export function retainSelectedAccount(accounts:Account[],current:string){return accounts.some(account=>account.account_id===current)?current:''}

async function ibkrRequest(path:string,method:'GET'|'POST',body:Record<string,never>):Promise<IbkrResult>{
  const token=getToken()
  const response=await fetch(`/api${path}`,{method,headers:{'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`}:{})},...(method==='POST'?{body:JSON.stringify(body)}:{})})
  const data=await response.json() as IbkrResult
  return data
}

function status(value:boolean|undefined, yes='是', no='否'){return value===undefined?'未检查':value?yes:no}
function valueText(value:unknown){return value===null||value===undefined||value===''?'—':String(value)}

export function IbkrIntegrationTest(){
  const config=useQuery({queryKey:['ibkr-config'],queryFn:()=>api<Config>('/admin/integrations/ibkr/config'),staleTime:60_000})
  const credentials=useQuery({queryKey:['ibkr-credentials'],queryFn:()=>api<CredentialStatus>('/admin/integrations/ibkr/login/credentials'),staleTime:30_000})
  const [username,setUsername]=useState('')
  const [password,setPassword]=useState('')
  const [showPassword,setShowPassword]=useState(false)
  const [saveCredentials,setSaveCredentials]=useState(true)
  const [loginMessage,setLoginMessage]=useState('')
  const [result,setResult]=useState<IbkrResult|null>(null)
  const [logs,setLogs]=useState<LogRow[]>([])
  const [accounts,setAccounts]=useState<Account[]>([])
  const [accountId,setAccountId]=useState('')
  const [outputTab,setOutputTab]=useState<'normalized'|'raw'|'request'>('normalized')
  const [rawSearch,setRawSearch]=useState('')
  const [gatewayStatus,setGatewayStatus]=useState<boolean|undefined>()
  const [authStatus,setAuthStatus]=useState<Record<string,unknown>|undefined>()
  const effectiveUsername=username||config.data?.username_hint||''
  const login=useMutation({
    mutationFn:()=>api<{success:boolean;authenticated:boolean}>('/admin/integrations/ibkr/login',{method:'POST',body:JSON.stringify(loginRequest(effectiveUsername,password,saveCredentials))}),
    onMutate:()=>setLoginMessage('正在通过 Gateway 登录；如果手机收到 IB Key，请批准…'),
    onSuccess:async()=>{setPassword('');setAuthStatus({authenticated:true,connected:false});setLoginMessage('登录成功，Gateway 已认证。');await Promise.all([credentials.refetch(),config.refetch()])},
    onError:error=>setLoginMessage(error instanceof Error?error.message:'登录失败'),
  })
  const loginSaved=useMutation({
    mutationFn:()=>api<{success:boolean;authenticated:boolean}>('/admin/integrations/ibkr/login',{method:'POST',body:JSON.stringify(loginRequest('','',false))}),
    onMutate:()=>setLoginMessage('正在使用已保存凭据登录；请在手机批准 IB Key…'),
    onSuccess:()=>{setAuthStatus({authenticated:true,connected:false});setLoginMessage('登录成功，Gateway 已认证。')},
    onError:error=>setLoginMessage(error instanceof Error?error.message:'登录失败'),
  })
  const removeSaved=useMutation({mutationFn:()=>api('/admin/integrations/ibkr/login/credentials',{method:'DELETE'}),onSuccess:()=>{setLoginMessage('已删除服务端保存的 IBKR 凭据。');credentials.refetch()}})
  const action=useMutation({
    mutationFn:async({path,method}:{path:string;method:'GET'|'POST'})=>ibkrRequest(path,method,{}),
    onSuccess:data=>{
      setResult(data);setLogs(rows=>[{at:new Date().toLocaleTimeString('zh-CN',{hour12:false}),label:labels[data.operation]||data.operation,result:data},...rows])
      if(data.operation==='get_accounts'&&Array.isArray(data.normalized)){const next=data.normalized as Account[];setAccounts(next);setAccountId(current=>retainSelectedAccount(next,current))}
      if(data.operation==='gateway_health'&&data.success)setGatewayStatus(Boolean((data.normalized as Record<string,unknown>)?.reachable))
      if(data.operation==='auth_status'&&data.success)setAuthStatus(data.normalized as Record<string,unknown>)
    },
    onError:error=>{const fallback:IbkrResult={success:false,operation:'request',timestamp:new Date().toISOString(),duration_ms:0,status_code:null,normalized:null,raw:null,warnings:[],error:{code:'NETWORK_ERROR',message:error instanceof Error?error.message:String(error)}};setResult(fallback)},
  })
  const run=(path:string,method:'GET'|'POST'='GET')=>action.mutate({path,method})
  const accountPath=(suffix:string)=>`/admin/integrations/ibkr/accounts/${encodeURIComponent(accountId)}/${suffix}`
  const rawText=useMemo(()=>typeof result?.raw==='string'?result.raw:JSON.stringify(result?.raw,null,2),[result])
  const displayedRaw=filterRawResponse(rawText||'',rawSearch)
  const normalized=result?.normalized as Record<string,unknown>|unknown[]|null
  return <div className="ibkr-test">
    <section className="ibkr-warning"><div><p className="eyebrow">EXPERIMENTAL · ADMIN ONLY</p><h2>IBKR 集成测试</h2><p>实验性功能 · 只读测试 · 不会执行交易</p></div><span>READ ONLY</span></section>
    <section className="ibkr-status-grid">
      <StatusCard label="Client Portal Gateway" value={config.data?.cp_enabled} yes="已启用" no="未启用"/>
      <StatusCard label="Gateway 网络" value={gatewayStatus} yes="可访问" no="不可访问"/>
      <StatusCard label="IBKR 认证" value={authStatus?.authenticated as boolean|undefined} yes="已认证" no="未认证"/>
      <StatusCard label="Brokerage Session" value={authStatus?.connected as boolean|undefined} yes="已连接" no="未连接"/>
      <StatusCard label="Competing Session" value={authStatus?.competing as boolean|undefined}/>
      <StatusCard label="Flex Web Service" value={config.data?.flex_configured} yes="已配置" no="未配置"/>
      <div className="ibkr-status-card"><span>上次请求</span><b>{result?new Date(result.timestamp).toLocaleString('zh-CN'):'未检查'}</b><small>{result?`${result.duration_ms}ms · HTTP ${result.status_code??'—'}`:'等待手动操作'}</small></div>
      <div className="ibkr-status-card"><span>网络安全</span><b>{config.data?.proxy_enforced?'10808 强制代理':'配置异常'}</b><small>IBKR 外联 fail-closed，无 direct fallback</small></div>
    </section>
    <section className="ibkr-login-panel">
      <div><p className="eyebrow">SERVER-SIDE GATEWAY LOGIN</p><h3>直接登录 IBKR</h3><p>后端会打开 Gateway、代填凭据并执行官方 SRP 登录。收到 IB Key 后只需在手机批准。</p>{credentials.data?.saved&&<p className="positive">已保存凭据：{credentials.data.username_hint}</p>}</div>
      <div className="ibkr-login-fields"><label>IBKR 用户名<input value={effectiveUsername} onChange={e=>setUsername(e.target.value)} autoComplete="username"/></label><label>IBKR 密码<span className="ibkr-password"><input type={showPassword?'text':'password'} value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password"/><button type="button" onClick={()=>setShowPassword(v=>!v)}>{showPassword?'隐藏':'显示'}</button></span></label><label className="ibkr-save"><input type="checkbox" checked={saveCredentials} onChange={e=>setSaveCredentials(e.target.checked)} disabled={!config.data?.credential_storage_enabled}/> 加密保存到服务器，以后无需重复输入</label></div>
      <div className="ibkr-login-controls"><button type="button" onClick={()=>login.mutate()} disabled={login.isPending||loginSaved.isPending||!effectiveUsername||!password}>登录并等待手机批准</button>{credentials.data?.saved&&<button type="button" onClick={()=>loginSaved.mutate()} disabled={login.isPending||loginSaved.isPending}>使用已保存凭据登录</button>}{credentials.data?.saved&&<button type="button" className="ghost-btn" onClick={()=>removeSaved.mutate()} disabled={removeSaved.isPending}>删除保存的凭据</button>}</div>
      {loginMessage&&<div className="ibkr-login-message">{loginMessage}</div>}
    </section>
    <section className="ibkr-actions"><div className="section-title"><div><p>MANUAL TESTS</p><h2>只读操作</h2></div></div><div className="ibkr-action-grid">
      <Action label="检查 Gateway" busy={action.isPending} onClick={()=>run('/admin/integrations/ibkr/gateway/health')}/>
      <Action label="检查认证状态" busy={action.isPending} onClick={()=>run('/admin/integrations/ibkr/auth/status')}/>
      <Action label="初始化 Brokerage Session" busy={action.isPending} onClick={()=>{if(window.confirm('初始化可能影响同一用户名的 brokerage session。系统固定 compete=false，不会抢占其他会话。是否继续？'))run('/admin/integrations/ibkr/session/initialize','POST')}}/>
      <Action label="发送 Tickle" busy={action.isPending} onClick={()=>run('/admin/integrations/ibkr/tickle','POST')}/>
      <Action label="读取账户列表" busy={action.isPending} onClick={()=>run('/admin/integrations/ibkr/accounts')}/>
      <Action label="测试 Flex 配置" busy={action.isPending} onClick={()=>run('/admin/integrations/ibkr/flex/test','POST')}/>
      <Action label="运行 Flex Query" busy={action.isPending} onClick={()=>run('/admin/integrations/ibkr/flex/run','POST')}/>
      <button type="button" className="ghost-btn" onClick={()=>{setResult(null);setLogs([])}}>清空测试输出</button>
    </div></section>
    <section className="ibkr-account-panel"><label>账户<select value={accountId} onChange={e=>setAccountId(e.target.value)}><option value="">请选择已读取账户</option>{accounts.map(account=><option value={account.account_id} key={account.account_id}>{account.account_id} {account.display_name?`/ ${account.display_name}`:''}</option>)}</select></label><div>
      <Action label="读取账户摘要" busy={action.isPending} disabled={!accountId} onClick={()=>run(accountPath('summary'))}/><Action label="读取当前仓位" busy={action.isPending} disabled={!accountId} onClick={()=>run(accountPath('positions'))}/><Action label="读取未成交订单" busy={action.isPending} disabled={!accountId} onClick={()=>run(accountPath('orders'))}/><Action label="读取当日成交" busy={action.isPending} disabled={!accountId} onClick={()=>run(accountPath('trades'))}/>
    </div></section>
    <section className="ibkr-output"><div className="ibkr-output-tabs"><button className={outputTab==='normalized'?'active':''} onClick={()=>setOutputTab('normalized')}>结构化结果</button><button className={outputTab==='raw'?'active':''} onClick={()=>setOutputTab('raw')}>原始响应</button><button className={outputTab==='request'?'active':''} onClick={()=>setOutputTab('request')}>请求信息</button></div>
      {!result?<div className="empty">页面不会自动请求 IBKR。请选择上方操作开始测试。</div>:result.error?<div className="error"><b>{result.error.code}</b><p>{ibkrErrorText(result.error.code)}</p><small>{result.error.message}</small></div>:outputTab==='normalized'?<NormalizedResult operation={result.operation} value={result.normalized}/>:outputTab==='raw'?<div className="ibkr-code"><div><input placeholder="搜索原始响应" value={rawSearch} onChange={e=>setRawSearch(e.target.value)}/><button onClick={()=>navigator.clipboard?.writeText(rawText||'')}>复制</button></div><details open><summary>安全清理后的原始响应</summary><pre>{displayedRaw||'—'}</pre></details></div>:<dl className="ibkr-request-info"><dt>operation</dt><dd>{result.operation}</dd><dt>HTTP</dt><dd>{result.request?.method||'—'} {result.request?.path||'—'}</dd><dt>query</dt><dd><code>{JSON.stringify(result.request?.query||{})}</code></dd><dt>status code</dt><dd>{result.status_code??'—'}</dd><dt>started_at</dt><dd>{result.started_at||'—'}</dd><dt>completed_at</dt><dd>{result.completed_at||result.timestamp}</dd><dt>duration</dt><dd>{result.duration_ms}ms</dd><dt>warnings</dt><dd>{result.warnings?.join('；')||'无'}</dd></dl>}
    </section>
    <section className="ibkr-session-log"><div className="section-title"><div><p>SESSION ONLY</p><h2>本页测试日志</h2></div></div>{logs.map((row,index)=><div key={`${row.at}-${index}`}><time>{row.at}</time><b>{row.label}</b><span className={row.result.success?'positive':'negative'}>{row.result.success?'成功':'失败'}</span><span>{row.result.status_code??'—'}</span><span>{row.result.duration_ms}ms</span></div>)}{!logs.length&&<div className="empty">记录只保存在当前页面内存中，刷新后清空。</div>}</section>
  </div>
}

export function StatusCard({label,value,yes='是',no='否'}:{label:string;value:boolean|undefined;yes?:string;no?:string}){return <div className={`ibkr-status-card ${value===undefined?'':value?'ok':'bad'}`}><span>{label}</span><b>{status(value,yes,no)}</b><small>{value===undefined?'等待手动检查':value?'状态正常':'需要处理'}</small></div>}
export function Action({label,busy,disabled,onClick}:{label:string;busy:boolean;disabled?:boolean;onClick:()=>void}){return <button type="button" disabled={busy||disabled} onClick={onClick}>{busy?'请求进行中…':label}</button>}
function NormalizedResult({operation,value}:{operation:string;value:unknown}){
  if(operation==='get_account_summary'&&value&&typeof value==='object'&&!Array.isArray(value)){const rows=value as Record<string,unknown>;const fields=[['net_liquidation','Net Liquidation'],['total_cash','Total Cash'],['buying_power','Buying Power'],['available_funds','Available Funds'],['excess_liquidity','Excess Liquidity'],['initial_margin','Initial Margin'],['maintenance_margin','Maintenance Margin'],['unrealized_pnl','Unrealized P&L'],['realized_pnl','Realized P&L'],['base_currency','Base Currency']];return <div className="ibkr-summary-grid">{fields.map(([key,label])=><div key={key}><span>{label}</span><b>{valueText(rows[key])}</b></div>)}</div>}
  if(operation==='get_positions'&&Array.isArray(value)){const keys=['symbol','conid','asset_class','exchange','currency','position','average_cost','market_price','market_value','unrealized_pnl','realized_pnl','account_id'];return <div className="table-scroll"><table><thead><tr>{keys.map(key=><th key={key}>{key.replaceAll('_',' ')}</th>)}</tr></thead><tbody>{value.map((row,index)=><tr key={index}>{keys.map(key=><td key={key}>{valueText((row as Record<string,unknown>)[key])}</td>)}</tr>)}</tbody></table></div>}
  return <pre className="ibkr-normalized-json">{JSON.stringify(value,null,2)||'—'}</pre>
}
