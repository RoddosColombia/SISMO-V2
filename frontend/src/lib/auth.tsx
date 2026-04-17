import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import { apiPost, apiGet, readTokenExpiryMs } from './api'

interface User {
  id: string
  email: string
  name: string
  role: string
}

interface AuthContextType {
  user: User | null
  loading: boolean
  expiringSoon: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

// Show warning toast when remaining lifetime drops below this threshold.
const WARN_THRESHOLD_MS = 12 * 60 * 60 * 1000

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [expiringSoon, setExpiringSoon] = useState(false)

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) {
      setLoading(false)
      return
    }
    apiGet<User>('/auth/me')
      .then(setUser)
      .catch(() => localStorage.removeItem('token'))
      .finally(() => setLoading(false))
  }, [])

  // Re-evaluate expiry on mount and every 5 minutes. Each successful request
  // that returns X-New-Token automatically updates localStorage, so the check
  // naturally flips back to false after the next sliding renewal.
  useEffect(() => {
    function evaluate() {
      const token = localStorage.getItem('token')
      const expMs = readTokenExpiryMs(token)
      if (!expMs) {
        setExpiringSoon(false)
        return
      }
      const remaining = expMs - Date.now()
      setExpiringSoon(remaining > 0 && remaining < WARN_THRESHOLD_MS)
    }
    evaluate()
    const id = window.setInterval(evaluate, 5 * 60 * 1000)
    return () => window.clearInterval(id)
  }, [user])

  async function login(email: string, password: string) {
    const res = await apiPost<{ token: string; user: User }>('/auth/login', { email, password })
    localStorage.setItem('token', res.token)
    setUser(res.user)
  }

  function logout() {
    localStorage.removeItem('token')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, expiringSoon, login, logout }}>
      {children}
      <ExpiryWarningToast visible={expiringSoon} />
    </AuthContext.Provider>
  )
}

function ExpiryWarningToast({ visible }: { visible: boolean }) {
  if (!visible) return null
  return (
    <div
      role="status"
      className="fixed bottom-4 right-4 z-[80] max-w-sm bg-amber-50 border border-amber-200 text-amber-900 text-xs rounded-lg shadow-lg px-4 py-3"
    >
      <div className="font-semibold mb-0.5">Tu sesión expira pronto.</div>
      <div className="text-amber-800/90">Cualquier acción la renueva automáticamente.</div>
    </div>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
