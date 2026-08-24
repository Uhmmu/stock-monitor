import { QueryClient, dehydrate } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import {
  QUERY_CACHE_BUSTER,
  QUERY_CACHE_MAX_AGE_MS,
  currentQueryCacheOwner,
  filterExpiredQueries,
  restoreQueryCache,
  setupQueryCacheAutoSave,
  syncQueryCacheUser,
  trimStateToBudget,
  type CacheKVStorage,
} from './queryPersistence'

function memoryStorage() {
  let value: string | null = null
  const store: CacheKVStorage & { peek: () => string | null } = {
    get: async () => value,
    set: async (next: string) => { value = next },
    del: async () => { value = null },
    peek: () => value,
  }
  return store
}

function clientWithData(entries: Record<string, unknown>) {
  const client = new QueryClient()
  for (const [key, data] of Object.entries(entries)) client.setQueryData([key], data)
  return client
}

function storedRecord(user: string | null, state: ReturnType<typeof dehydrate>) {
  return JSON.stringify({ buster: QUERY_CACHE_BUSTER, user, savedAt: Date.now(), state })
}

describe('filterExpiredQueries', () => {
  it('drops queries older than max age and keeps fresh ones', () => {
    const now = Date.now()
    const client = clientWithData({ old: 1, fresh: 2 })
    const state = dehydrate(client)
    state.queries[0].state.dataUpdatedAt = now - QUERY_CACHE_MAX_AGE_MS - 1000
    state.queries[1].state.dataUpdatedAt = now - 60_000
    const filtered = filterExpiredQueries(state, now, QUERY_CACHE_MAX_AGE_MS)
    expect(filtered.queries).toHaveLength(1)
    expect(filtered.queries[0].queryKey).toEqual(['fresh'])
  })
})

describe('trimStateToBudget', () => {
  it('drops the oldest queries first when the cache exceeds the budget', () => {
    const client = clientWithData({ oldest: 'a'.repeat(50), newer: 'b'.repeat(50) })
    const state = dehydrate(client)
    state.queries[0].state.dataUpdatedAt = 1
    state.queries[1].state.dataUpdatedAt = 2
    const trimmed = trimStateToBudget(state, JSON.stringify(state).length - 60)
    expect(trimmed.queries.map(query => query.queryKey)).toEqual([['newer']])
  })
})

describe('restoreQueryCache', () => {
  it('rehydrates persisted data and remembers the owner', async () => {
    const store = memoryStorage()
    await store.set(storedRecord('alice', dehydrate(clientWithData({ portfolio: 'secret', news: [1, 2] }))))
    const client = new QueryClient()
    await restoreQueryCache(client, { storage: store })
    expect(client.getQueryData(['portfolio'])).toBe('secret')
    expect(client.getQueryData(['news'])).toEqual([1, 2])
    expect(currentQueryCacheOwner()).toBe('alice')
  })

  it('ignores records written by a different cache schema version', async () => {
    const store = memoryStorage()
    syncQueryCacheUser(new QueryClient(), null, { storage: store })
    await store.set(JSON.stringify({ buster: 'qcache-v0', user: 'alice', savedAt: Date.now(), state: dehydrate(clientWithData({ portfolio: 'secret' })) }))
    const client = new QueryClient()
    await restoreQueryCache(client, { storage: store })
    expect(client.getQueryData(['portfolio'])).toBeUndefined()
    expect(currentQueryCacheOwner()).toBeNull()
  })

  it('ignores expired queries on restore', async () => {
    const store = memoryStorage()
    const state = dehydrate(clientWithData({ stale: 'old', live: 'new' }))
    const now = Date.now()
    state.queries[0].state.dataUpdatedAt = now - QUERY_CACHE_MAX_AGE_MS - 1000
    state.queries[1].state.dataUpdatedAt = now - 1000
    await store.set(storedRecord('alice', state))
    const client = new QueryClient()
    await restoreQueryCache(client, { storage: store, now })
    expect(client.getQueryData(['stale'])).toBeUndefined()
    expect(client.getQueryData(['live'])).toBe('new')
  })
})

describe('setupQueryCacheAutoSave', () => {
  it('persists successful queries after the throttle window', async () => {
    vi.useFakeTimers()
    try {
      const store = memoryStorage()
      const client = clientWithData({})
      const stop = setupQueryCacheAutoSave(client, { storage: store, throttleMs: 3000 })
      client.setQueryData(['dashboard'], { market: { is_open: true } })
      await vi.advanceTimersByTimeAsync(3000)
      const saved = store.peek()
      expect(saved).toBeTruthy()
      const parsed = JSON.parse(saved!) as { buster: string; state: { queries: { queryKey: string[] }[] } }
      expect(parsed.buster).toBe(QUERY_CACHE_BUSTER)
      expect(parsed.state.queries.map(query => query.queryKey)).toEqual([['dashboard']])
      stop()
    } finally {
      vi.useRealTimers()
    }
  })

  it('restores what autosave wrote into a fresh client', async () => {
    vi.useFakeTimers()
    try {
      const store = memoryStorage()
      const writer = clientWithData({ reports: [{ id: 1 }] })
      const stop = setupQueryCacheAutoSave(writer, { storage: store, throttleMs: 3000 })
      writer.setQueryData(['reports'], [{ id: 2 }])
      await vi.advanceTimersByTimeAsync(3000)
      stop()
      const reader = new QueryClient()
      await restoreQueryCache(reader, { storage: store })
      expect(reader.getQueryData(['reports'])).toEqual([{ id: 2 }])
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('syncQueryCacheUser', () => {
  it('clears cache and storage when the account switches', async () => {
    const store = memoryStorage()
    await store.set(storedRecord('alice', dehydrate(clientWithData({ portfolio: 'secret' }))))
    const client = new QueryClient()
    await restoreQueryCache(client, { storage: store })
    client.setQueryData(['dashboard'], { live: true })

    syncQueryCacheUser(client, 'bob', { storage: store })
    expect(client.getQueryData(['portfolio'])).toBeUndefined()
    expect(client.getQueryData(['dashboard'])).toBeUndefined()
    expect(store.peek()).toBeNull()
    expect(currentQueryCacheOwner()).toBe('bob')
  })

  it('keeps data when the same user comes back', async () => {
    const store = memoryStorage()
    await store.set(storedRecord('alice', dehydrate(clientWithData({ portfolio: 'secret' }))))
    const client = new QueryClient()
    await restoreQueryCache(client, { storage: store })
    syncQueryCacheUser(client, 'alice', { storage: store })
    expect(client.getQueryData(['portfolio'])).toBe('secret')
    expect(store.peek()).toBeTruthy()
  })

  it('wipes everything on logout', async () => {
    const store = memoryStorage()
    await store.set(storedRecord('alice', dehydrate(clientWithData({ portfolio: 'secret' }))))
    const client = new QueryClient()
    await restoreQueryCache(client, { storage: store })
    syncQueryCacheUser(client, null, { storage: store })
    expect(client.getQueryData(['portfolio'])).toBeUndefined()
    expect(store.peek()).toBeNull()
    expect(currentQueryCacheOwner()).toBeNull()
  })
})
