import { useEffect, useState } from 'react'
import type { Manifest } from './types'

/**
 * Static-snapshot data access. Snapshots are produced by `repower export-web`
 * into web/public/data/web and served (dev + build) at `${BASE_URL}data/web/`.
 * They're immutable per export, so we cache each fetched path in-memory —
 * re-selecting an already-loaded slice is instant.
 */

const DATA_BASE = import.meta.env.BASE_URL + 'data/web/'

const _cache = new Map<string, Promise<unknown>>()

/** Fetch a snapshot JSON by path (relative to data/web/), cached per path. */
export function getSnapshot<T>(path: string): Promise<T> {
  const url = DATA_BASE + path.replace(/^\/+/, '')
  let p = _cache.get(url) as Promise<T> | undefined
  if (!p) {
    p = fetch(url).then((r) => {
      if (!r.ok) throw new Error(`snapshot ${path}: HTTP ${r.status}`)
      return r.json() as Promise<T>
    })
    // Don't cache a rejected promise (allow retry on next mount).
    p.catch(() => _cache.delete(url))
    _cache.set(url, p)
  }
  return p
}

export interface Async<T> {
  data: T | null
  loading: boolean
  error: Error | null
}

/** React hook: load a snapshot by path. Pass `null` to load nothing. */
export function useSnapshot<T>(path: string | null): Async<T> {
  const [state, setState] = useState<Async<T>>({
    data: null,
    loading: path != null,
    error: null,
  })
  useEffect(() => {
    if (path == null) {
      setState({ data: null, loading: false, error: null })
      return
    }
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    getSnapshot<T>(path)
      .then((data) => alive && setState({ data, loading: false, error: null }))
      .catch((error: Error) => alive && setState({ data: null, loading: false, error }))
    return () => {
      alive = false
    }
  }, [path])
  return state
}

export function useManifest(): Async<Manifest> {
  return useSnapshot<Manifest>('manifest.json')
}
