import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { apiGet } from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface MesDesglose {
  mes: string
  label: string
  total: number
  causados: number
  pendientes: number
  pct_causado: number
}

interface RondaDesglose {
  ronda: string
  label: string
  causados: number
  detalle?: Record<string, number>
  nota?: string
}

interface CarteraLegacy {
  creditos_activos: number
  recaudo_periodo: number
  saldo_vigente: number
}

interface Bloqueantes {
  manual_pendiente: number
  errores_cuenta: number
  sin_categoria: number
}

interface CapacidadCierre {
  movimientos_por_semana: number
  semanas_estimadas_cierre: number | null
  tendencia: 'mejorando' | 'estable' | 'sin_datos'
}

interface DetalleResponse {
  success: boolean
  periodo_id: string
  label: string
  rango: string
  fecha_inicio: string
  fecha_fin: string
  estado: 'cerrado' | 'en_progreso' | 'abierto'
  total_movimientos: number
  causados: number
  pendientes: number
  errores: number
  manual_pendiente: number
  pct_causado: number
  bloqueantes: Bloqueantes
  capacidad_cierre: CapacidadCierre
  desglose_por_mes: MesDesglose[]
  desglose_por_ronda: RondaDesglose[]
  cartera_legacy?: CarteraLegacy
  proximos_pasos: string[]
  nota_build4?: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const COP = (n: number) =>
  n.toLocaleString('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 })

const Pct = (n: number) => `${n.toFixed(1)}%`

function estadoBadge(estado: DetalleResponse['estado']) {
  if (estado === 'cerrado') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
        CERRADO
      </span>
    )
  }
  if (estado === 'en_progreso') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-100 text-amber-700">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500 inline-block" />
        EN PROGRESO
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-surface-container text-on-surface-variant">
      <span className="w-1.5 h-1.5 rounded-full bg-on-surface-variant/40 inline-block" />
      ABIERTO
    </span>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs font-semibold uppercase tracking-wider text-on-surface-variant mt-8 mb-3">
      {children}
    </h2>
  )
}

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string | number
  sub?: string
  accent?: 'primary' | 'warn' | 'error' | 'emerald'
}) {
  const cls =
    accent === 'primary' ? 'text-primary'
    : accent === 'warn'  ? 'text-amber-600'
    : accent === 'error' ? 'text-error'
    : accent === 'emerald' ? 'text-emerald-600'
    : 'text-on-surface'

  return (
    <div className="rounded-xl bg-surface-container-lowest p-4 flex flex-col gap-1 shadow-ambient">
      <span className="text-xs text-on-surface-variant uppercase tracking-wide">{label}</span>
      <span className={`text-2xl font-bold font-display ${cls}`}>{value}</span>
      {sub && <span className="text-xs text-on-surface-variant">{sub}</span>}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CierreDetallePage() {
  const { periodo_id } = useParams<{ periodo_id: string }>()
  const navigate = useNavigate()
  const [data, setData] = useState<DetalleResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!periodo_id) return
    setLoading(true)
    apiGet<DetalleResponse>(`/cierres/${periodo_id}`)
      .then(r => {
        if (r.success) setData(r)
        else setError('No se pudo cargar el detalle.')
      })
      .catch(() => setError('Error de conexión al cargar el período.'))
      .finally(() => setLoading(false))
  }, [periodo_id])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-on-surface-variant text-sm">
        Cargando período...
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex-1 flex items-center justify-center text-error text-sm">
        {error || 'Error desconocido.'}
      </div>
    )
  }

  const totalBloqueantes =
    data.bloqueantes.manual_pendiente +
    data.bloqueantes.errores_cuenta +
    data.bloqueantes.sin_categoria

  return (
    <div className="flex-1 overflow-y-auto bg-surface">
      <div className="max-w-4xl mx-auto px-6 py-8">

        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-xs text-on-surface-variant mb-6">
          <button
            onClick={() => navigate('/cierres')}
            className="hover:text-primary transition-colors"
          >
            Cierres Contables
          </button>
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
          <span className="text-on-surface font-medium">{data.label}</span>
        </div>

        {/* ── Sección 1: Header ── */}
        <div className="flex items-start justify-between gap-4 mb-2">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold font-display text-on-surface">{data.label}</h1>
              {estadoBadge(data.estado)}
            </div>
            <p className="text-sm text-on-surface-variant mt-1">{data.rango}</p>
            <p className="text-xs text-on-surface-variant mt-0.5">
              {data.fecha_inicio} → {data.fecha_fin}
            </p>
          </div>
        </div>

        {/* ── Sección 2: 4 KPI cards ── */}
        <SectionTitle>Resumen</SectionTitle>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard label="Total movimientos" value={data.total_movimientos} />
          <StatCard
            label="% causado"
            value={Pct(data.pct_causado)}
            sub={`${data.causados} de ${data.total_movimientos}`}
            accent={data.pct_causado >= 95 ? 'emerald' : 'primary'}
          />
          <StatCard
            label="Bloqueantes"
            value={totalBloqueantes}
            sub={
              totalBloqueantes === 0
                ? 'Sin bloqueantes'
                : `${data.bloqueantes.manual_pendiente} manual · ${data.bloqueantes.errores_cuenta} error`
            }
            accent={totalBloqueantes > 0 ? 'warn' : undefined}
          />
          <StatCard
            label="Semanas est. cierre"
            value={
              data.capacidad_cierre.semanas_estimadas_cierre != null
                ? `${data.capacidad_cierre.semanas_estimadas_cierre.toFixed(1)} sem`
                : '—'
            }
            sub={
              data.capacidad_cierre.tendencia === 'sin_datos'
                ? 'Sin datos de velocidad'
                : data.capacidad_cierre.tendencia
            }
          />
        </div>

        {/* ── Sección 3: Progreso por mes ── */}
        {data.desglose_por_mes.length > 0 && (
          <>
            <SectionTitle>Avance por mes</SectionTitle>
            <div className="rounded-xl bg-surface-container-lowest p-5 shadow-ambient space-y-4">
              {data.desglose_por_mes.map(mes => (
                <div key={mes.mes}>
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-medium text-on-surface w-20 shrink-0">{mes.label}</span>
                    <div className="flex-1 h-2 rounded-full bg-surface-container overflow-hidden">
                      <div
                        className={`h-2 rounded-full ${
                          mes.pct_causado >= 95 ? 'bg-emerald-500' : 'bg-primary'
                        }`}
                        style={{ width: `${Math.min(mes.pct_causado, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs font-semibold text-primary w-12 text-right shrink-0">
                      {Pct(mes.pct_causado)}
                    </span>
                  </div>
                  <div className="flex gap-4 text-xs text-on-surface-variant mt-1 ml-[92px]">
                    <span>{mes.causados} causados</span>
                    {mes.pendientes > 0 && <span>{mes.pendientes} pendientes</span>}
                    <span className="text-on-surface-variant/60">{mes.total} total</span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {/* ── Sección 4: Rondas ── */}
        {data.desglose_por_ronda.length > 0 && (
          <>
            <SectionTitle>Desglose por ronda</SectionTitle>
            <div className="rounded-xl bg-surface-container-lowest overflow-hidden shadow-ambient">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-container">
                    <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide text-on-surface-variant">
                      Ronda
                    </th>
                    <th className="text-right px-4 py-3 text-xs font-semibold uppercase tracking-wide text-on-surface-variant">
                      Causados
                    </th>
                    <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide text-on-surface-variant hidden sm:table-cell">
                      Detalle
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-container">
                  {data.desglose_por_ronda.map(r => (
                    <tr key={r.ronda}>
                      <td className="px-4 py-3">
                        <p className="text-sm font-medium text-on-surface">{r.label}</p>
                        {r.nota && (
                          <p className="text-xs text-on-surface-variant mt-0.5">{r.nota}</p>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className={`text-base font-bold font-display ${r.causados > 0 ? 'text-primary' : 'text-on-surface-variant'}`}>
                          {r.causados}
                        </span>
                      </td>
                      <td className="px-4 py-3 hidden sm:table-cell">
                        {r.detalle && (
                          <div className="flex flex-wrap gap-x-3 gap-y-1">
                            {Object.entries(r.detalle).map(([k, v]) => (
                              <span key={k} className="text-xs text-on-surface-variant">
                                {k.replace(/_/g, ' ')}: <span className="font-medium text-on-surface">{v}</span>
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {/* ── Sección 5: Bloqueantes ── */}
        {data.proximos_pasos.length > 0 && (
          <>
            <SectionTitle>Bloqueantes y próximos pasos</SectionTitle>
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
              <div className="flex gap-2 mb-3">
                <svg className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                </svg>
                <p className="text-xs font-semibold text-amber-800">
                  {totalBloqueantes} bloqueante{totalBloqueantes !== 1 ? 's' : ''} impide{totalBloqueantes !== 1 ? 'n' : ''} el cierre
                </p>
              </div>
              <ul className="space-y-2">
                {data.proximos_pasos.map((paso, i) => {
                  const esError   = paso.includes('error de cuenta')
                  const esLizbeth = paso.includes('Lizbeth')
                  return (
                    <li key={i} className="flex items-start gap-2 text-sm text-amber-900">
                      <span className="mt-1 w-1.5 h-1.5 rounded-full bg-amber-500 shrink-0" />
                      <span>
                        {paso}
                        {esError && (
                          <Link
                            to="/backlog?estado=error"
                            className="ml-2 text-xs text-primary underline hover:no-underline"
                          >
                            Ver en backlog
                          </Link>
                        )}
                        {esLizbeth && (
                          <Link
                            to="/backlog?estado=manual_pendiente"
                            className="ml-2 text-xs text-primary underline hover:no-underline"
                          >
                            Ver en backlog
                          </Link>
                        )}
                      </span>
                    </li>
                  )
                })}
              </ul>
            </div>
          </>
        )}

        {/* ── Sección 6: Cartera legacy ── */}
        {data.cartera_legacy && (
          <>
            <SectionTitle>Cartera legacy</SectionTitle>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <StatCard
                label="Créditos activos"
                value={data.cartera_legacy.creditos_activos}
              />
              <StatCard
                label="Recaudo del período"
                value={COP(data.cartera_legacy.recaudo_periodo)}
                accent="primary"
              />
              <StatCard
                label="Saldo vigente"
                value={COP(data.cartera_legacy.saldo_vigente)}
              />
            </div>
          </>
        )}

        {/* ── Sección 7: Nota BUILD 4 (solo Q1) ── */}
        {data.nota_build4 && (
          <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 flex gap-3">
            <svg className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
            </svg>
            <p className="text-sm text-amber-900">{data.nota_build4}</p>
          </div>
        )}

        <p className="text-xs text-on-surface-variant mt-8 text-center">
          SISMO V2 · Cierres Contables
        </p>
      </div>
    </div>
  )
}
