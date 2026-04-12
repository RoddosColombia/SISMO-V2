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
          <img src="/logo-roddos-dark.png" alt="RODDOS" className="h-10 mb-12" />
          <h1 className="font-display text-3xl font-bold leading-tight mb-16 text-white/80">
            Precision.<br />
            Administrative.<br />
            Excellence.
          </h1>

          {/* SISMO Logo — SISM + radar O */}
          <svg viewBox="0 0 480 120" className="w-full max-w-lg mb-4" aria-label="SISMO">
            {/* SISM as continuous word */}
            <text x="0" y="98" fontFamily="'Public Sans', sans-serif" fontWeight="900" fontSize="115" fill="white" letterSpacing="-2">SISM</text>
            {/* O — radar circle matching letter height */}
            <g transform="translate(380, 52)">
              {/* Outer cyan arcs */}
              <path d="M 42 -10 A 44 44 0 0 1 10 42" stroke="#00b4d8" strokeWidth="7" fill="none" strokeLinecap="round" />
              <path d="M -42 10 A 44 44 0 0 1 -10 -42" stroke="#00b4d8" strokeWidth="7" fill="none" strokeLinecap="round" />
              {/* Mid green arcs */}
              <path d="M 30 -7 A 32 32 0 0 1 7 30" stroke="#006e2a" strokeWidth="7" fill="none" strokeLinecap="round" />
              <path d="M -30 7 A 32 32 0 0 1 -7 -30" stroke="#006e2a" strokeWidth="7" fill="none" strokeLinecap="round" />
              {/* Inner cyan arcs */}
              <path d="M 19 -4 A 20 20 0 0 1 4 19" stroke="#00b4d8" strokeWidth="6" fill="none" strokeLinecap="round" />
              <path d="M -19 4 A 20 20 0 0 1 -4 -19" stroke="#00b4d8" strokeWidth="6" fill="none" strokeLinecap="round" />
              {/* Center */}
              <circle cx="0" cy="0" r="6" fill="#00b4d8" />
              <circle cx="0" cy="0" r="10" stroke="#00b4d8" strokeWidth="2.5" fill="none" />
            </g>
          </svg>
          <p className="text-white/40 text-sm tracking-widest uppercase">
            Sistema Integral de Monitoreo Operativo
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
