import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '@/lib/auth'

export default function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  if (user) return <Navigate to="/chat" replace />

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(email, password)
      navigate('/chat', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error de inicio de sesion')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex bg-surface">
      {/* LEFT — Branding */}
      <div className="hidden lg:flex lg:w-1/2 bg-on-surface flex-col justify-between p-12 text-surface-container-lowest">
        <div>
          <img src="/logo-roddos.jpeg" alt="RODDOS" className="h-10 mb-16" />
          <h1 className="font-display text-4xl font-bold leading-tight mb-4">
            Precision.<br />
            Administrative<br />
            Excellence.
          </h1>
          <p className="text-on-surface-variant text-sm max-w-sm">
            Portal corporativo de gestion contable y financiera.
            Sistema integral de monitoreo operativo.
          </p>
        </div>
        <div className="flex gap-12 text-xs text-on-surface-variant">
          <div>
            <div className="font-display text-2xl font-bold text-surface-container-lowest">99.9%</div>
            <div>Uptime</div>
          </div>
          <div>
            <div className="font-display text-2xl font-bold text-surface-container-lowest">256-bit</div>
            <div>Encryption</div>
          </div>
          <div>
            <div className="font-display text-2xl font-bold text-surface-container-lowest">Real-time</div>
            <div>Sync with Alegra</div>
          </div>
        </div>
      </div>

      {/* RIGHT — Login Form */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-8">
        <form onSubmit={handleSubmit} className="w-full max-w-sm">
          <div className="glass rounded-lg p-8 shadow-ambient-2">
            <div className="lg:hidden mb-8 flex justify-center">
              <img src="/logo-roddos.jpeg" alt="RODDOS" className="h-8" />
            </div>

            <h2 className="font-display text-xl font-bold text-on-surface mb-1">Welcome back</h2>
            <p className="text-sm text-on-surface-variant mb-8">Sign in to your account</p>

            {error && (
              <div className="mb-6 p-3 text-sm bg-error-light text-error rounded-md">
                {error}
              </div>
            )}

            <label className="block mb-2 text-xs font-medium text-on-surface-variant uppercase tracking-wider">
              Corporate Email
            </label>
            <div className="relative mb-5">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-on-surface-variant" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0l-9.75 6.093L2.25 6.75" />
              </svg>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full pl-10 pr-4 py-3 bg-surface-container-low rounded-md text-sm text-on-surface placeholder:text-on-surface-variant focus:outline-none focus:ring-2 focus:ring-primary/30"
                placeholder="usuario@roddos.com"
              />
            </div>

            <label className="block mb-2 text-xs font-medium text-on-surface-variant uppercase tracking-wider">
              Password
            </label>
            <div className="relative mb-8">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-on-surface-variant" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
              </svg>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full pl-10 pr-4 py-3 bg-surface-container-low rounded-md text-sm text-on-surface placeholder:text-on-surface-variant focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-primary text-white text-sm font-medium rounded-md hover:brightness-110 disabled:opacity-50 transition-all"
            >
              {loading ? 'Signing in...' : 'Sign In to Portal →'}
            </button>
          </div>

          <p className="text-center text-xs text-on-surface-variant mt-6">
            &copy; 2026 RODDOS S.A.S. All rights reserved.
          </p>
        </form>
      </div>
    </div>
  )
}
