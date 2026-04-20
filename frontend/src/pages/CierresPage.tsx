import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiGet } from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Bloqueantes {
  manual_pendiente: number
  errores_cuenta: number
  sin_categoria: number
}

interface PeriodoSummary {
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
}

interface ListResponse {
  success: boolean
  generado_en: string
  periodos: PeriodoSummary[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const Pct = (n: number) => `${n.toFixed(1)}%`

function estadoBadge(estado: PeriodoSummary['estado']) {
  if (estado === 'cerrado') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700">
        <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
        CERRADO
      </span>
    )
  }
  if (estado === 'en_progreso') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700">
        <span className="w-2 h-2 rounded-full bg-amber-500 inline-block" />
        EN PROGRESO
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-on-surface-variant">
      <span className="w-2 h-2 rounded-full bg-on-surface-variant/40 inline-block" />
      ABIERTO
    </span>
  )
}

function bloqueantesCount(b: Bloqueantes) {
  return b.manual_pendiente + b.errores_cuenta + b.sin_categoria
}

// ── PeriodoCard ───────────────────────────────────────────────────────────────

function PeriodoCard({
  periodo,
  onClick,
}: {
  periodo: PeriodoSummary
  onClick: () => void
}) {
  const total = bloqueantesCount(periodo.bloqueantes)
  const isEmpty = periodo.total_movimientos === 0

  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-xl bg-surface-container-lowest p-5 shadow-ambient hover:shadow-md transition-shadow group"
    >
      {/* Row 1: título + flecha */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-bold font-display text-on-surface group-hover:text-primary transition-colors">
            {periodo.label}
          </h2>
          <p className="text-xs text-on-surface-variant mt-0.5">{periodo.rango}</p>
        </div>
        <div className="flex items-center gap-3 shrink-0 mt-0.5">
          {estadoBadge(periodo.estado)}
          <svg
            className="w-4 h-4 text-on-surface-variant group-hover:text-primary transition-colors"
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
        </div>
      </div>

      {/* Row 2: barra de progreso */}
      <div className="mt-4">
        <div className="flex justify-between text-xs text-on-surface-variant mb-1.5">
          <span>Causación</span>
          <span className="font-semibold text-primary">{Pct(periodo.pct_causado)}</span>
        </div>
        <div className="h-2 rounded-full bg-surface-container overflow-hidden">
          <div
            className={`h-2 rounded-full transition-all ${
              periodo.estado === 'cerrado'
                ? 'bg-emerald-500'
                : periodo.estado === 'en_progreso'
                ? 'bg-primary'
                : 'bg-on-surface-variant/20'
            }`}
            style={{ width: `${Math.min(periodo.pct_causado, 100)}%` }}
          />
        </div>
      </div>

      {/* Row 3: stats / mensaje vacío */}
      <div className="mt-3 text-xs text-on-surface-variant">
        {isEmpty ? (
          <span className="italic">0 movimientos · Sube extractos para empezar</span>
        ) : (
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <span>
              <span className="font-medium text-on-surface">{periodo.causados}</span> causados
            </span>
            <span>
              <span className="font-medium text-on-surface">{periodo.pendientes}</span> pendientes
            </span>
            {periodo.manual_pendiente > 0 && (
              <span className="text-amber-600 font-medium">
                {periodo.manual_pendiente} manuales
              </span>
            )}
            {periodo.errores > 0 && (
              <span className="text-error font-medium">
                {periodo.errores} errores
              </span>
            )}
          </div>
        )}
      </div>

      {/* Row 4: alerta bloqueantes */}
      {total > 0 && (
        <div className="mt-3 flex items-center gap-1.5 text-xs text-amber-700">
          <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
          </svg>
          {`${total} bloqueante${total !== 1 ? 's' : ''} activo${total !== 1 ? 's' : ''}`}
        </div>
      )}
    </button>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CierresPage() {
  const navigate = useNavigate()
  const [periodos, setPeriodos] = useState<PeriodoSummary[]>([])
  const [generadoEn, setGeneradoEn] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    apiGet<ListResponse>('/cierres')
      .then(r => {
        if (r.success) {
          setPeriodos(r.periodos ?? [])
          setGeneradoEn(r.generado_en ?? '')
        } else {
          setError('El servidor no devolvió datos válidos.')
        }
      })
      .catch(() => setError('No se pudo cargar la lista de cierres.'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-on-surface-variant text-sm">
        Cargando cierres...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-error text-sm">{error}</div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto bg-surface">
      <div className="max-w-2xl mx-auto px-6 py-8">

        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold font-display text-on-surface">Cierres Contables</h1>
            <p className="text-sm text-on-surface-variant mt-0.5">Estado contable por trimestre</p>
          </div>
          {generadoEn && (
            <span className="text-xs text-on-surface-variant mt-1">
              {generadoEn.replace('T', ' ').replace('Z', ' UTC')}
            </span>
          )}
        </div>

        {/* Cards */}
        <div className="space-y-3">
          {periodos.map(p => (
            <PeriodoCard
              key={p.periodo_id}
              periodo={p}
              onClick={() => navigate(`/cierres/${p.periodo_id}`)}
            />
          ))}
          {periodos.length === 0 && (
            <p className="text-sm text-on-surface-variant text-center py-12">
              No hay períodos detectados.
            </p>
          )}
        </div>

        <p className="text-xs text-on-surface-variant mt-8 text-center">
          SISMO V2 · Cierres Contables
        </p>
      </div>
    </div>
  )
}
