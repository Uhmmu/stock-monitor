// 客户端查询缓存：把 TanStack Query 的成功结果持久化到 IndexedDB。
// 冷加载时先渲染上次的数据（stale-while-revalidate），后台刷新完成后由 react-query 自动切换为新数据。
// 缓存按登录用户隔离；退出登录或切换账号时整份清空，不跨用户展示持仓等私有数据。
import { dehydrate, hydrate, type DehydratedState, type QueryClient } from '@tanstack/react-query'

export const QUERY_CACHE_BUSTER = 'qcache-v1'
export const QUERY_CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000
const QUERY_CACHE_MAX_CHARS = 24 * 1024 * 1024
const SAVE_THROTTLE_MS = 3000
const RESTORE_TIMEOUT_MS = 600

export type CacheKVStorage = {
  get(): Promise<string | null>
  set(value: string): Promise<void>
  del(): Promise<void>
}

type StoredQueryCache = { buster: string; user: string | null; savedAt: number; state: DehydratedState }

function createIdbStorage(): CacheKVStorage | null {
  if (typeof indexedDB === 'undefined') return null
  let dbPromise: Promise<IDBDatabase> | null = null
  const open = () => {
    if (!dbPromise) {
      dbPromise = new Promise((resolve, reject) => {
        const request = indexedDB.open('stock-monitor-cache', 1)
        request.onupgradeneeded = () => { request.result.createObjectStore('kv') }
        request.onsuccess = () => resolve(request.result)
        request.onerror = () => { dbPromise = null; reject(request.error ?? new Error('indexeddb open failed')) }
        request.onblocked = () => { dbPromise = null; reject(new Error('indexeddb blocked')) }
      })
    }
    return dbPromise
  }
  const run = (mode: IDBTransactionMode, action: (store: IDBObjectStore) => void, capture?: (store: IDBObjectStore) => IDBRequest) =>
    open().then(db => new Promise<string | null>((resolve, reject) => {
      const tx = db.transaction('kv', mode)
      const store = tx.objectStore('kv')
      let result: string | null = null
      const read = capture?.(store)
      if (read) read.onsuccess = () => { result = (read.result as string | undefined) ?? null }
      action(store)
      tx.oncomplete = () => resolve(result)
      tx.onerror = () => reject(tx.error ?? new Error('indexeddb transaction failed'))
      tx.onabort = () => reject(tx.error ?? new Error('indexeddb transaction aborted'))
    }))
  return {
    get: () => run('readonly', () => {}, store => store.get('query-cache')),
    set: value => run('readwrite', store => { store.put(value, 'query-cache') }).then(() => undefined),
    del: () => run('readwrite', store => { store.delete('query-cache') }).then(() => undefined),
  }
}

let defaultStorage: CacheKVStorage | null | undefined
let cacheOwner: string | null = null

function storage(options?: { storage?: CacheKVStorage | null }): CacheKVStorage | null {
  if (options?.storage !== undefined) return options.storage
  if (defaultStorage === undefined) defaultStorage = createIdbStorage()
  return defaultStorage
}

export function currentQueryCacheOwner(): string | null {
  return cacheOwner
}

export function filterExpiredQueries(state: DehydratedState, now: number, maxAgeMs: number): DehydratedState {
  return { ...state, queries: state.queries.filter(query => {
    const updatedAt = query.state.dataUpdatedAt
    return typeof updatedAt === 'number' && updatedAt > 0 && now - updatedAt <= maxAgeMs
  }) }
}

export function trimStateToBudget(state: DehydratedState, maxChars: number): DehydratedState {
  let serialized = JSON.stringify(state)
  if (serialized.length <= maxChars) return state
  const queries = [...state.queries].sort((a, b) => (a.state.dataUpdatedAt || 0) - (b.state.dataUpdatedAt || 0))
  while (queries.length && serialized.length > maxChars) {
    queries.shift()
    serialized = JSON.stringify({ ...state, queries })
  }
  return { ...state, queries }
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('query cache restore timeout')), ms)
    promise.then(value => { clearTimeout(timer); resolve(value) }, error => { clearTimeout(timer); reject(error) })
  })
}

export async function restoreQueryCache(client: QueryClient, options: { storage?: CacheKVStorage | null; now?: number } = {}): Promise<void> {
  const kv = storage(options)
  if (!kv) return
  let raw: string | null = null
  try { raw = await withTimeout(kv.get(), RESTORE_TIMEOUT_MS) } catch { return }
  if (!raw) return
  let parsed: StoredQueryCache
  try { parsed = JSON.parse(raw) as StoredQueryCache } catch { return }
  if (!parsed || parsed.buster !== QUERY_CACHE_BUSTER || !parsed.state?.queries?.length) return
  cacheOwner = parsed.user ?? null
  const fresh = filterExpiredQueries(parsed.state, options.now ?? Date.now(), QUERY_CACHE_MAX_AGE_MS)
  if (fresh.queries.length) hydrate(client, fresh)
}

export function setupQueryCacheAutoSave(client: QueryClient, options: { storage?: CacheKVStorage | null; throttleMs?: number } = {}): () => void {
  const kv = storage(options)
  if (!kv) return () => {}
  const throttleMs = options.throttleMs ?? SAVE_THROTTLE_MS
  let timer: ReturnType<typeof setTimeout> | null = null
  let dirty = false
  let stopped = false
  const save = async () => {
    if (stopped || !dirty) return
    dirty = false
    try {
      const state = trimStateToBudget(dehydrate(client, { shouldDehydrateQuery: query => query.state.status === 'success' }), QUERY_CACHE_MAX_CHARS)
      await kv.set(JSON.stringify({ buster: QUERY_CACHE_BUSTER, user: cacheOwner, savedAt: Date.now(), state } satisfies StoredQueryCache))
    } catch { /* 缓存写入失败不影响页面功能 */ }
  }
  const schedule = () => {
    dirty = true
    if (!timer && !stopped) timer = setTimeout(() => { timer = null; void save() }, throttleMs)
  }
  const unsubscribe = client.getQueryCache().subscribe(schedule)
  const flush = () => { if (timer) { clearTimeout(timer); timer = null } void save() }
  const listeners: Array<[EventTarget, string, EventListener]> = []
  if (typeof window !== 'undefined') {
    const onPageHide: EventListener = () => flush()
    window.addEventListener('pagehide', onPageHide)
    listeners.push([window, 'pagehide', onPageHide])
  }
  if (typeof document !== 'undefined') {
    const onVisibility: EventListener = () => { if (document.visibilityState === 'hidden') flush() }
    document.addEventListener('visibilitychange', onVisibility)
    listeners.push([document, 'visibilitychange', onVisibility])
  }
  return () => {
    stopped = true
    if (timer) { clearTimeout(timer); timer = null }
    unsubscribe()
    for (const [target, event, listener] of listeners) target.removeEventListener(event, listener)
  }
}

export function syncQueryCacheUser(client: QueryClient, username: string | null, options: { storage?: CacheKVStorage | null } = {}): void {
  const drop = () => {
    client.clear()
    void storage(options)?.del().catch(() => {})
  }
  if (username === null) {
    cacheOwner = null
    drop()
    return
  }
  if (cacheOwner !== null && cacheOwner !== username) {
    cacheOwner = null
    drop()
  }
  cacheOwner = username
}
