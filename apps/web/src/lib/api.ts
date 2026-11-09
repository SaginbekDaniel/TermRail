// Typed API client. All requests carry the bearer token; errors are normalized into ApiError
// with the server's stable error `code` (localized by the UI, see i18n `errors.*`).

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? '/api/v1'
const TOKEN_KEY = 'termrail.token'

let token: string | null = readToken()
let onUnauthorized: (() => void) | null = null

function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function getToken(): string | null {
  return token
}

export function setToken(value: string | null): void {
  token = value
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // Private mode / blocked storage: the session simply lasts for this tab.
  }
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly retryable: boolean
  readonly requestId: string | null
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, retryable = false, requestId: string | null = null,
    details: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.retryable = retryable
    this.requestId = requestId
    this.details = details
  }
}

type Body = Record<string, unknown> | unknown[] | FormData | undefined

interface Options {
  body?: Body
  idempotencyKey?: string
  signal?: AbortSignal
}

async function request<T>(method: string, path: string, opts: Options = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  if (opts.idempotencyKey) headers['Idempotency-Key'] = opts.idempotencyKey
  let body: BodyInit | undefined
  if (opts.body instanceof FormData) body = opts.body
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, { method, headers, body, signal: opts.signal })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, 'NETWORK_ERROR', 'Network error', true)
  }
  if (res.status === 401 && token) onUnauthorized?.()
  if (!res.ok) throw await toApiError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

async function toApiError(res: Response): Promise<ApiError> {
  try {
    const data = (await res.json()) as { error?: { code?: string; message?: string; retryable?: boolean; request_id?: string; details?: Record<string, unknown> } }
    const e = data.error ?? {}
    return new ApiError(res.status, e.code ?? `HTTP_${res.status}`, e.message ?? res.statusText, e.retryable ?? false,
      e.request_id ?? res.headers.get('x-request-id'), e.details ?? {})
  } catch {
    return new ApiError(res.status, `HTTP_${res.status}`, res.statusText, res.status >= 500, res.headers.get('x-request-id'))
  }
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>('GET', path, { signal }),
  post: <T>(path: string, body?: Body, idempotencyKey?: string) => request<T>('POST', path, { body: body ?? {}, idempotencyKey }),
  put: <T>(path: string, body: Body) => request<T>('PUT', path, { body }),
  patch: <T>(path: string, body: Body) => request<T>('PATCH', path, { body }),
  delete: <T>(path: string) => request<T>('DELETE', path),
  upload: <T>(path: string, form: FormData) => request<T>('POST', path, { body: form }),
}

/** Download a protected file (bearer auth) and hand it to the browser as a file save. */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, { headers })
  if (!res.ok) throw await toApiError(res)
  const blob = await res.blob()
  const disposition = res.headers.get('content-disposition') ?? ''
  const match = /filename\*=UTF-8''([^;]+)|filename="([^"]+)"/.exec(disposition)
  const name = match ? decodeURIComponent(match[1] ?? match[2] ?? fallbackName) : fallbackName
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 30_000)
}

/** One key per intended user action (e.g. per form submission) so retries never duplicate it. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID()
}
