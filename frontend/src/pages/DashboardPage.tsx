import { useEffect, useState } from 'react'
import { apiGet } from '@/lib/api'

interface PlanSepareStats {
  total_retenido: number
  matriculas_provision_actual: number
  matriculas_provision_proyectada: number
  por_estado: { activa: number; completada: number; facturada: number; cancelada: number }
  matricula_unit: number
}

function formatCOP(n: number | undefined | null): string {
  if (n === undefined || n === null) return '—'
  return new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(n)
}

export default function DashboardPage() {
  const [psStats, setPsStats] = useState<PlanSepareStats | null>(null)

  useEffect(() => {
    apiGet<PlanSepareStats>('/plan-separe/stats')
      .then(setPsStats)
      .catch(() => {})
  }, [])

  const cards = [
    { label: 'Journals hoy', value: '—', sub: 'Conectar Alegra' },
    { label: 'Backlog pendiente', value: '—', sub: 'Movimientos sin causar' },
    { label: 'Cartera activa', value: '—', sub: 'Loanbooks activos' },
    { label: 'Ultimo sync', value: '—', sub: 'Alegra API' },
  ]

  return (
    <div className="flex flex-col h-full bg-surface overflow-y-auto">
      <div className="px-6 pt-6 pb-4">
        <h1 className="font-display text-lg font-bold text-on-surface">Dashboard</h1>
        <p className="text-sm text-on-surface-variant mt-1">Resumen operativo</p>
      </div>

      <div className="px-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {cards.map((card) => (
          <div key={card.label} className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-5 py-4">
            <div className="text-xs text-on-surface-variant uppercase tracking-wider">{card.label}</div>
            <div className="font-display text-3xl font-bold text-on-surface mt-1">{card.value}</div>
            <div className="text-xs text-on-surface-variant mt-1">{card.sub}</div>
          </div>
        ))}
      </div>

      {/* CFO widget: Plan Separe */}
      {psStats && (
        <div className="px-6 mt-6">
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
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <div className="text-[10px] text-gray-400 uppercase tracking-wider">Dinero retenido</div>
                <div className="text-xl font-semibold text-gray-900 mt-1">{formatCOP(psStats.total_retenido)}</div>
                <div className="text-[10px] text-gray-500 mt-0.5">Pasivo 2805</div>
              </div>
              <div>
                <div className="text-[10px] text-gray-400 uppercase tracking-wider">Matrículas a provisionar</div>
                <div className="text-xl font-semibold text-amber-700 mt-1">{formatCOP(psStats.matriculas_provision_proyectada)}</div>
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

      <div className="px-6 mt-6 flex-1 pb-6">
        <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg p-6 h-full max-h-64 flex items-center justify-center">
          <p className="text-on-surface-variant text-sm">Graficos y metricas en tiempo real — por implementar</p>
        </div>
      </div>
    </div>
  )
}
