const BASE = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '')
const KEY  = import.meta.env.VITE_API_KEY  || ''

const defaultHeaders = KEY ? { 'x-api-key': KEY } : {}

export function apiFetch(path, options = {}) {
  const headers = { ...defaultHeaders, ...(options.headers || {}) }
  return fetch(`${BASE}${path}`, { ...options, headers })
}

export const API = BASE
