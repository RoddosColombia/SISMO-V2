import { useState, useEffect, useCallback } from 'react'
import { apiGet } from '@/lib/api'
import LoanDetailPage from '@/pages/LoanDetailPage'

// ═══════════════════════════════════════════
// Types
// ═══════════════════════════════════════════

interface ProximaCuota {
  fecha: string
  monto: number
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
// Detail view is now /loanbook/:id — see LoanDetailPage.tsx
// DEPRECATED: Inline modal removed. All navigation uses loanbook_id (works
// for VIN-less products like comparendo/licencia).
// Dead function kept below with no-op body to preserve line ordering but
// prefixed with _ to signal unused. Will be removed in a cleanup pass.
// ═══════════════════════════════════════════

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function _DetalleModal_DEPRECATED(_props: { vin: string; onClose: () => void }) {
  return null
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function _DetalleModal_DEPRECATED_OLD({ vin, onClose }: { vin: string; onClose: () => void }) {
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
            <div className="bg-primary/5 rounded-lg px-4 py-3 flex items-center justify-between">
              <div>
                <div className="text-[10px] text-primary uppercase tracking-wider font-medium">Próxima cuota</div>
                <div className="text-sm text-on-surface font-medium">{formatDate(lb.proxima_cuota.fecha)}</div>
              </div>
              <div className="font-display text-lg font-bold text-primary">{formatCOP(lb.proxima_cuota.monto)}</div>
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
  const [loanbooks, setLoanbooks] = useState<Loanbook[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [filtroEstado, setFiltroEstado] = useState('')
  const [search, setSearch] = useState('')
  const [openLoanId, setOpenLoanId] = useState<string | null>(null)

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

  useEffect(() => {
    setLoading(true)
    loadData().finally(() => setLoading(false))
  }, [loadData])

  const searchNormalized = search.trim().toLowerCase()
  const filtered = loanbooks.filter(lb => {
    if (filtroEstado && lb.estado !== filtroEstado) return false
    if (!searchNormalized) return true
    const haystack = [
      lb.cliente?.nombre || '',
      lb.cliente?.cedula || '',
      lb.loanbook_id || '',
    ].join(' ').toLowerCase()
    return haystack.includes(searchNormalized)
  })

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* Header */}
      <div className="px-6 pt-6 pb-4">
        <h1 className="font-display text-lg font-bold text-on-surface">Créditos</h1>
        <p className="text-sm text-on-surface-variant mt-0.5">Gestión de cartera y loanbooks activos</p>
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
            <div className="grid grid-cols-4 gap-4 mb-5">
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                <div className="text-xs text-on-surface-variant uppercase tracking-wider">Créditos activos</div>
                <div className="font-display text-2xl font-bold text-on-surface">{stats?.activos ?? 0}</div>
                <div className="text-[10px] text-on-surface-variant">{stats?.total ?? 0} total</div>
              </div>
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                <div className="text-xs text-on-surface-variant uppercase tracking-wider">Cartera total</div>
                <div className="font-display text-2xl font-bold text-on-surface">{formatCOP(stats?.cartera_total ?? 0)}</div>
              </div>
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                <div className="text-xs text-on-surface-variant uppercase tracking-wider">Recaudo semanal</div>
                <div className="font-display text-2xl font-bold text-emerald-600">{formatCOP(stats?.recaudo_semanal ?? 0)}</div>
                <div className="text-[10px] text-on-surface-variant">Proyectado</div>
              </div>
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                <div className="text-xs text-on-surface-variant uppercase tracking-wider">En mora</div>
                <div className={`font-display text-2xl font-bold ${(stats?.en_mora ?? 0) > 0 ? 'text-red-600' : 'text-emerald-600'}`}>
                  {stats?.en_mora ?? 0}
                </div>
                <div className="text-[10px] text-on-surface-variant">DPD {'>'} 0</div>
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
                            <div className="text-[10px] text-primary mt-1">
                              Próx: {formatDate(lb.proxima_cuota.fecha)}
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

      {/* Drawer lateral con detalle del credito */}
      {openLoanId && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm animate-in fade-in duration-150"
            onClick={() => setOpenLoanId(null)}
          />
          {/* Slide-in panel */}
          <div
            className="fixed top-0 right-0 z-50 h-screen w-full sm:w-[80%] md:w-[75%] lg:w-[70%] xl:w-[65%] bg-surface shadow-2xl overflow-hidden animate-in slide-in-from-right duration-200"
            role="dialog"
            aria-modal="true"
          >
            <LoanDetailPage idProp={openLoanId} onClose={() => setOpenLoanId(null)} />
          </div>
        </>
      )}
    </div>
  )
}
