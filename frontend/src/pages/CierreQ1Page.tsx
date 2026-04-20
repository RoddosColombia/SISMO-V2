import { useState, useEffect } from 'react'
import { apiGet } from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface BacklogStats {
  total: number
  causados: number
  pendiente: number
  manual_pendiente: number
  sin_match: number
  error: number
  pct_causado: number
}

interface RondaDetalle {
  total: number
  detalle?: Record<string, number>
  nota?: string
}

interface RondasStats {
  pre_sprint: number
  ronda_1: RondaDetalle
  ronda_2: RondaDetalle
  ronda_3: RondaDetalle
}

interface RecaudoStats {
  legacy: number
  v2: number
  total: number
  matcheados: number
  analizados: number
  reporte_ts: string | null
}

interface CarteraLegacyStats {
  total_creditos: number
  activos: number
  saldados: number
  saldo_vigente: number
  cobertura_pct: number
}

interface PendientesEstimado {
  movimientos: number
  monto_estimado: number
  monto_promedio_mov: number
  nota: string
}

interface Reporte {
  generado_en: string
  periodo: string
  backlog: BacklogStats
  rondas: RondasStats
  recaudo: RecaudoStats
  cartera_legacy: CarteraLegacyStats
  pendientes_estimado: PendientesEstimado
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const COP = (n: number) =>
  n.toLocaleString('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 })

const Pct = (n: number) => `${n.toFixed(1)}%`

// ── Sub-components ────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string | number
  sub?: string
  accent?: 'primary' | 'warn' | 'error'
}) {
  const accentClass =
    accent === 'primary'
      ? 'text-primary'
      : accent === 'warn'
      ? 'text-amber-600'
      : accent === 'error'
      ? 'text-error'
      : 'text-on-surface'

  return (
    <div className="rounded-xl bg-surface-container-lowest p-4 flex flex-col gap-1 shadow-ambient">
      <span className="text-xs text-on-surface-variant uppercase tracking-wide">{label}</span>
      <span className={`text-2xl font-bold font-display ${accentClass}`}>{value}</span>
      {sub && <span className="text-xs text-on-surface-variant">{sub}</span>}
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-sm font-semibold uppercase tracking-wider text-on-surface-variant mt-6 mb-3">
      {children}
    </h2>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CierreQ1Page() {
  const [reporte, setReporte] = useState<Reporte | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    apiGet<{ success: boolean } & Reporte>('/cierre-q1/reporte')
      .then(r => {
        if (r.success) setReporte(r as unknown as Reporte)
        else setError('El servidor no devolvió datos válidos.')
      })
      .catch(() => setError('No se pudo cargar el reporte. Verifica conexión.'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-on-surface-variant text-sm">
        Cargando reporte...
      </div>
    )
  }

  if (error || !reporte) {
    return (
      <div className="flex-1 flex items-center justify-center text-error text-sm">
        {error || 'Error desconocido.'}
      </div>
    )
  }

  const { backlog, rondas, recaudo, cartera_legacy, pendientes_estimado } = reporte

  return (
    <div className="flex-1 overflow-y-auto bg-surface">
      <div className="max-w-5xl mx-auto px-6 py-8">

        {/* Header */}
        <div className="flex items-start justify-between mb-2">
          <div>
            <h1 className="text-2xl font-bold font-display text-on-surface">
              Cierre Q1 2026
            </h1>
            <p className="text-sm text-on-surface-variant mt-0.5">{reporte.periodo}</p>
          </div>
          <span className="text-xs text-on-surface-variant mt-1">
            {reporte.generado_en.replace('T', ' ').replace('Z', ' UTC')}
          </span>
        </div>

        {/* ── Backlog overview ── */}
        <SectionTitle>Backlog de movimientos</SectionTitle>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <StatCard label="Total" value={backlog.total} />
          <StatCard
            label="Causados"
            value={backlog.causados}
            sub={Pct(backlog.pct_causado) + ' del total'}
            accent="primary"
          />
          <StatCard label="Pendiente" value={backlog.pendiente} />
          <StatCard
            label="Manual pendiente"
            value={backlog.manual_pendiente}
            sub="Lizbeth — revisión Andrés"
            accent="warn"
          />
          <StatCard label="Sin match" value={backlog.sin_match} />
          <StatCard label="Error" value={backlog.error} accent={backlog.error > 0 ? 'error' : undefined} />
        </div>

        {/* Progress bar */}
        <div className="mt-4 rounded-xl bg-surface-container-lowest p-4 shadow-ambient">
          <div className="flex justify-between text-xs text-on-surface-variant mb-2">
            <span>Avance de causación</span>
            <span className="font-semibold text-primary">{Pct(backlog.pct_causado)}</span>
          </div>
          <div className="h-2 rounded-full bg-surface-container overflow-hidden">
            <div
              className="h-2 rounded-full bg-primary transition-all"
              style={{ width: `${Math.min(backlog.pct_causado, 100)}%` }}
            />
          </div>
          <div className="flex gap-4 mt-3 text-xs text-on-surface-variant flex-wrap">
            <span>
              <span className="font-medium text-primary">{backlog.causados}</span> causados
            </span>
            <span>
              <span className="font-medium">{backlog.pendiente}</span> por clasificar
            </span>
            <span>
              <span className="font-medium text-amber-600">{backlog.manual_pendiente}</span> revisión manual
            </span>
          </div>
        </div>

        {/* ── Rondas ── */}
        <SectionTitle>Desglose por ronda de causación</SectionTitle>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="rounded-xl bg-surface-container-lowest p-4 shadow-ambient">
            <p className="text-xs font-semibold uppercase tracking-wide text-on-surface-variant mb-2">
              Pre-sprint
            </p>
            <p className="text-xl font-bold font-display text-on-surface">{rondas.pre_sprint}</p>
            <p className="text-xs text-on-surface-variant mt-1">Movimientos anteriores al sprint Q1</p>
          </div>

          <div className="rounded-xl bg-surface-container-lowest p-4 shadow-ambient">
            <p className="text-xs font-semibold uppercase tracking-wide text-on-surface-variant mb-2">
              Ronda 1 — Reglas mecánicas
            </p>
            <p className="text-xl font-bold font-display text-primary">{rondas.ronda_1.total}</p>
            {rondas.ronda_1.detalle && (
              <ul className="mt-2 space-y-0.5">
                {Object.entries(rondas.ronda_1.detalle).map(([k, v]) => (
                  <li key={k} className="flex justify-between text-xs text-on-surface-variant">
                    <span>{k.replace(/_/g, ' ')}</span>
                    <span className="font-medium">{v}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-xl bg-surface-container-lowest p-4 shadow-ambient">
            <p className="text-xs font-semibold uppercase tracking-wide text-on-surface-variant mb-2">
              Ronda 2 — Auto-contrapartida
            </p>
            <p className="text-xl font-bold font-display text-on-surface">{rondas.ronda_2.total}</p>
            {rondas.ronda_2.nota && (
              <p className="text-xs text-on-surface-variant mt-1">{rondas.ronda_2.nota}</p>
            )}
          </div>

          <div className="rounded-xl bg-surface-container-lowest p-4 shadow-ambient">
            <p className="text-xs font-semibold uppercase tracking-wide text-on-surface-variant mb-2">
              Ronda 3 — Matcheo cartera
            </p>
            <p className="text-xl font-bold font-display text-primary">{rondas.ronda_3.total}</p>
            {rondas.ronda_3.nota && (
              <p className="text-xs text-on-surface-variant mt-1">{rondas.ronda_3.nota}</p>
            )}
          </div>
        </div>

        {/* ── Recaudo ── */}
        <SectionTitle>Recaudo Q1 identificado</SectionTitle>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <StatCard
            label="Recaudo Legacy"
            value={COP(recaudo.legacy)}
            sub={`${recaudo.matcheados} movs matcheados`}
            accent="primary"
          />
          <StatCard
            label="Recaudo V2"
            value={COP(recaudo.v2)}
            sub={`de ${recaudo.analizados} movs analizados`}
            accent="primary"
          />
          <StatCard
            label="Total recaudo"
            value={COP(recaudo.total)}
            accent="primary"
          />
        </div>

        {/* ── Cartera legacy ── */}
        <SectionTitle>Cartera legacy</SectionTitle>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard label="Total créditos" value={cartera_legacy.total_creditos} />
          <StatCard label="Activos" value={cartera_legacy.activos} />
          <StatCard label="Saldados" value={cartera_legacy.saldados} />
          <StatCard
            label="Saldo vigente"
            value={COP(cartera_legacy.saldo_vigente)}
            sub={`Cobertura recaudo: ${Pct(cartera_legacy.cobertura_pct)}`}
          />
        </div>

        {/* Coverage bar */}
        <div className="mt-3 rounded-xl bg-surface-container-lowest p-4 shadow-ambient">
          <div className="flex justify-between text-xs text-on-surface-variant mb-2">
            <span>Recaudo legacy vs saldo vigente</span>
            <span className="font-semibold text-primary">{Pct(cartera_legacy.cobertura_pct)}</span>
          </div>
          <div className="h-2 rounded-full bg-surface-container overflow-hidden">
            <div
              className="h-2 rounded-full bg-primary transition-all"
              style={{ width: `${Math.min(cartera_legacy.cobertura_pct, 100)}%` }}
            />
          </div>
          <div className="flex gap-6 mt-3 text-xs text-on-surface-variant">
            <span>Recaudo: <span className="font-medium text-primary">{COP(recaudo.legacy)}</span></span>
            <span>Saldo: <span className="font-medium">{COP(cartera_legacy.saldo_vigente)}</span></span>
          </div>
        </div>

        {/* ── Pendientes estimado ── */}
        <SectionTitle>Pendientes por clasificar</SectionTitle>
        <div className="rounded-xl bg-surface-container-lowest p-4 shadow-ambient">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <p className="text-xs text-on-surface-variant uppercase tracking-wide">Movimientos</p>
              <p className="text-2xl font-bold font-display text-amber-600 mt-1">
                {pendientes_estimado.movimientos}
              </p>
            </div>
            <div>
              <p className="text-xs text-on-surface-variant uppercase tracking-wide">Monto estimado</p>
              <p className="text-2xl font-bold font-display text-on-surface mt-1">
                {COP(pendientes_estimado.monto_estimado)}
              </p>
            </div>
            <div>
              <p className="text-xs text-on-surface-variant uppercase tracking-wide">Promedio por mov</p>
              <p className="text-2xl font-bold font-display text-on-surface mt-1">
                {COP(pendientes_estimado.monto_promedio_mov)}
              </p>
            </div>
          </div>
          <p className="text-xs text-on-surface-variant mt-3 italic">{pendientes_estimado.nota}</p>
        </div>

        {/* Footer */}
        <p className="text-xs text-on-surface-variant mt-8 text-center">
          Reporte generado automáticamente — SISMO V2 · BUILD 5
        </p>
      </div>
    </div>
  )
}
