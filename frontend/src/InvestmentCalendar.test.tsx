import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { CalendarEmpty, CalendarSkeleton } from './InvestmentCalendar'

describe('投资日历状态',()=>{
  it('加载状态对辅助技术公开忙碌语义',()=>{
    const html=renderToStaticMarkup(<CalendarSkeleton/>)
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain('正在读取投资日历')
  })

  it('空状态提示用户调整日期或证券范围',()=>{
    const html=renderToStaticMarkup(<CalendarEmpty/>)
    expect(html).toContain('没有即将发生的事件')
    expect(html).toContain('扩大日期范围')
  })
})
