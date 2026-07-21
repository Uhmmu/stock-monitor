import { describe, expect, it } from 'vitest'
import { securityPayload, type SecuritySearchResult } from './SecuritySearchAutocomplete'

const result = (patch:Partial<SecuritySearchResult>={}):SecuritySearchResult => ({
  provider_key:'yahoo:AAPL', security_id:null, display_symbol:'AAPL', display_name:'Apple Inc.',
  local_symbol:'AAPL', exchange:'NASDAQ', exchange_code:'NMS', market:'US', country_code:'US',
  currency:'USD', instrument_type:'EQUITY', yahoo_symbol:'AAPL', finnhub_symbol:null,
  source:'yahoo', is_local:false, ...patch,
})

describe('securityPayload',()=>{
  it('submits provider symbols for a remote candidate',()=>{
    expect(securityPayload(result())).toEqual({security_id:null,source:'yahoo',yahoo_symbol:'AAPL',finnhub_symbol:null})
  })

  it('submits only the canonical id for a local candidate source',()=>{
    expect(securityPayload(result({provider_key:'security:7',security_id:7,source:'local',is_local:true}))).toEqual({
      security_id:7, source:undefined, yahoo_symbol:'AAPL', finnhub_symbol:null,
    })
  })
})
