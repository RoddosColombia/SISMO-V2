import { useEffect, useState } from 'react'
import { apiGet } from '@/lib/api'

interface PlanSepareStats {
  total_retenido: number
  total_esperado?: number
  dinero_pendiente?: number
  matriculas_provision_actual: number
  matriculas_provision_proyectada: number
  por_estado: { activa: number; completada: number; facturada: number; cancelada: number }
  matricula_unit: number
}

interface DashboardStats {
  mes: string
  rango: { desde: string; hasta: string }
  dinero_facturado_mes: number | null
  motos_facturadas_mes: number | null
  cuotas_recibidas_mes: number
  cuotas_pagadas_count: number
}

function formatCOP(n: number | undefined | null): string {
  if (n === undefined || n === null) return '—'
  return new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(n)
}

function formatMes(m: string | undefined): string {
  if (!m) return ''
  const [y, mo] = m.split('-')
  const nombres = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic']
  return `${nombres[parseInt(mo) - 1]} ${y}`
}

// ── Metric card ─────────────────────────────────────────────────────────────
function MetricCard({
  label, value, sub, loading, accent,
}: {
  label: string
  value: string
  sub: string
  loading?: boolean
  accent?: 'emerald' | 'amber' | 'blue' | 'gray'
}) {
  const valueColor = {
    emerald: 'text-emerald-700',
    amber: 'text-amber-700',
    blue: 'text-blue-700',
    gray: 'text-gray-900',
  }[accent ?? 'gray']

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm px-5 py-4">
      <div className="text-[10px] text-gray-400 uppercase tracking-wider font-medium">{label}</div>
      {loading ? (
        <div className="mt-2 h-7 w-24 bg-gray-100 rounded animate-pulse" />
      ) : (
        <div className={`font-display text-2xl font-bold mt-1 ${valueColor}`}>{value}</div>
      )}
      <div className="text-[11px] text-gray-400 mt-1">{sub}</div>
    </div>
  )
}

export default function DashboardPage() {
  const [psStats, setPsStats] = useState<PlanSepareStats | null>(null)
  const [dashStats, setDashStats] = useState<DashboardStats | null>(null)
  const [dashLoading, setDashLoading] = useState(true)

  useEffect(() => {
    apiGet<PlanSepareStats>('/plan-separe/stats')
      .then(setPsStats)
      .catch(() => {})
  }, [])

  useEffect(() => {
    setDashLoading(true)
    apiGet<DashboardStats>('/dashboard/stats')
      .then(setDashStats)
      .catch(() => {})
      .finally(() => setDashLoading(false))
  }, [])

  const mesLabel = dashStats ? formatMes(dashStats.mes) : ''

  return (
    <div className="flex flex-col h-full bg-gray-50 overflow-y-auto">
      <div className="bg-white border-b border-gray-100 px-6 py-5">
        <h1 className="text-xl font-semibold text-gray-900 tracking-tight">Dashboard</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Resumen operativo{mesLabel ? ` · ${mesLabel}` : ''}
        </p>
      </div>

      {/* ── Cards mes actual ──────────────────────────────────────────── */}
      <div className="px-6 pt-5">
        <p className="text-[10px] text-gray-400 uppercase tracking-wider font-medium mb-3">
          Mes actual — {mesLabel || '…'}
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <MetricCard
            label="Dinero facturado"
            value={formatCOP(dashStats?.dinero_facturado_mes)}
            sub="Facturas abiertas en Alegra"
            loading={dashLoading}
            accent="emerald"
          />
          <MetricCard
            label="Motos facturadas"
            value={dashStats?.motos_facturadas_mes != null ? String(dashStats.motos_facturadas_mes) : '—'}
            sub="Unidades vendidas este mes"
            loading={dashLoading}
            accent="blue"
          />
          <MetricCard
            label="Cuotas recibidas"
            value={formatCOP(dashStats?.cuotas_recibidas_mes)}
            sub={dashStats?.cuotas_pagadas_count ? `${dashStats.cuotas_pagadas_count} pagos registrados` : 'Cartera activa'}
            loading={dashLoading}
            accent="amber"
          />
        </div>
      </div>

      {/* ── CFO widget: Plan Separe ───────────────────────────────────── */}
      {psStats && (
        <div className="px-6 mt-5">
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <div className="flex items-start justify-between mb-5">
              <div>
                <h2 className="text-sm font-semibold text-gray-900">Plan Separe — Anticipos de clientes</h2>
                <p className="text-xs text-gray-500 mt-0.5">Pasivo diferido y provisión de matrículas</p>
              </div>
              <a href="/plan-separe" className="text-xs text-emerald-600 hover:text-emerald-700 font-medium">
                Ver detalle →
              </a>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
              <div>
                <div className="text-[10px] text-gray-400 uppercase tracking-wider">Dinero retenido</div>
                <div className="text-xl font-semibold text-emerald-700 mt-1">{formatCOP(psStats.total_retenido)}</div>
                <div className="text-[10px] text-gray-500 mt-0.5">En caja (pasivo 2805)</div>
              </div>
              <div>
                <div className="text-[10px] text-gray-400 uppercase tracking-wider">Dinero pendiente</div>
                <div className="text-xl font-semibold text-amber-700 mt-1">
                  {formatCOP(psStats.dinero_pendiente ?? 0)}
                </div>
                <div className="text-[10px] text-gray-500 mt-0.5">Falta por ingresar</div>
              </div>
              <div>
                <div className="text-[10px] text-gray-400 uppercase tracking-wider">Matrículas</div>
                <div className="text-xl font-semibold text-gray-700 mt-1">{formatCOP(psStats.matriculas_provision_proyectada)}</div>
                <div className="text-[10px] text-gray-500 mt-0.5">
                  {psStats.por_estado.activa + psStats.por_estado.completada} × {formatCOP(psStats.matricula_unit)}
                </div>
              </div>
              <div>
                <div className="text-[10px] text-gray-400 uppercase tracking-wider">Completadas</div>
                <div className="text-xl font-semibold text-emerald-700 mt-1">{psStats.por_estado.completada}</div>
                <div className="text-[10px] text-gray-500 mt-0.5">100% pagadas</div>
              </div>
              <div>
                <div className="text-[10px] text-gray-400 uppercase tracking-wider">En abonos</div>
                <div className="text-xl font-semibold text-gray-900 mt-1">{psStats.por_estado.activa}</div>
                <div className="text-[10px] text-gray-500 mt-0.5">Parciales</div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Placeholder gráficas ─────────────────────────────────────── */}
      <div className="px-6 mt-5 pb-6 flex-1">
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 flex items-center justify-center min-h-[120px]">
          <p className="text-sm text-gray-400">Gráficas en tiempo real — próxima fase</p>
        </div>
      </div>
    </div>
  )
}
