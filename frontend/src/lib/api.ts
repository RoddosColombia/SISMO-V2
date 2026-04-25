const BASE = '/api'

// ═══════════════════════════════════════════
// Sliding session helpers (B7-UX)
// ═══════════════════════════════════════════

const PENDING_MSG_KEY = 'sismo:pending:message'

function getToken(): string | null {
  return localStorage.getItem('token')
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** If the response carries X-New-Token, swap it into localStorage silently. */
function captureRenewalHeader(res: Response): void {
  const newToken = res.headers.get('X-New-Token') || res.headers.get('x-new-token')
  if (newToken) {
    try {
      localStorage.setItem('token', newToken)
    } catch {
      // localStorage disabled — ignore, keep old token
    }
  }
}

/** Decode JWT exp claim without verifying signature. Returns ms since epoch, or null. */
export function readTokenExpiryMs(token: string | null): number | null {
  if (!token) return null
  const parts = token.split('.')
  if (parts.length !== 3) return null
  try {
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4)
    const payload = JSON.parse(atob(padded)) as { exp?: number }
    return typeof payload.exp === 'number' ? payload.exp * 1000 : null
  } catch {
    return null
  }
}

/** Save the user's draft message (called before forcing re-login). */
export function savePendingMessage(message: string): void {
  if (!message) return
  try {
    localStorage.setItem(PENDING_MSG_KEY, message)
  } catch { /* ignore */ }
}

/** Read and CLEAR any saved draft message. */
export function popPendingMessage(): string | null {
  try {
    const v = localStorage.getItem(PENDING_MSG_KEY)
    if (v) localStorage.removeItem(PENDING_MSG_KEY)
    return v
  } catch {
    return null
  }
}

/** Shared 401 handler: wipe token (keep sidebar prefs) and redirect. */
function handleUnauthorized(): void {
  try {
    localStorage.removeItem('token')
  } catch { /* ignore */ }
  // Avoid an infinite redirect loop if we're already on /login
  if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
    window.location.href = '/login?reason=expired'
  }
}

// ═══════════════════════════════════════════
// Core fetch wrappers
// ═══════════════════════════════════════════

export async function apiPost<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  captureRenewalHeader(res)
  if (res.status === 401) {
    handleUnauthorized()
    throw new Error('Tu sesión expiró')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Error de red')
  }
  return res.json()
}

export async function apiPatch<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  captureRenewalHeader(res)
  if (res.status === 401) {
    handleUnauthorized()
    throw new Error('Tu sesión expiró')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    const e = new Error(err.detail || 'Error de red') as Error & { status?: number }
    e.status = res.status
    throw e
  }
  return res.json()
}

export async function apiPut<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  captureRenewalHeader(res)
  if (res.status === 401) {
    handleUnauthorized()
    throw new Error('Tu sesión expiró')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    const e = new Error(err.detail || 'Error de red') as Error & { status?: number }
    e.status = res.status
    throw e
  }
  return res.json()
}

export async function apiGet<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: authHeaders(),
  })
  captureRenewalHeader(res)
  if (res.status === 401) {
    handleUnauthorized()
    throw new Error('Tu sesión expiró')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Error de red')
  }
  return res.json()
}

export async function apiDelete<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  captureRenewalHeader(res)
  if (res.status === 401) {
    handleUnauthorized()
    throw new Error('Tu sesión expiró')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Error de red')
  }
  // DELETE may return 204 No Content
  if (res.status === 204) return {} as T
  return res.json()
}

export function chatSSE(
  message: string,
  sessionId: string | null,
  onEvent: (event: { type: string; [key: string]: unknown }) => void,
  onDone: () => void,
  onError: (err: Error) => void,
  imagen?: string | null,
  agentType?: string | null,
): AbortController {
  const controller = new AbortController()

  fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      imagen: imagen || undefined,
      agent_type: agentType || undefined,
    }),
    signal: controller.signal,
  })
    .then(async (res) => {
      captureRenewalHeader(res)
      if (res.status === 401) {
        // Save the draft message so the user recovers it after re-login
        savePendingMessage(message)
        handleUnauthorized()
        throw new Error('Tu sesión expiró')
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const reader = res.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const parsed = JSON.parse(line.slice(6))
              if (parsed.type === 'done') {
                onDone()
              } else {
                onEvent(parsed)
              }
            } catch {
              // skip malformed lines
            }
          }
        }
      }
      onDone()
    })
    .catch((err) => {
      if (err.name !== 'AbortError') onError(err)
    })

  return controller
}
