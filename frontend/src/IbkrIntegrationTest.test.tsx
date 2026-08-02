import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Action, IBKR_AUTOMATIC_REQUESTS, StatusCard, filterRawResponse, ibkrErrorText, loginRequest, retainSelectedAccount } from './IbkrIntegrationTest'

describe('IBKR 登录和只读测试',()=>{
  it('登录请求可明确提交并选择保存凭据',()=>expect(loginRequest('user','top-secret',true)).toEqual({username:'user',password:'top-secret',save_credentials:true}))
  it('为 competing session 给出不抢占提示',()=>expect(ibkrErrorText('COMPETING_SESSION')).toContain('不会自动抢占'))
  it('服务端渲染不会泄露密码',()=>expect(renderToStaticMarkup(<input type="password" defaultValue=""/>)).not.toContain('top-secret'))
  it('页面加载只读取配置和凭据状态，不自动登录',()=>expect(IBKR_AUTOMATIC_REQUESTS).toEqual(['/admin/integrations/ibkr/config','/admin/integrations/ibkr/login/credentials']))
  it('请求中状态会禁用按钮并显示 loading',()=>{const html=renderToStaticMarkup(<Action label="读取账户" busy onClick={()=>undefined}/>);expect(html).toContain('disabled');expect(html).toContain('请求进行中')})
  it('状态卡正确展示认证状态',()=>expect(renderToStaticMarkup(<StatusCard label="IBKR 认证" value yes="已认证" no="未认证"/>)).toContain('已认证'))
  it('账户切换仅保留仍在 allowlist 的账户',()=>{const rows=[{account_id:'DU1',display_name:null,currency:'USD',brokerage_access:true}];expect(retainSelectedAccount(rows,'DU1')).toBe('DU1');expect(retainSelectedAccount(rows,'U2')).toBe('')})
  it('原始 JSON 搜索只保留匹配行',()=>expect(filterRawResponse('{\n  "symbol":"AAPL",\n  "currency":"USD"\n}','aapl')).toContain('AAPL'))
  it('Flex 未配置显示明确提示',()=>expect(ibkrErrorText('FLEX_NOT_CONFIGURED')).toContain('.env'))
  it('清空输出的空状态由 null 结果表示',()=>expect({result:null,logs:[]}).toEqual({result:null,logs:[]}))
})
