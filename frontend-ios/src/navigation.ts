export type RootTab = 'overview' | 'chat' | 'fundamentals' | 'more'
export type DetailRoute = { kind: 'stock' | 'position' | 'candidate' | 'reports' | 'watchlist' | 'activity' | 'discovery' | 'journal'; id?: string | number; segment?: 'news' | 'calendar' | 'reports'; mode?: 'list' | 'new' }
export type NavigationState = { tab: RootTab; stack: DetailRoute[] }
export type NavigationAction = { type: 'tab'; tab: RootTab } | { type: 'push'; route: DetailRoute } | { type: 'back' }

export const initialNavigation: NavigationState = { tab: 'overview', stack: [] }

export function navigationReducer(state: NavigationState, action: NavigationAction): NavigationState {
  if (action.type === 'tab') return { tab: action.tab, stack: [] }
  if (action.type === 'push') return { ...state, stack: [...state.stack, action.route] }
  return { ...state, stack: state.stack.slice(0, -1) }
}
