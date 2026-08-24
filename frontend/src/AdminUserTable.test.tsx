import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { AdminCreateUserForm, AdminUserTable } from './App'

describe('管理员用户管理',()=>{
  it('显示待审核用户操作，但不允许操作管理员账户',()=>{
    const html=renderToStaticMarkup(<AdminUserTable users={[
      {id:1,username:'root',role:'admin',status:'active',note:'主账号',created_at:'2026-08-24T00:00:00Z'},
      {id:2,username:'pending-user',role:'user',status:'pending',note:null,created_at:'2026-08-24T00:00:00Z'},
    ]} onApprove={()=>undefined} onDelete={()=>undefined} onSaveNote={()=>undefined}/>)
    expect(html).toContain('pending-user')
    expect(html).toContain('管理员备注')
    expect(html).toContain('主账号')
    expect(html).toContain('待审核')
    expect(html.match(/>激活</g)).toHaveLength(1)
    expect(html.match(/>删除</g)).toHaveLength(1)
  })

  it('新建用户密码只存在于密码输入框',()=>{
    const html=renderToStaticMarkup(<AdminCreateUserForm busy={false} onCreate={async()=>undefined}/>)
    expect(html).toContain('type="password"')
    expect(html).toContain('autoComplete="new-password"')
    expect(html).toContain('minLength="6"')
    expect(html).toContain('maxLength="72"')
    expect(html).toContain('maxLength="5000"')
    expect(html).not.toContain('top-secret')
  })
})
