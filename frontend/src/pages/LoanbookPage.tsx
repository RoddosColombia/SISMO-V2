import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiGet, apiPost } from '@/lib/api'
import LoanOverlayModal from '@/components/LoanOverlayModal'

// ═══════════════════════════════════════════
// Types
// ═══════════════════════════════════════════

interface ProximaCuota {
  fecha: string
  monto: number
  numero?: number
  monto_capital?: number
  monto_interes?: number
  es_cuota_inicial?: boolean
  vencida?: boolean
  dias_diff?: number
}

interface Cuota {
  numero: number
  monto: number
  estado: string
  fecha: string | null
  fecha_pago: string | null
  mora_acumulada: number
  timeline_status?: string
}

interface Loanbook {
  loanbook_id: string
  tipo_producto?: string
  vin: string | null
  cliente: { nombre: string; cedula: string; telefono?: string }
  plan_codigo: string
  modelo: string
  modalidad: string
  estado: string
  cuota_monto: number
  num_cuotas: number
  saldo_capital: number
  saldo_pendiente?: number
  total_pagado: number
  total_mora_pagada: number
  total_anzi_pagado: number
  anzi_pct: number
  fecha_entrega: string
  fecha_primer_pago: string | null
  fecha_primera_cuota?: string
  fecha_ultima_cuota?: string
  cuotas_pagadas: number
  cuotas_total: number
  dpd: number
  proxima_cuota: ProximaCuota | null
  cuotas?: Cuota[]
  score_bucket?: string
}

interface Stats {
  total: number
  activos: number
  saldados?: number
  pendiente_entrega?: number
  cartera_total: number
  recaudo_semanal: number
  en_mora: number
}

// ─── Auditoría types ──────────────────────────────────────────────────────────

interface AuditCasoValorTotal {
  loanbook_id: string
  cliente: string
  plan_codigo: string
  modalidad: string
  muestra: number
  deberia_ser: number
  formula: string
  diferencia: number
}

interface AuditCasoTotalCuotas {
  loanbook_id: string
  cliente: string
  plan_codigo: string
  modalidad: string
  total_cuotas_muestra: number
  total_cuotas_correcto: number
}

interface AuditCasoCuotaImposible {
  loanbook_id: string
  cliente: string
  cuotas: Array<{ numero: number; fecha: string; fecha_pago: string | null; tiene_referencia: boolean; tiene_metodo: boolean }>
}

interface AuditoriaResult {
  fecha_auditoria: string
  total_loanbooks: number
  resumen: {
    valor_total_incorrecto: number
    total_cuotas_incorrecto_segun_plan: number
    cuotas_pagadas_con_fecha_imposible: number
  }
  casos: {
    valor_total_incorrecto: AuditCasoValorTotal[]
    total_cuotas_incorrecto_segun_plan: AuditCasoTotalCuotas[]
    cuotas_pagadas_fecha_imposible: AuditCasoCuotaImposible[]
  }
}

// ═══════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════

function formatCOP(n: number) {
  return new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(n)
}

function shortVIN(vin: string) {
  return vin ? vin.slice(-6).toUpperCase() : '—'
}

function shortID(id: string) {
  return id ? `LB-${id.slice(0, 8).toUpperCase()}` : '—'
}

function estadoBadge(estado: string) {
  const map: Record<string, string> = {
    pendiente_entrega: 'bg-neutral-400/10 text-neutral-500',
    activo: 'bg-emerald-500/10 text-emerald-700',
    al_dia: 'bg-emerald-500/10 text-emerald-700',
    en_riesgo: 'bg-amber-500/10 text-amber-700',
    mora: 'bg-orange-500/10 text-orange-700',
    mora_grave: 'bg-red-500/10 text-red-700',
    reestructurado: 'bg-purple-500/10 text-purple-700',
    saldado: 'bg-blue-500/10 text-blue-700',
    castigado: 'bg-neutral-500/10 text-neutral-600',
  }
  return map[estado] || 'bg-neutral-400/10 text-neutral-500'
}

function estadoLabel(estado: string) {
  const map: Record<string, string> = {
    pendiente_entrega: 'Pend. entrega',
    activo: 'Activo',
    al_dia: 'Al día',
    en_riesgo: 'En riesgo',
    mora: 'Mora',
    mora_grave: 'Mora grave',
    reestructurado: 'Reestructurado',
    saldado: 'Saldado',
    castigado: 'Castigado',
  }
  return map[estado] || estado
}

function modalidadLabel(m: string) {
  const map: Record<string, string> = { semanal: 'Semanal', quincenal: 'Quincenal', mensual: 'Mensual' }
  return map[m] || m
}

function formatDate(d: string | null) {
  if (!d) return '—'
  try {
    return new Date(d + 'T12:00:00').toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric' })
  } catch {
    return d
  }
}

const MORA_TASA = 2000 // COP/dia

function tipoProductoBadge(tipo: string | undefined) {
  const t = (tipo || 'moto').toLowerCase()
  const map: Record<string, string> = {
    moto: 'bg-neutral-200 text-neutral-700',
    comparendo: 'bg-blue-500/15 text-blue-700',
    licencia: 'bg-purple-500/15 text-purple-700',
  }
  return map[t] || 'bg-neutral-200 text-neutral-700'
}

function scoreClass(bucket: string | undefined) {
  if (!bucket) return ''
  const map: Record<string, string> = {
    'A+': 'bg-emerald-700 text-white',
    'A': 'bg-emerald-500 text-white',
    'B': 'bg-amber-400 text-neutral-900',
    'C': 'bg-orange-500 text-white',
    'D': 'bg-red-500 text-white',
    'E': 'bg-red-700 text-white',
  }
  return map[bucket] || ''
}

function cleanPhone(p: string | undefined | null) {
  if (!p) return ''
  return p.replace(/[^\d]/g, '')
}

function moraAcumulada(cuotas: Cuota[] | undefined): number {
  if (!cuotas) return 0
  const today = new Date()
  today.setHours(12, 0, 0, 0)
  let total = 0
  for (const c of cuotas) {
    if (c.estado === 'pagada' || !c.fecha) continue
    const fc = new Date(c.fecha + 'T12:00:00')
    const dias = Math.floor((today.getTime() - fc.getTime()) / (1000 * 60 * 60 * 24))
    if (dias > 0) total += dias * MORA_TASA
  }
  return total
}

// ═══════════════════════════════════════════
// Detail view: LoanOverlayModal (see components/LoanOverlayModal.tsx)
// Route /loanbook/:id also works as standalone page (LoanDetailPage).
// ═══════════════════════════════════════════

// Dead code below was removed in cleanup pass.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function _NEVER_CALLED_removed_in_cleanup({ vin, onClose }: { vin: string; onClose: () => void }) {
  // Stub kept only to preserve file history; actual overlay rendering
  // lives in LoanOverlayModal.tsx. No-op body below.
  void vin; void onClose
  return null
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function _LEGACY_DetalleModal_removed({ vin, onClose }: { vin: string; onClose: () => void }) {
  const [lb, setLb] = useState<Loanbook | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    apiGet<Loanbook>(`/loanbook/${vin}`)
      .then(setLb)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [vin])

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 bg-black/30 backdrop-blur-sm flex items-center justify-center" onClick={onClose}>
        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (!lb) {
    return (
      <div className="fixed inset-0 z-50 bg-black/30 backdrop-blur-sm flex items-center justify-center" onClick={onClose}>
        <div className="bg-surface-container-lowest rounded-xl shadow-ambient-3 p-6 max-w-md" onClick={e => e.stopPropagation()}>
          <p className="text-sm text-on-surface-variant">No se encontró el loanbook.</p>
          <button onClick={onClose} className="mt-4 px-4 py-2 rounded-md bg-surface-container-low text-sm text-on-surface-variant">Cerrar</button>
        </div>
      </div>
    )
  }

  const cuotas = lb.cuotas || []
  const pagadas = cuotas.filter(c => c.estado === 'pagada').length
  const totalFinanciado = lb.num_cuotas * lb.cuota_monto

  return (
    <div className="fixed inset-0 z-50 bg-black/30 backdrop-blur-sm flex items-center justify-center overflow-y-auto py-8" onClick={onClose}>
      <div className="bg-surface-container-lowest rounded-xl shadow-ambient-3 w-full max-w-2xl mx-4" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="px-6 py-5 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <h2 className="font-display font-bold text-on-surface">{lb.cliente.nombre}</h2>
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${estadoBadge(lb.estado)}`}>
                {estadoLabel(lb.estado)}
              </span>
            </div>
            <p className="text-xs text-on-surface-variant">CC {lb.cliente.cedula} · {lb.modelo} · VIN ...{shortVIN(lb.vin)}</p>
          </div>
          <button onClick={onClose} className="text-on-surface-variant hover:text-on-surface p-1">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Info grid */}
        <div className="px-6 pb-4 grid grid-cols-3 gap-4">
          <div>
            <div className="text-[10px] text-on-surface-variant uppercase tracking-wider">Plan</div>
            <div className="text-sm font-medium text-on-surface">{lb.plan_codigo} · {modalidadLabel(lb.modalidad)}</div>
          </div>
          <div>
            <div className="text-[10px] text-on-surface-variant uppercase tracking-wider">Cuota</div>
            <div className="text-sm font-medium text-on-surface">{formatCOP(lb.cuota_monto)}</div>
          </div>
          <div>
            <div className="text-[10px] text-on-surface-variant uppercase tracking-wider">DPD</div>
            <div className={`text-sm font-medium ${lb.dpd > 0 ? 'text-red-600' : 'text-emerald-600'}`}>{lb.dpd} días</div>
          </div>
        </div>

        {/* Cuota timeline bar */}
        {cuotas.length > 0 && (
          <div className="px-6 pb-4">
            <div className="text-[10px] text-on-surface-variant uppercase tracking-wider mb-2">Timeline de cuotas</div>
            <div className="flex gap-px rounded-lg overflow-hidden h-6">
              {cuotas.map(c => {
                const status = c.timeline_status || c.estado
                const colorMap: Record<string, string> = {
                  pagada: 'bg-emerald-500',
                  proxima: 'bg-amber-400',
                  vencida: 'bg-red-500',
                  pendiente: 'bg-neutral-200',
                }
                return (
                  <div
                    key={c.numero}
                    className={`flex-1 ${colorMap[status] || 'bg-neutral-200'} relative group cursor-default`}
                    title={`#${c.numero} ${formatDate(c.fecha)} ${formatCOP(c.monto)} — ${status}`}
                  >
                    <div className="hidden group-hover:block absolute bottom-full left-1/2 -translate-x-1/2 mb-1 bg-on-surface text-surface-container-lowest text-[9px] px-2 py-1 rounded whitespace-nowrap z-10">
                      #{c.numero} · {formatDate(c.fecha)} · {formatCOP(c.monto)}
                      {c.fecha_pago && <><br />Pagada: {formatDate(c.fecha_pago)}</>}
                    </div>
                  </div>
                )
              })}
            </div>
            <div className="flex justify-between text-[9px] text-on-surface-variant mt-1">
              <span>{pagadas}/{cuotas.length} pagadas</span>
              <div className="flex gap-3">
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-emerald-500" />Pagada</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-amber-400" />Próxima</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-red-500" />Vencida</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-neutral-200" />Pendiente</span>
              </div>
            </div>
          </div>
        )}

        {/* Financial summary */}
        <div className="px-6 pb-4 grid grid-cols-2 gap-3">
          <div className="bg-surface-container-low rounded-lg px-4 py-3">
            <div className="text-[10px] text-on-surface-variant uppercase tracking-wider">Total financiado</div>
            <div className="font-display text-lg font-bold text-on-surface">{formatCOP(totalFinanciado)}</div>
          </div>
          <div className="bg-surface-container-low rounded-lg px-4 py-3">
            <div className="text-[10px] text-on-surface-variant uppercase tracking-wider">Saldo pendiente</div>
            <div className="font-display text-lg font-bold text-on-surface">{formatCOP(lb.saldo_capital)}</div>
          </div>
          <div className="bg-surface-container-low rounded-lg px-4 py-3">
            <div className="text-[10px] text-on-surface-variant uppercase tracking-wider">Total pagado</div>
            <div className="font-display text-lg font-bold text-emerald-600">{formatCOP(lb.total_pagado)}</div>
          </div>
          <div className="bg-surface-container-low rounded-lg px-4 py-3">
            <div className="text-[10px] text-on-surface-variant uppercase tracking-wider">ANZI acumulado</div>
            <div className="font-display text-lg font-bold text-secondary">{formatCOP(lb.total_anzi_pagado)}</div>
          </div>
        </div>

        {/* Próxima cuota */}
        {lb.proxima_cuota && (
          <div className="px-6 pb-4">
            <div
              className={`rounded-lg px-4 py-3 flex items-center justify-between ${
                lb.proxima_cuota.vencida ? 'bg-red-50' : 'bg-primary/5'
              }`}
            >
              <div>
                <div
                  className={`text-[10px] uppercase tracking-wider font-medium ${
                    lb.proxima_cuota.vencida ? 'text-red-700' : 'text-primary'
                  }`}
                >
                  {lb.proxima_cuota.vencida ? 'Cuota atrasada' : 'Próxima cuota'}
                  {lb.proxima_cuota.es_cuota_inicial && ' (cuota inicial)'}
                </div>
                <div className="text-sm text-on-surface font-medium">
                  {formatDate(lb.proxima_cuota.fecha)}
                  {lb.proxima_cuota.vencida && lb.proxima_cuota.dias_diff !== undefined && (
                    <span className="text-red-600 ml-2">
                      · {Math.abs(lb.proxima_cuota.dias_diff)}d atrás
                    </span>
                  )}
                </div>
              </div>
              <div
                className={`font-display text-lg font-bold ${
                  lb.proxima_cuota.vencida ? 'text-red-700' : 'text-primary'
                }`}
              >
                {formatCOP(lb.proxima_cuota.monto)}
              </div>
            </div>
          </div>
        )}

        {/* Cuotas table */}
        {cuotas.length > 0 && (
          <div className="px-6 pb-5">
            <div className="text-[10px] text-on-surface-variant uppercase tracking-wider mb-2">Detalle de cuotas</div>
            <div className="max-h-48 overflow-y-auto rounded-lg border border-surface-container-low">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-surface-container-low">
                  <tr>
                    <th className="text-left px-3 py-2 text-on-surface-variant font-medium">#</th>
                    <th className="text-left px-3 py-2 text-on-surface-variant font-medium">Fecha</th>
                    <th className="text-right px-3 py-2 text-on-surface-variant font-medium">Monto</th>
                    <th className="text-center px-3 py-2 text-on-surface-variant font-medium">Estado</th>
                    <th className="text-left px-3 py-2 text-on-surface-variant font-medium">Pagada</th>
                    <th className="text-right px-3 py-2 text-on-surface-variant font-medium">Mora</th>
                  </tr>
                </thead>
                <tbody>
                  {cuotas.map(c => (
                    <tr key={c.numero} className="border-t border-surface-container-low hover:bg-surface-container-low/40">
                      <td className="px-3 py-1.5 text-on-surface">{c.numero}</td>
                      <td className="px-3 py-1.5 text-on-surface">{formatDate(c.fecha)}</td>
                      <td className="px-3 py-1.5 text-right text-on-surface">{formatCOP(c.monto)}</td>
                      <td className="px-3 py-1.5 text-center">
                        <span className={`px-1.5 py-0.5 rounded-full text-[9px] font-semibold ${
                          c.estado === 'pagada' ? 'bg-emerald-500/10 text-emerald-700'
                            : (c.timeline_status === 'vencida' ? 'bg-red-500/10 text-red-700' : 'bg-neutral-200/60 text-neutral-500')
                        }`}>
                          {c.estado === 'pagada' ? 'Pagada' : (c.timeline_status === 'vencida' ? 'Vencida' : 'Pendiente')}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-on-surface-variant">{c.fecha_pago ? formatDate(c.fecha_pago) : '—'}</td>
                      <td className="px-3 py-1.5 text-right text-on-surface-variant">
                        {c.mora_acumulada > 0 ? <span className="text-red-600">{formatCOP(c.mora_acumulada)}</span> : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Close */}
        <div className="px-6 pb-5">
          <button onClick={onClose}
            className="w-full rounded-md bg-surface-container-low px-4 py-2 text-sm text-on-surface-variant hover:bg-surface-container-low/80 transition-colors">
            Cerrar
          </button>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════
// Main Page
// ═══════════════════════════════════════════

const ESTADO_FILTERS = ['', 'activo', 'al_dia', 'en_riesgo', 'mora', 'mora_grave', 'saldado', 'pendiente_entrega']
const ESTADO_FILTER_LABELS: Record<string, string> = {
  '': 'Todos',
  activo: 'Activos',
  al_dia: 'Al día',
  en_riesgo: 'En riesgo',
  mora: 'Mora',
  mora_grave: 'Mora grave',
  saldado: 'Saldados',
  pendiente_entrega: 'Pend. entrega',
}

export default function LoanbookPage() {
  const navigate = useNavigate()
  const [loanbooks, setLoanbooks] = useState<Loanbook[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [filtroEstado, setFiltroEstado] = useState('')
  const [search, setSearch] = useState('')
  const [openLoanId, setOpenLoanId] = useState<string | null>(null)
  const [tab, setTab] = useState<'cartera' | 'auditoria'>('cartera')

  // Auditoría state
  const [auditResult, setAuditResult] = useState<AuditoriaResult | null>(null)
  const [auditLoading, setAuditLoading] = useState(false)
  const [auditError, setAuditError] = useState('')

  const loadData = useCallback(async () => {
    try {
      const [lbRes, statsRes] = await Promise.all([
        apiGet<{ count: number; loanbooks: Loanbook[] }>('/loanbook'),
        apiGet<Stats>('/loanbook/stats'),
      ])
      setLoanbooks(lbRes.loanbooks)
      setStats(statsRes)
    } catch { /* ignore */ }
  }, [])

  const runAudit = useCallback(async () => {
    setAuditLoading(true)
    setAuditError('')
    try {
      const data = await apiGet<AuditoriaResult>('/loanbook/auditoria')
      setAuditResult(data)
    } catch (e: unknown) {
      setAuditError(e instanceof Error ? e.message : 'Error en auditoría')
    } finally {
      setAuditLoading(false)
    }
  }, [])

  const repararUno = useCallback(async (loanbookId: string) => {
    if (!window.confirm(`¿Reparar ${loanbookId}? Se corregirán num_cuotas, valor_total y cuotas seed.`)) return
    try {
      await apiPost(`/loanbook/${loanbookId}/reparar?dry_run=false`, {})
      // Re-run audit to reflect changes
      const data = await apiGet<AuditoriaResult>('/loanbook/auditoria')
      setAuditResult(data)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Error al reparar')
    }
  }, [])

  const repararTodos = useCallback(async () => {
    if (!window.confirm('¿Reparar TODOS los loanbooks con inconsistencias? Esta acción aplica cambios en producción.')) return
    try {
      await apiPost('/loanbook/reparar-todos?dry_run=false', {})
      const data = await apiGet<AuditoriaResult>('/loanbook/auditoria')
      setAuditResult(data)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Error al reparar todos')
    }
  }, [])

  const [excelLoading, setExcelLoading] = useState(false)
  const descargarExcel = useCallback(async () => {
    setExcelLoading(true)
    try {
      const token = localStorage.getItem('token')
      const res = await fetch('/api/loanbook/export-loan-tape', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) throw new Error(`Error ${res.status}`)
      const blob = await res.blob()
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `loanbook_roddos_${new Date().toISOString().slice(0, 10)}.xlsx`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Error al descargar Excel')
    } finally {
      setExcelLoading(false)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    loadData().finally(() => setLoading(false))
  }, [loadData])

  const searchNormalized = search.trim().toLowerCase()

  // Filtro estado: 'activo' significa "todos los no-saldados/cancelados/pendiente_entrega"
  // (incluye al_dia, en_riesgo, mora, mora_grave, Early Delinquency, etc.)
  const matchEstado = (lbEstado: string | undefined, filtro: string): boolean => {
    if (!filtro) return true
    const e = (lbEstado || '').toLowerCase()
    if (filtro === 'activo') {
      return !['saldado', 'pagado', 'castigado', 'chargeoff', 'pendiente_entrega', 'pendiente entrega', 'cancelado'].includes(e)
    }
    if (filtro === 'al_dia') {
      return e === 'al_dia' || e === 'al día' || e === 'current' || e === 'activo'
    }
    if (filtro === 'mora') {
      return e === 'mora' || e === 'early delinquency' || e === 'late delinquency'
    }
    if (filtro === 'mora_grave') {
      return e === 'mora_grave' || e === 'severe delinquency' || e === 'pre default' || e === 'default'
    }
    if (filtro === 'en_riesgo') {
      return e === 'en_riesgo' || e === 'grace' || e === 'warning' || e === 'alert'
    }
    return e === filtro.toLowerCase()
  }

  const filtered = loanbooks.filter(lb => {
    if (!matchEstado(lb.estado, filtroEstado)) return false
    if (!searchNormalized) return true
    const haystack = [
      lb.cliente?.nombre || '',
      lb.cliente?.cedula || '',
      lb.loanbook_id || '',
    ].join(' ').toLowerCase()
    return haystack.includes(searchNormalized)
  })

  // Tarjetas DINÁMICAS según filtro activo
  // Tres métricas independientes:
  //   carteraNeto    = lo que aún se debe (saldo_pendiente)
  //   carteraBruto   = total contratado original (valor_total)
  //   recaudado      = cartera_bruta - cartera_neto (lo que ya pagaron)
  const carteraNeto = filtered.reduce((acc, lb: any) => acc + Number(lb.saldo_pendiente || 0), 0)
  const carteraBruto = filtered.reduce((acc, lb: any) => acc + Number(
    lb.valor_total || lb.monto_original || lb.saldo_pendiente || 0
  ), 0)
  const recaudado = Math.max(0, carteraBruto - carteraNeto)
  const dynamicStats = {
    count: filtered.length,
    cartera_total: carteraNeto,        // legacy alias
    cartera_neto: carteraNeto,
    cartera_bruto: carteraBruto,
    recaudado: recaudado,
    en_mora: filtered.filter(lb => matchEstado(lb.estado, 'mora') || matchEstado(lb.estado, 'mora_grave')).length,
  }

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* Header */}
      <div className="px-6 pt-6 pb-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-display text-lg font-bold text-on-surface">Créditos</h1>
            <p className="text-sm text-on-surface-variant mt-0.5">Gestión de cartera y loanbooks activos</p>
          </div>
          <div className="flex items-center gap-2">
            {/* Descargar Excel */}
            <button
              onClick={descargarExcel}
              disabled={excelLoading}
              title="Descargar portafolio en Excel"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-container-low text-on-surface-variant hover:bg-surface-container hover:text-on-surface transition-colors disabled:opacity-50"
            >
              {excelLoading ? (
                <span className="w-3.5 h-3.5 border border-current border-t-transparent rounded-full animate-spin" />
              ) : (
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
              )}
              Excel
            </button>

            {/* Informe semanal */}
            <button
              onClick={() => navigate('/loanbook/informe')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-container-low text-on-surface-variant hover:bg-surface-container hover:text-on-surface transition-colors"
              title="Ver informe semanal de créditos sin pago"
            >
              📋 Informe
            </button>

            {/* Tab toggle */}
            <div className="flex gap-1 bg-surface-container-low rounded-lg p-1">
              <button
                onClick={() => setTab('cartera')}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                  tab === 'cartera'
                    ? 'bg-surface-container-lowest text-on-surface shadow-ambient-1'
                    : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                Cartera
              </button>
              <button
                onClick={() => setTab('auditoria')}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                  tab === 'auditoria'
                    ? 'bg-surface-container-lowest text-on-surface shadow-ambient-1'
                    : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                Auditoría
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 pb-6">
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : tab === 'auditoria' ? (
          /* ── Auditoría tab ──────────────────────────────────────────────── */
          <div>
            <div className="flex items-center gap-3 mb-4">
              <button
                onClick={runAudit}
                disabled={auditLoading}
                className="px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium disabled:opacity-50 hover:bg-primary/90 transition-colors"
              >
                {auditLoading ? 'Ejecutando...' : 'Ejecutar auditoría'}
              </button>
              {auditResult && auditResult.resumen.valor_total_incorrecto + auditResult.resumen.total_cuotas_incorrecto_segun_plan + auditResult.resumen.cuotas_pagadas_con_fecha_imposible > 0 && (
                <button
                  onClick={repararTodos}
                  className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 transition-colors"
                >
                  Reparar todos
                </button>
              )}
              {auditResult && (
                <span className="text-xs text-on-surface-variant">
                  {new Date(auditResult.fecha_auditoria).toLocaleString('es-CO')} · {auditResult.total_loanbooks} loanbooks analizados
                </span>
              )}
            </div>

            {auditError && (
              <div className="mb-4 px-4 py-3 rounded-lg bg-red-500/10 text-red-700 text-sm">{auditError}</div>
            )}

            {auditResult && (
              <div className="space-y-4">
                {/* Resumen badges */}
                <div className="grid grid-cols-3 gap-3">
                  <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                    <div className="text-[10px] text-on-surface-variant uppercase tracking-wider">Valor total incorrecto</div>
                    <div className={`font-display text-2xl font-bold ${auditResult.resumen.valor_total_incorrecto > 0 ? 'text-red-600' : 'text-emerald-600'}`}>
                      {auditResult.resumen.valor_total_incorrecto}
                    </div>
                  </div>
                  <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                    <div className="text-[10px] text-on-surface-variant uppercase tracking-wider">Cuotas incorrectas</div>
                    <div className={`font-display text-2xl font-bold ${auditResult.resumen.total_cuotas_incorrecto_segun_plan > 0 ? 'text-amber-600' : 'text-emerald-600'}`}>
                      {auditResult.resumen.total_cuotas_incorrecto_segun_plan}
                    </div>
                  </div>
                  <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                    <div className="text-[10px] text-on-surface-variant uppercase tracking-wider">Cuotas seed corruptas</div>
                    <div className={`font-display text-2xl font-bold ${auditResult.resumen.cuotas_pagadas_con_fecha_imposible > 0 ? 'text-orange-600' : 'text-emerald-600'}`}>
                      {auditResult.resumen.cuotas_pagadas_con_fecha_imposible}
                    </div>
                  </div>
                </div>

                {/* Valor total incorrecto */}
                {auditResult.casos.valor_total_incorrecto.length > 0 && (
                  <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg overflow-hidden">
                    <div className="px-4 py-3 border-b border-surface-container-low">
                      <h3 className="text-sm font-semibold text-on-surface">Valor total incorrecto</h3>
                      <p className="text-xs text-on-surface-variant mt-0.5">El valor_total no coincide con la fórmula del plan</p>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead className="bg-surface-container-low">
                          <tr>
                            <th className="text-left px-3 py-2 text-on-surface-variant font-medium">ID</th>
                            <th className="text-left px-3 py-2 text-on-surface-variant font-medium">Cliente</th>
                            <th className="text-left px-3 py-2 text-on-surface-variant font-medium">Plan</th>
                            <th className="text-right px-3 py-2 text-on-surface-variant font-medium">Muestra</th>
                            <th className="text-right px-3 py-2 text-on-surface-variant font-medium">Correcto</th>
                            <th className="text-right px-3 py-2 text-on-surface-variant font-medium">Diferencia</th>
                          </tr>
                        </thead>
                        <tbody>
                          {auditResult.casos.valor_total_incorrecto.map(c => (
                            <tr key={c.loanbook_id} className="border-t border-surface-container-low hover:bg-surface-container-low/40">
                              <td className="px-3 py-2 font-mono text-on-surface-variant">{c.loanbook_id}</td>
                              <td className="px-3 py-2 text-on-surface">{c.cliente}</td>
                              <td className="px-3 py-2 text-on-surface-variant">{c.plan_codigo} · {c.modalidad}</td>
                              <td className="px-3 py-2 text-right text-red-600">{formatCOP(c.muestra)}</td>
                              <td className="px-3 py-2 text-right text-emerald-600">{formatCOP(c.deberia_ser)}</td>
                              <td className="px-3 py-2 text-right font-medium text-red-600">{formatCOP(c.diferencia)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Total cuotas incorrecto */}
                {auditResult.casos.total_cuotas_incorrecto_segun_plan.length > 0 && (
                  <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg overflow-hidden">
                    <div className="px-4 py-3 border-b border-surface-container-low">
                      <h3 className="text-sm font-semibold text-on-surface">Número de cuotas incorrecto</h3>
                      <p className="text-xs text-on-surface-variant mt-0.5">total_cuotas no coincide con lo que dicta el plan_codigo</p>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead className="bg-surface-container-low">
                          <tr>
                            <th className="text-left px-3 py-2 text-on-surface-variant font-medium">ID</th>
                            <th className="text-left px-3 py-2 text-on-surface-variant font-medium">Cliente</th>
                            <th className="text-left px-3 py-2 text-on-surface-variant font-medium">Plan</th>
                            <th className="text-center px-3 py-2 text-on-surface-variant font-medium">Muestra</th>
                            <th className="text-center px-3 py-2 text-on-surface-variant font-medium">Correcto</th>
                            <th className="px-3 py-2" />
                          </tr>
                        </thead>
                        <tbody>
                          {auditResult.casos.total_cuotas_incorrecto_segun_plan.map(c => (
                            <tr key={c.loanbook_id} className="border-t border-surface-container-low hover:bg-surface-container-low/40">
                              <td className="px-3 py-2 font-mono text-on-surface-variant">{c.loanbook_id}</td>
                              <td className="px-3 py-2 text-on-surface">{c.cliente}</td>
                              <td className="px-3 py-2 text-on-surface-variant">{c.plan_codigo} · {c.modalidad}</td>
                              <td className="px-3 py-2 text-center text-red-600 font-bold">{c.total_cuotas_muestra}</td>
                              <td className="px-3 py-2 text-center text-emerald-600 font-bold">{c.total_cuotas_correcto}</td>
                              <td className="px-3 py-2">
                                <button onClick={() => repararUno(c.loanbook_id)}
                                  className="px-2 py-1 rounded text-[10px] font-medium bg-amber-500/10 text-amber-700 hover:bg-amber-500/20 transition-colors whitespace-nowrap">
                                  Reparar
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Cuotas seed corruptas */}
                {auditResult.casos.cuotas_pagadas_fecha_imposible.length > 0 && (
                  <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg overflow-hidden">
                    <div className="px-4 py-3 border-b border-surface-container-low">
                      <h3 className="text-sm font-semibold text-on-surface">Cuotas futuras marcadas pagadas sin evidencia</h3>
                      <p className="text-xs text-on-surface-variant mt-0.5">Probablemente seed corrupto — fecha en el futuro, sin referencia ni método de pago</p>
                    </div>
                    <div className="space-y-0">
                      {auditResult.casos.cuotas_pagadas_fecha_imposible.map(c => (
                        <div key={c.loanbook_id} className="px-4 py-3 border-t border-surface-container-low first:border-0">
                          <div className="flex items-center justify-between mb-1.5">
                            <div className="flex items-baseline gap-2">
                              <span className="font-mono text-xs text-on-surface-variant">{c.loanbook_id}</span>
                              <span className="text-sm font-medium text-on-surface">{c.cliente}</span>
                            </div>
                            <button onClick={() => repararUno(c.loanbook_id)}
                              className="px-2 py-1 rounded text-[10px] font-medium bg-orange-500/10 text-orange-700 hover:bg-orange-500/20 transition-colors whitespace-nowrap shrink-0">
                              Reparar
                            </button>
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {c.cuotas.map(cu => (
                              <span key={cu.numero}
                                className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-orange-500/10 text-orange-700">
                                #{cu.numero} · {cu.fecha}
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* All clean */}
                {auditResult.resumen.valor_total_incorrecto === 0 &&
                  auditResult.resumen.total_cuotas_incorrecto_segun_plan === 0 &&
                  auditResult.resumen.cuotas_pagadas_con_fecha_imposible === 0 && (
                  <div className="flex flex-col items-center justify-center py-12 text-emerald-600">
                    <svg className="w-10 h-10 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <p className="text-sm font-semibold">Portafolio limpio</p>
                    <p className="text-xs text-emerald-700/70 mt-1">No se detectaron inconsistencias estructurales</p>
                  </div>
                )}
              </div>
            )}

            {!auditResult && !auditLoading && (
              <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant">
                <svg className="w-10 h-10 mb-3 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" />
                </svg>
                <p className="text-sm font-medium">Sin auditoría ejecutada</p>
                <p className="text-xs mt-1">Presiona "Ejecutar auditoría" para analizar el portafolio</p>
              </div>
            )}
          </div>
        ) : (
          <>
            {/* Summary cards — DINÁMICAS según filtro activo */}
            <div className="grid grid-cols-4 gap-4 mb-5">
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                <div className="text-xs text-on-surface-variant uppercase tracking-wider">
                  {filtroEstado ? `${ESTADO_FILTER_LABELS[filtroEstado] || filtroEstado}` : 'Créditos activos'}
                </div>
                <div className="font-display text-2xl font-bold text-on-surface">{dynamicStats.count}</div>
                <div className="text-[10px] text-on-surface-variant">{loanbooks.length} total</div>
              </div>
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                <div className="text-xs text-on-surface-variant uppercase tracking-wider">
                  {filtroEstado ? `Saldo neto ${ESTADO_FILTER_LABELS[filtroEstado] || filtroEstado}` : 'Saldo neto a cobrar'}
                </div>
                <div className="font-display text-2xl font-bold text-on-surface">{formatCOP(dynamicStats.cartera_neto)}</div>
                <div className="text-[10px] text-on-surface-variant">Bruto contratado: {formatCOP(dynamicStats.cartera_bruto)}</div>
              </div>
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                <div className="text-xs text-on-surface-variant uppercase tracking-wider">Recaudado a la fecha</div>
                <div className="font-display text-2xl font-bold text-emerald-600">{formatCOP(dynamicStats.recaudado)}</div>
                <div className="text-[10px] text-on-surface-variant">
                  {dynamicStats.cartera_bruto > 0 ? `${Math.round((dynamicStats.recaudado / dynamicStats.cartera_bruto) * 100)}% del bruto` : '0%'}
                </div>
              </div>
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                <div className="text-xs text-on-surface-variant uppercase tracking-wider">En mora</div>
                <div className={`font-display text-2xl font-bold ${dynamicStats.en_mora > 0 ? 'text-red-600' : 'text-emerald-600'}`}>
                  {dynamicStats.en_mora}
                </div>
                <div className="text-[10px] text-on-surface-variant">DPD {'>'} 0 en filtro</div>
              </div>
            </div>

            {/* Search bar */}
            <div className="mb-3 relative">
              <input
                type="search"
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Buscar por nombre, cédula o código de crédito..."
                className="w-full rounded-lg bg-surface-container-lowest shadow-ambient-1 pl-10 pr-3 py-2 text-sm text-on-surface placeholder:text-on-surface-variant/60 outline-none focus:ring-2 focus:ring-primary/30"
              />
              <svg className="w-4 h-4 text-on-surface-variant absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
                fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 10.5a6.5 6.5 0 11-13 0 6.5 6.5 0 0113 0z" />
              </svg>
              {search && (
                <button onClick={() => setSearch('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-on-surface p-1">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
            </div>

            {/* Filters */}
            <div className="flex gap-2 mb-4 flex-wrap">
              {ESTADO_FILTERS.map(est => (
                <button key={est} onClick={() => setFiltroEstado(est)}
                  className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                    filtroEstado === est
                      ? 'bg-primary/10 text-primary'
                      : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-low/80'
                  }`}>
                  {ESTADO_FILTER_LABELS[est]}
                </button>
              ))}
            </div>

            {/* Loanbook cards */}
            {filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant">
                <svg className="w-12 h-12 mb-3 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
                <p className="text-sm font-medium">Sin créditos</p>
                <p className="text-xs mt-1">Los créditos aparecerán aquí cuando se creen loanbooks</p>
              </div>
            ) : (
              <div className="space-y-2">
                {filtered.map(lb => {
                  const tipo = (lb.tipo_producto || 'moto').toLowerCase()
                  const mora = moraAcumulada(lb.cuotas)
                  const telClean = cleanPhone(lb.cliente?.telefono)
                  const saldoMostrar = lb.saldo_pendiente ?? lb.saldo_capital
                  return (
                    <div key={lb.loanbook_id}
                      onClick={() => setOpenLoanId(lb.loanbook_id)}
                      className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-4 sm:px-5 cursor-pointer transition-shadow hover:shadow-ambient-2">
                      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                        {/* Left: client + modelo + tipo */}
                        <div className="min-w-0 flex-1 w-full">
                          <div className="flex items-center gap-2 mb-1 flex-wrap">
                            <span className="font-display font-bold text-sm text-on-surface truncate">{lb.cliente.nombre}</span>
                            <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold shrink-0 ${estadoBadge(lb.estado)}`}>
                              {estadoLabel(lb.estado)}
                            </span>
                            <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold shrink-0 uppercase tracking-wider ${tipoProductoBadge(tipo)}`}>
                              {tipo}
                            </span>
                            {lb.score_bucket && (
                              <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold shrink-0 ${scoreClass(lb.score_bucket)}`}>
                                {lb.score_bucket}
                              </span>
                            )}
                          </div>
                          <div className="flex flex-wrap items-center gap-2 sm:gap-3 text-[11px] text-on-surface-variant">
                            <span>CC {lb.cliente.cedula}</span>
                            {lb.cliente.telefono && (
                              <>
                                <span className="text-on-surface-variant/40 hidden sm:inline">·</span>
                                <a href={`tel:+${telClean}`}
                                   onClick={e => e.stopPropagation()}
                                   className="text-primary hover:underline font-mono">
                                  {lb.cliente.telefono}
                                </a>
                              </>
                            )}
                            <span className="text-on-surface-variant/40 hidden sm:inline">·</span>
                            <span>{lb.modelo}</span>
                            {lb.vin && (
                              <>
                                <span className="text-on-surface-variant/40 hidden sm:inline">·</span>
                                <span className="font-mono">...{shortVIN(lb.vin)}</span>
                              </>
                            )}
                          </div>
                        </div>

                        {/* Center: plan + progress + DPD */}
                        <div className="flex items-center gap-4 sm:gap-6 shrink-0 w-full sm:w-auto justify-between sm:justify-start">
                          <div className="text-center">
                            <div className="text-[10px] text-on-surface-variant uppercase">Plan</div>
                            <div className="text-xs font-medium text-on-surface">{lb.plan_codigo}</div>
                            <div className="text-[10px] text-on-surface-variant">{modalidadLabel(lb.modalidad)}</div>
                          </div>
                          <div className="text-center">
                            <div className="text-[10px] text-on-surface-variant uppercase">Cuotas</div>
                            <div className="text-xs font-medium text-on-surface">{lb.cuotas_pagadas}/{lb.cuotas_total}</div>
                            <div className="w-16 h-1 bg-surface-container-low rounded-full mt-1 overflow-hidden">
                              <div className="h-full bg-primary rounded-full" style={{ width: `${lb.cuotas_total ? (lb.cuotas_pagadas / lb.cuotas_total) * 100 : 0}%` }} />
                            </div>
                          </div>
                          <div className="text-center">
                            <div className="text-[10px] text-on-surface-variant uppercase">DPD</div>
                            <div className={`text-xs font-bold ${lb.dpd > 15 ? 'text-red-600' : lb.dpd > 0 ? 'text-amber-600' : 'text-emerald-600'}`}>
                              {lb.dpd}
                            </div>
                          </div>
                        </div>

                        {/* Right: amounts */}
                        <div className="text-right shrink-0 w-full sm:w-auto">
                          <div className="text-sm font-display font-bold text-on-surface">{formatCOP(saldoMostrar)}</div>
                          <div className="text-[10px] text-on-surface-variant">Saldo pendiente</div>
                          {mora > 0 && (
                            <div className="text-[10px] text-red-600 font-medium mt-0.5">
                              Mora: {formatCOP(mora)}
                            </div>
                          )}
                          {lb.proxima_cuota && (
                            <div
                              className={`text-[10px] mt-1 font-medium ${
                                lb.proxima_cuota.vencida
                                  ? 'text-red-600'
                                  : 'text-primary'
                              }`}
                              title={
                                lb.proxima_cuota.vencida
                                  ? `Atrasada ${Math.abs(lb.proxima_cuota.dias_diff ?? 0)} días`
                                  : `Faltan ${lb.proxima_cuota.dias_diff ?? 0} días`
                              }
                            >
                              {lb.proxima_cuota.vencida ? 'Atrasada: ' : 'Próx: '}
                              {formatDate(lb.proxima_cuota.fecha)}
                              {lb.proxima_cuota.es_cuota_inicial && ' (cuota inicial)'}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </>
        )}
      </div>

      {/* Overlay modal centrado — premium refined design */}
      {openLoanId && (
        <LoanOverlayModal
          loanId={openLoanId}
          onClose={() => setOpenLoanId(null)}
        />
      )}
    </div>
  )
}
