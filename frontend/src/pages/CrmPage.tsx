import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiGet } from '@/lib/api'

// ═══════════════════════════════════════════
// Types
// ═══════════════════════════════════════════

interface Cliente {
  cedula: string
  nombre: string
  telefono?: string
  email?: string
  estado: string
  loanbooks?: number | string[] | string
  score_pago?: string
  score?: string
  created_at?: string
  updated_at?: string
}

interface Stats {
  total: number
  activos: number
  saldados: number
}

// ═══════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════

function estadoBadge(estado: string) {
  const map: Record<string, string> = {
    activo: 'bg-emerald-500/10 text-emerald-700',
    saldado: 'bg-blue-500/10 text-blue-700',
    inactivo: 'bg-neutral-400/10 text-neutral-500',
    mora: 'bg-red-500/10 text-red-700',
    prospecto: 'bg-amber-500/10 text-amber-700',
  }
  return map[estado] || 'bg-neutral-400/10 text-neutral-500'
}

function scoreBadge(bucket: string | undefined) {
  if (!bucket) return null
  const map: Record<string, string> = {
    'A+': 'bg-emerald-700 text-white',
    'A': 'bg-emerald-500 text-white',
    'B': 'bg-amber-400 text-neutral-900',
    'C': 'bg-orange-500 text-white',
    'D': 'bg-red-500 text-white',
    'E': 'bg-red-700 text-white',
  }
  return map[bucket] || 'bg-neutral-400 text-white'
}

// ═══════════════════════════════════════════
// Main Page
// ═══════════════════════════════════════════

export default function CrmPage() {
  const navigate = useNavigate()
  const [clientes, setClientes] = useState<Cliente[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  const loadData = useCallback(async () => {
    try {
      const [clientesRes, statsRes] = await Promise.all([
        apiGet<{ clientes: Cliente[] }>('/crm/clientes'),
        apiGet<Stats>('/crm/stats'),
      ])
      setClientes(clientesRes.clientes)
      setStats(statsRes)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    setLoading(true)
    loadData().finally(() => setLoading(false))
  }, [loadData])

  const filtered = search
    ? clientes.filter(c =>
        c.nombre.toLowerCase().includes(search.toLowerCase()) ||
        c.cedula.includes(search)
      )
    : clientes

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* Header */}
      <div className="px-6 pt-6 pb-4 flex items-center justify-between">
        <div>
          <h1 className="font-display text-lg font-bold text-on-surface">Clientes</h1>
          <p className="text-sm text-on-surface-variant mt-0.5">Directorio de clientes CRM</p>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 pb-6">
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <>
            {/* Summary cards */}
            <div className="grid grid-cols-3 gap-4 mb-5">
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                <div className="text-xs text-on-surface-variant uppercase tracking-wider">Total clientes</div>
                <div className="font-display text-2xl font-bold text-on-surface">{stats?.total ?? 0}</div>
              </div>
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                <div className="text-xs text-on-surface-variant uppercase tracking-wider">Activos</div>
                <div className="font-display text-2xl font-bold text-emerald-600">{stats?.activos ?? 0}</div>
              </div>
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                <div className="text-xs text-on-surface-variant uppercase tracking-wider">Saldados</div>
                <div className="font-display text-2xl font-bold text-blue-600">{stats?.saldados ?? 0}</div>
              </div>
            </div>

            {/* Search */}
            <div className="mb-4">
              <input
                className="w-full max-w-sm rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface placeholder:text-on-surface-variant/50 outline-none focus:ring-2 focus:ring-primary/30"
                placeholder="Buscar por nombre o cedula..."
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>

            {/* Table or empty state */}
            {filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant">
                <svg className="w-12 h-12 mb-3 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
                </svg>
                <p className="text-sm font-medium">No hay clientes registrados</p>
                <p className="text-xs mt-1">
                  {search
                    ? `Sin resultados para "${search}"`
                    : 'Los clientes aparecerán aquí cuando se registren desde el chat o loanbook'}
                </p>
              </div>
            ) : (
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-surface-container-low">
                      <th className="text-left px-4 py-2.5 text-xs text-on-surface-variant font-medium">Nombre</th>
                      <th className="text-left px-4 py-2.5 text-xs text-on-surface-variant font-medium">Cédula</th>
                      <th className="text-left px-4 py-2.5 text-xs text-on-surface-variant font-medium">Teléfono</th>
                      <th className="text-center px-4 py-2.5 text-xs text-on-surface-variant font-medium">Estado</th>
                      <th className="text-center px-4 py-2.5 text-xs text-on-surface-variant font-medium">Score</th>
                      <th className="text-right px-4 py-2.5 text-xs text-on-surface-variant font-medium">Créditos</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map(c => {
                      const score = c.score_pago || c.score
                      const scoreCls = scoreBadge(score)
                      return (
                        <tr key={c.cedula}
                          onClick={() => navigate(`/clientes/${c.cedula}`)}
                          className="border-t border-surface-container-low hover:bg-surface-container-low/40 transition-colors cursor-pointer">
                          <td className="px-4 py-2.5 font-medium text-on-surface">{c.nombre}</td>
                          <td className="px-4 py-2.5 font-mono text-xs text-on-surface-variant">{c.cedula}</td>
                          <td className="px-4 py-2.5 text-on-surface-variant">{c.telefono || '—'}</td>
                          <td className="px-4 py-2.5 text-center">
                            <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${estadoBadge(c.estado)}`}>
                              {c.estado}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 text-center">
                            {score ? (
                              <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${scoreCls}`}>
                                {score}
                              </span>
                            ) : (
                              <span className="text-[10px] text-on-surface-variant/60">—</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-right text-on-surface">{
                            Array.isArray(c.loanbooks)
                              ? c.loanbooks.filter((x: string) => /^LB-\d{4}-\d{4}$/.test(x)).length
                              : (typeof c.loanbooks === 'number' ? c.loanbooks : 0)
                          }</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
