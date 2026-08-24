const APP_PREFIXES = ['/beta', '/appledesign'] as const

function appPrefix(pathname: string) {
  const path = pathname.replace(/\/+$/, '') || '/'
  return APP_PREFIXES.find(prefix => path === prefix || path.startsWith(`${prefix}/`)) || ''
}

export function isAppleDesignPath(pathname = window.location.pathname) {
  return appPrefix(pathname) !== ''
}

export function isBetaDesignPath(pathname = window.location.pathname) {
  return appPrefix(pathname) === '/beta'
}

export function appPath(pathname = window.location.pathname) {
  const prefix = appPrefix(pathname)
  return prefix ? pathname.slice(prefix.length) || '/' : pathname
}

export function appHref(target: string, pathname = window.location.pathname) {
  const prefix = appPrefix(pathname)
  if (!prefix || APP_PREFIXES.some(candidate => target === candidate || target.startsWith(`${candidate}/`))) return target
  return `${prefix}${target === '/' ? '' : target}`
}
