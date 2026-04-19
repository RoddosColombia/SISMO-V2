import { useEffect, useState } from 'react'
import { apiGet } from '@/lib/api'

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
  const [dashStats, setDashStats] = useState<DashboardStats | null>(null)
  const [dashLoading, setDashLoading] = useState(true)

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

      <div className="px-6 pt-5">
        <p className="text-[10px] text-gray-400 uppercase tracking-wider font-medium mb-3">
          Mes actual — {mesLabel || '…'}
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <MetricCard
            label="Dinero facturado"
            value={formatCOP(dashStats?.dinero_facturado_mes)}
            sub="Facturas de venta en Alegra"
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

      <div className="px-6 mt-5 pb-6 flex-1">
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 flex items-center justify-center min-h-[120px]">
          <p className="text-sm text-gray-400">Gráficas en tiempo real — próxima fase</p>
        </div>
      </div>
    </div>
  )
}
