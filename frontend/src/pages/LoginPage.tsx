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
    <div className="min-h-screen flex items-center justify-center bg-neutral-50">
      <form onSubmit={handleSubmit} className="w-full max-w-sm p-8 bg-white border border-neutral-200 rounded-lg">
        <h1 className="text-xl font-semibold mb-6 text-center text-neutral-900">SISMO V2</h1>

        {error && (
          <div className="mb-4 p-3 text-sm bg-red-50 text-red-700 border border-red-200 rounded">
            {error}
          </div>
        )}

        <label className="block mb-1 text-sm text-neutral-600">Correo</label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          className="w-full mb-4 px-3 py-2 border border-neutral-300 rounded text-sm focus:outline-none focus:border-neutral-500"
          placeholder="usuario@roddos.com"
        />

        <label className="block mb-1 text-sm text-neutral-600">Contrasena</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          className="w-full mb-6 px-3 py-2 border border-neutral-300 rounded text-sm focus:outline-none focus:border-neutral-500"
        />

        <button
          type="submit"
          disabled={loading}
          className="w-full py-2 bg-neutral-900 text-white text-sm rounded hover:bg-neutral-800 disabled:opacity-50"
        >
          {loading ? 'Ingresando...' : 'Ingresar'}
        </button>
      </form>
    </div>
  )
}
