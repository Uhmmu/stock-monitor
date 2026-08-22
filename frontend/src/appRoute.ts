const APPLE_PREFIX = '/appledesign'

export function isAppleDesignPath(pathname = window.location.pathname) {
  const path = pathname.replace(/\/+$/, '') || '/'
  return path === APPLE_PREFIX || path.startsWith(`${APPLE_PREFIX}/`)
}

export function appPath(pathname = window.location.pathname) {
  if (!isAppleDesignPath(pathname)) return pathname
  return pathname.slice(APPLE_PREFIX.length) || '/'
}

export function appHref(target: string, pathname = window.location.pathname) {
  if (!isAppleDesignPath(pathname) || target === APPLE_PREFIX || target.startsWith(`${APPLE_PREFIX}/`)) return target
  return `${APPLE_PREFIX}${target === '/' ? '' : target}`
}
