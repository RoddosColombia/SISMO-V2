import { useEffect, useState, useCallback } from 'react'
import { apiFetch } from '@/lib/api'

// ─── Types ────────────────────────────────────────────────────────────────────

interface ServiceStatus {
  ok: boolean
  latencia_ms?: number
  detalle?: string
  version?: string
  estado?: string  // circuit breaker state
}

interface BacklogStats {
  pendiente: number
  causado: number
  error: number
  total: number
}

interface StatusPayload {
  render: ServiceStatus
  mongodb: ServiceStatus
  alegra: ServiceStatus & { circuit_breaker?: string; ultimo_journal_id?: string | null }
  mercately: ServiceStatus
  backlog: BacklogStats
  jobs_activos: number
  datakeeper_vivo: boolean
  generado_en: string
}

interface DeudaItem {
  _id: string
  codigo: string
  titulo: string
  descripcion: string
  categoria: 'infra' | 'observabilidad' | 'seguridad' | 'deuda_codigo' | 'proceso'
  prioridad: number
  estado: 'pendiente' | 'en_progreso' | 'resuelto' | 'descartado'
  impacto: string
  esfuerzo_dias: number
  fase_origen?: string
  creado_en: string
  resuelto_en?: string
}

interface NewDeuda {
  titulo: string
  descripcion: string
  categoria: DeudaItem['categoria']
  prioridad: number
  impacto: string
  esfuerzo_dias: number
  fase_origen?: string
}

// ─── Constants ────────────────────────────────────────────────────────────────

const ESTADO_COLORS: Record<DeudaItem['estado'], string> = {
  pendiente:   'bg-amber-50 text-amber-800 border-amber-200',
  en_progreso: 'bg-blue-50 text-blue-800 border-blue-200',
  resuelto:    'bg-green-50 text-green-800 border-green-200',
  descartado:  'bg-surface-container-low text-on-surface-variant border-transparent',
}

const ESTADO_LABEL: Record<DeudaItem['estado'], string> = {
  pendiente:   'Pendiente',
  en_progreso: 'En progreso',
  resuelto:    'Resuelto',
  descartado:  'Descartado',
}

const CATEGORIA_LABEL: Record<DeudaItem['categoria'], string> = {
  infra:         'Infra',
  observabilidad:'Observ.',
  seguridad:     'Seguridad',
  deuda_codigo:  'Código',
  proceso:       'Proceso',
}

const PRIORIDAD_COLORS: Record<number, string> = {
  1: 'text-red-600 font-bold',
  2: 'text-red-500 font-semibold',
  3: 'text-amber-600 font-semibold',
  4: 'text-amber-500',
  5: 'text-on-surface-variant',
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block w-2.5 h-2.5 rounded-full ${ok ? 'bg-green-500' : 'bg-red-500'}`}
      aria-label={ok ? 'OK' : 'Error'}
    />
  )
}

function ServiceCard({
  title,
  service,
  extra,
}: {
  title: string
  service: ServiceStatus | null
  extra?: React.ReactNode
}) {
  if (!service) {
    return (
      <div className="bg-surface rounded-2xl p-5 shadow-[0_2px_16px_rgba(0,0,0,0.06)]">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-2.5 h-2.5 rounded-full bg-on-surface-variant/30 animate-pulse" />
          <span className="text-sm font-semibold text-on-surface">{title}</span>
        </div>
        <p className="text-xs text-on-surface-variant">Cargando...</p>
      </div>
    )
  }

  return (
    <div className={`bg-surface rounded-2xl p-5 shadow-[0_2px_16px_rgba(0,0,0,0.06)] border ${service.ok ? 'border-transparent' : 'border-red-200'}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <StatusDot ok={service.ok} />
          <span className="text-sm font-semibold text-on-surface">{title}</span>
        </div>
        {service.latencia_ms !== undefined && (
          <span className="text-xs text-on-surface-variant">{service.latencia_ms} ms</span>
        )}
      </div>

      {service.detalle && (
        <p className={`text-xs ${service.ok ? 'text-on-surface-variant' : 'text-red-600'} mb-2`}>
          {service.detalle}
        </p>
      )}

      {extra}
    </div>
  )
}

function CBBadge({ estado }: { estado?: string }) {
  if (!estado) return null
  const colors: Record<string, string> = {
    CLOSED:    'bg-green-100 text-green-800',
    HALF_OPEN: 'bg-amber-100 text-amber-800',
    OPEN:      'bg-red-100 text-red-800',
  }
  return (
    <span className={`inline-block text-xs px-2 py-0.5 rounded-full font-mono font-semibold ${colors[estado] ?? 'bg-surface-container text-on-surface-variant'}`}>
      CB {estado}
    </span>
  )
}

function AddDeudaModal({
  onClose,
  onSave,
}: {
  onClose: () => void
  onSave: (data: NewDeuda) => Promise<void>
}) {
  const [form, setForm] = useState<NewDeuda>({
    titulo: '',
    descripcion: '',
    categoria: 'deuda_codigo',
    prioridad: 3,
    impacto: '',
    esfuerzo_dias: 1,
    fase_origen: '',
  })
  const [saving, setSaving] = useState(false)

  const set = (field: keyof NewDeuda, value: string | number) =>
    setForm(f => ({ ...f, [field]: value }))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.titulo.trim() || !form.descripcion.trim() || !form.impacto.trim()) return
    setSaving(true)
    try {
      await onSave(form)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-surface rounded-2xl shadow-[0_8px_40px_rgba(0,0,0,0.18)] w-full max-w-lg p-6">
        <h2 className="text-base font-semibold text-on-surface mb-4">Nueva Deuda Técnica</h2>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs text-on-surface-variant mb-1">Título *</label>
            <input
              type="text"
              value={form.titulo}
              onChange={e => set('titulo', e.target.value)}
              className="w-full text-sm border border-surface-container rounded-lg px-3 py-2 bg-surface-container-low outline-none focus:ring-1 focus:ring-primary"
              placeholder="Ej: Agregar rate limiting al API"
            />
          </div>

          <div>
            <label className="block text-xs text-on-surface-variant mb-1">Descripción *</label>
            <textarea
              value={form.descripcion}
              onChange={e => set('descripcion', e.target.value)}
              rows={2}
              className="w-full text-sm border border-surface-container rounded-lg px-3 py-2 bg-surface-container-low outline-none focus:ring-1 focus:ring-primary resize-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-on-surface-variant mb-1">Categoría</label>
              <select
                value={form.categoria}
                onChange={e => set('categoria', e.target.value)}
                className="w-full text-sm border border-surface-container rounded-lg px-3 py-2 bg-surface-container-low outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="infra">Infra</option>
                <option value="observabilidad">Observabilidad</option>
                <option value="seguridad">Seguridad</option>
                <option value="deuda_codigo">Código</option>
                <option value="proceso">Proceso</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-on-surface-variant mb-1">Prioridad (1=urgente)</label>
              <input
                type="number"
                min={1} max={5}
                value={form.prioridad}
                onChange={e => set('prioridad', parseInt(e.target.value, 10))}
                className="w-full text-sm border border-surface-container rounded-lg px-3 py-2 bg-surface-container-low outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs text-on-surface-variant mb-1">Impacto *</label>
            <input
              type="text"
              value={form.impacto}
              onChange={e => set('impacto', e.target.value)}
              className="w-full text-sm border border-surface-container rounded-lg px-3 py-2 bg-surface-container-low outline-none focus:ring-1 focus:ring-primary"
              placeholder="Ej: Costos operativos altos en Render"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-on-surface-variant mb-1">Esfuerzo (días)</label>
              <input
                type="number"
                min={1}
                value={form.esfuerzo_dias}
                onChange={e => set('esfuerzo_dias', parseInt(e.target.value, 10))}
                className="w-full text-sm border border-surface-container rounded-lg px-3 py-2 bg-surface-container-low outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <div>
              <label className="block text-xs text-on-surface-variant mb-1">Fase origen</label>
              <input
                type="text"
                value={form.fase_origen}
                onChange={e => set('fase_origen', e.target.value)}
                className="w-full text-sm border border-surface-container rounded-lg px-3 py-2 bg-surface-container-low outline-none focus:ring-1 focus:ring-primary"
                placeholder="Phase 6, TAREA-1..."
              />
            </div>
          </div>

          <div className="flex gap-3 pt-2 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg text-on-surface-variant hover:bg-surface-container-low transition-colors"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 text-sm rounded-lg bg-primary text-white font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {saving ? 'Guardando...' : 'Guardar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ITSismoPage() {
  const [status, setStatus] = useState<StatusPayload | null>(null)
  const [deuda, setDeuda] = useState<DeudaItem[]>([])
  const [loadingStatus, setLoadingStatus] = useState(true)
  const [loadingDeuda, setLoadingDeuda] = useState(true)
  const [showAddModal, setShowAddModal] = useState(false)
  const [patchingId, setPatchingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchStatus = useCallback(async () => {
    setLoadingStatus(true)
    try {
      const data = await apiFetch<StatusPayload>('/api/it/status')
      setStatus(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error cargando estado de servicios')
    } finally {
      setLoadingStatus(false)
    }
  }, [])

  const fetchDeuda = useCallback(async () => {
    setLoadingDeuda(true)
    try {
      const data = await apiFetch<DeudaItem[]>('/api/it/deuda')
      setDeuda(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error cargando deuda técnica')
    } finally {
      setLoadingDeuda(false)
    }
  }, [])

  useEffect(() => {
    fetchStatus()
    fetchDeuda()
  }, [fetchStatus, fetchDeuda])

  const handleAddDeuda = async (data: NewDeuda) => {
    await apiFetch('/api/it/deuda', { method: 'POST', body: JSON.stringify(data) })
    await fetchDeuda()
  }

  const handlePatch = async (codigo: string, estado: DeudaItem['estado']) => {
    setPatchingId(codigo)
    try {
      await apiFetch(`/api/it/deuda/${codigo}`, {
        method: 'PATCH',
        body: JSON.stringify({ estado }),
      })
      setDeuda(prev =>
        prev.map(d => d.codigo === codigo ? { ...d, estado } : d)
      )
    } finally {
      setPatchingId(null)
    }
  }

  const handleDelete = async (codigo: string) => {
    if (!window.confirm(`¿Eliminar deuda técnica ${codigo}?`)) return
    setDeletingId(codigo)
    try {
      await apiFetch(`/api/it/deuda/${codigo}`, { method: 'DELETE' })
      setDeuda(prev => prev.filter(d => d.codigo !== codigo))
    } finally {
      setDeletingId(null)
    }
  }

  // Derived backlog stats
  const backlog = status?.backlog
  const backlogTotal = backlog ? (backlog.pendiente + backlog.causado + backlog.error) : 0
  const backlogPct = backlogTotal > 0 && backlog
    ? Math.round((backlog.causado / backlogTotal) * 100)
    : 0

  // Deuda grouped
  const pendienteCount = deuda.filter(d => d.estado === 'pendiente' || d.estado === 'en_progreso').length
  const resueltaCount = deuda.filter(d => d.estado === 'resuelto').length

  return (
    <div className="flex-1 overflow-y-auto bg-surface p-6 space-y-6">
      {/* ── Header ── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-on-surface font-display">
            IT SISMO — Panel de Operaciones
          </h1>
          <p className="text-sm text-on-surface-variant mt-0.5">
            Estado de servicios, métricas operacionales y deuda técnica
          </p>
        </div>
        <button
          onClick={fetchStatus}
          disabled={loadingStatus}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-surface-container-low text-on-surface-variant hover:bg-surface-container transition-colors disabled:opacity-50"
        >
          <svg className={`w-3.5 h-3.5 ${loadingStatus ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Refrescar
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
          {error}
        </div>
      )}

      {/* ── Sección 1: Estado de Servicios ── */}
      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-on-surface-variant mb-3">
          Estado de Servicios
        </h2>
        <div className="grid grid-cols-2 gap-4">
          {/* Render */}
          <ServiceCard
            title="Render (API)"
            service={status ? status.render : null}
            extra={
              status?.render?.version && (
                <span className="text-xs font-mono text-on-surface-variant">
                  v{status.render.version}
                </span>
              )
            }
          />

          {/* MongoDB */}
          <ServiceCard
            title="MongoDB"
            service={status ? status.mongodb : null}
          />

          {/* Alegra */}
          <ServiceCard
            title="Alegra API"
            service={status ? status.alegra : null}
            extra={
              <div className="flex items-center gap-2 mt-1">
                <CBBadge estado={status?.alegra?.circuit_breaker} />
                {status?.alegra?.ultimo_journal_id && (
                  <span className="text-xs text-on-surface-variant font-mono">
                    último J#{status.alegra.ultimo_journal_id}
                  </span>
                )}
              </div>
            }
          />

          {/* Mercately */}
          <ServiceCard
            title="Mercately"
            service={status ? status.mercately : null}
          />
        </div>
      </section>

      {/* ── Sección 2: Métricas Operacionales ── */}
      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-on-surface-variant mb-3">
          Métricas Operacionales
        </h2>
        <div className="grid grid-cols-3 gap-4">
          {/* Backlog progress */}
          <div className="col-span-2 bg-surface rounded-2xl p-5 shadow-[0_2px_16px_rgba(0,0,0,0.06)]">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-semibold text-on-surface">Backlog Movimientos</span>
              {backlog && (
                <span className="text-xs text-on-surface-variant">
                  {backlog.causado}/{backlogTotal} causados
                </span>
              )}
            </div>

            {backlog ? (
              <>
                <div className="w-full h-2 bg-surface-container-low rounded-full overflow-hidden mb-3">
                  <div
                    className="h-full bg-primary rounded-full transition-all duration-500"
                    style={{ width: `${backlogPct}%` }}
                  />
                </div>
                <div className="flex gap-4 text-xs text-on-surface-variant">
                  <span>
                    <span className="inline-block w-2 h-2 rounded-full bg-amber-400 mr-1" />
                    Pendiente: <strong className="text-on-surface">{backlog.pendiente}</strong>
                  </span>
                  <span>
                    <span className="inline-block w-2 h-2 rounded-full bg-primary mr-1" />
                    Causado: <strong className="text-on-surface">{backlog.causado}</strong>
                  </span>
                  <span>
                    <span className="inline-block w-2 h-2 rounded-full bg-red-400 mr-1" />
                    Error: <strong className="text-on-surface">{backlog.error}</strong>
                  </span>
                  <span className="ml-auto font-semibold text-primary">{backlogPct}%</span>
                </div>
              </>
            ) : (
              <div className="h-2 bg-surface-container-low rounded-full animate-pulse" />
            )}
          </div>

          {/* Jobs + DataKeeper */}
          <div className="flex flex-col gap-4">
            <div className="bg-surface rounded-2xl p-5 shadow-[0_2px_16px_rgba(0,0,0,0.06)] flex-1 flex flex-col justify-between">
              <span className="text-xs text-on-surface-variant">Jobs activos</span>
              <span className="text-2xl font-bold text-on-surface mt-1">
                {status ? status.jobs_activos : '—'}
              </span>
              <span className="text-xs text-on-surface-variant">conciliacion_jobs</span>
            </div>
            <div className="bg-surface rounded-2xl p-5 shadow-[0_2px_16px_rgba(0,0,0,0.06)] flex-1 flex flex-col justify-between">
              <span className="text-xs text-on-surface-variant">DataKeeper</span>
              <div className="mt-1">
                {status === null ? (
                  <span className="text-on-surface-variant text-sm">—</span>
                ) : status.datakeeper_vivo ? (
                  <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-green-700">
                    <span className="w-2 h-2 rounded-full bg-green-500" />
                    Activo
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-red-700">
                    <span className="w-2 h-2 rounded-full bg-red-500" />
                    Inactivo
                  </span>
                )}
              </div>
              <span className="text-xs text-on-surface-variant">listener eventos</span>
            </div>
          </div>
        </div>
      </section>

      {/* ── Sección 3: Deuda Técnica ── */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-on-surface-variant">
              Deuda Técnica
            </h2>
            {!loadingDeuda && (
              <span className="text-xs text-on-surface-variant">
                {pendienteCount} activa{pendienteCount !== 1 ? 's' : ''} · {resueltaCount} resueltas
              </span>
            )}
          </div>
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-primary text-white font-medium hover:bg-primary/90 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            Nueva deuda
          </button>
        </div>

        {loadingDeuda ? (
          <div className="space-y-2">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-12 bg-surface-container-low rounded-xl animate-pulse" />
            ))}
          </div>
        ) : deuda.length === 0 ? (
          <div className="bg-surface rounded-2xl p-8 text-center shadow-[0_2px_16px_rgba(0,0,0,0.06)]">
            <p className="text-sm text-on-surface-variant">Sin deuda técnica registrada.</p>
          </div>
        ) : (
          <div className="bg-surface rounded-2xl shadow-[0_2px_16px_rgba(0,0,0,0.06)] overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-container-low">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-on-surface-variant w-16">P</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-on-surface-variant">Título</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-on-surface-variant w-24">Categoría</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-on-surface-variant w-20">Esfuerzo</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-on-surface-variant w-28">Estado</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-on-surface-variant w-36">Acción</th>
                  <th className="w-10" />
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-container-low">
                {deuda.map(item => {
                  const isPatching = patchingId === item.codigo
                  const isDeleting = deletingId === item.codigo
                  return (
                    <tr
                      key={item._id}
                      className={`transition-colors hover:bg-surface-container-low/40 ${
                        item.estado === 'resuelto' || item.estado === 'descartado'
                          ? 'opacity-60'
                          : ''
                      }`}
                    >
                      {/* Prioridad */}
                      <td className="px-4 py-3">
                        <span className={`font-mono text-base ${PRIORIDAD_COLORS[item.prioridad] ?? ''}`}>
                          {item.prioridad}
                        </span>
                      </td>

                      {/* Título + descripción */}
                      <td className="px-4 py-3">
                        <div className="font-medium text-on-surface leading-snug">{item.titulo}</div>
                        <div className="text-xs text-on-surface-variant mt-0.5 line-clamp-1">{item.impacto}</div>
                      </td>

                      {/* Categoría */}
                      <td className="px-4 py-3">
                        <span className="text-xs text-on-surface-variant">
                          {CATEGORIA_LABEL[item.categoria] ?? item.categoria}
                        </span>
                      </td>

                      {/* Esfuerzo */}
                      <td className="px-4 py-3 text-xs text-on-surface-variant">
                        {item.esfuerzo_dias}d
                      </td>

                      {/* Estado badge */}
                      <td className="px-4 py-3">
                        <span className={`inline-block text-xs px-2 py-0.5 rounded-full border ${ESTADO_COLORS[item.estado]}`}>
                          {ESTADO_LABEL[item.estado]}
                        </span>
                      </td>

                      {/* Acción */}
                      <td className="px-4 py-3">
                        {isPatching ? (
                          <span className="text-xs text-on-surface-variant">Guardando...</span>
                        ) : item.estado === 'pendiente' ? (
                          <div className="flex gap-1.5">
                            <button
                              onClick={() => handlePatch(item.codigo, 'en_progreso')}
                              className="text-xs px-2 py-1 rounded-md bg-blue-50 text-blue-700 hover:bg-blue-100 transition-colors"
                            >
                              Iniciar
                            </button>
                            <button
                              onClick={() => handlePatch(item.codigo, 'descartado')}
                              className="text-xs px-2 py-1 rounded-md bg-surface-container-low text-on-surface-variant hover:bg-surface-container transition-colors"
                            >
                              Descartar
                            </button>
                          </div>
                        ) : item.estado === 'en_progreso' ? (
                          <div className="flex gap-1.5">
                            <button
                              onClick={() => handlePatch(item.codigo, 'resuelto')}
                              className="text-xs px-2 py-1 rounded-md bg-green-50 text-green-700 hover:bg-green-100 transition-colors"
                            >
                              Resolver
                            </button>
                            <button
                              onClick={() => handlePatch(item.codigo, 'pendiente')}
                              className="text-xs px-2 py-1 rounded-md bg-surface-container-low text-on-surface-variant hover:bg-surface-container transition-colors"
                            >
                              Pausar
                            </button>
                          </div>
                        ) : item.estado === 'resuelto' ? (
                          <button
                            onClick={() => handlePatch(item.codigo, 'pendiente')}
                            className="text-xs px-2 py-1 rounded-md bg-surface-container-low text-on-surface-variant hover:bg-surface-container transition-colors"
                          >
                            Reabrir
                          </button>
                        ) : (
                          <button
                            onClick={() => handlePatch(item.codigo, 'pendiente')}
                            className="text-xs px-2 py-1 rounded-md bg-surface-container-low text-on-surface-variant hover:bg-surface-container transition-colors"
                          >
                            Reactivar
                          </button>
                        )}
                      </td>

                      {/* Delete */}
                      <td className="pr-3 py-3 text-right">
                        <button
                          onClick={() => handleDelete(item.codigo)}
                          disabled={isDeleting}
                          aria-label="Eliminar"
                          className="p-1 rounded-md text-on-surface-variant/40 hover:text-red-500 hover:bg-red-50 transition-colors disabled:opacity-30"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                          </svg>
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── Add modal ── */}
      {showAddModal && (
        <AddDeudaModal
          onClose={() => setShowAddModal(false)}
          onSave={handleAddDeuda}
        />
      )}
    </div>
  )
}
