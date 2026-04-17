import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { apiGet } from '@/lib/api'

// ═══════════════════════════════════════════
// Types
// ═══════════════════════════════════════════

interface LoanbookRef {
  loanbook_id: string
  tipo_producto?: string
  modelo?: string
  vin?: string | null
  estado: string
  plan_codigo?: string
  modalidad?: string
  cuota_monto?: number
  num_cuotas?: number
  cuotas_pagadas?: number
  saldo_capital?: number
  dpd?: number
}

interface Pago {
  loanbook_id: string
  cuota_numero: number
  monto: number
  fecha_programada?: string
  fecha_pago?: string
  metodo_pago?: string
  referencia?: string
}

interface Comportamiento {
  pct_a_tiempo: number | null
  promedio_atraso: number
  racha: number
  racha_tipo: 'a_tiempo' | 'atraso' | null
  ultimos_estados: string[]
}

interface Resumen {
  total_financiado: number
  total_pagado: number
  saldo_total: number
  cuotas_al_dia: number
  cuotas_en_mora: number
}

interface Cliente {
  cedula: string
  nombre?: string
  telefono?: string
  telefono_alternativo?: string | null
  email?: string
  direccion?: string
  ciudad?: string
  nacionalidad?: string
  lugar_nacimiento?: string
  fecha_nacimiento?: string
  edad?: number
  ingresos_mensuales?: number
  profesion?: string
  lugar_trabajo?: string
  estado_civil?: string
  score_pago?: string
  score?: string
  nivel_riesgo?: string
  notas?: string
  estado?: string
  loanbooks?: LoanbookRef[]
  resumen?: Resumen
  historial_pagos?: Pago[]
  comportamiento?: Comportamiento
  apto_nuevo_credito?: boolean
}

// ═══════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════

function formatCOP(n: number | undefined | null) {
  if (n === undefined || n === null) return '—'
  return new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(n)
}

function formatDate(d: string | null | undefined) {
  if (!d) return '—'
  try {
    return new Date(d + 'T12:00:00').toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric' })
  } catch { return d }
}

function cleanPhone(p: string | undefined | null) {
  return (p || '').replace(/[^\d]/g, '')
}

function scoreBadge(bucket: string | undefined) {
  if (!bucket) return 'bg-neutral-300 text-neutral-700'
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

function estadoBadge(estado: string | undefined) {
  const map: Record<string, string> = {
    activo: 'bg-emerald-500/15 text-emerald-700',
    al_dia: 'bg-emerald-500/15 text-emerald-700',
    mora: 'bg-red-500/15 text-red-700',
    mora_grave: 'bg-red-600/20 text-red-800',
    saldado: 'bg-neutral-400/20 text-neutral-600',
    pendiente_entrega: 'bg-orange-500/15 text-orange-700',
  }
  return map[estado || ''] || 'bg-neutral-400/15 text-neutral-600'
}

// ═══════════════════════════════════════════
// Inline editable row
// ═══════════════════════════════════════════

function EditableRow({
  label, value, onSave, type = 'text',
}: {
  label: string
  value: string | number | undefined | null
  onSave: (v: string) => Promise<void>
  type?: 'text' | 'number' | 'date' | 'email'
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value ?? '')
  const [saving, setSaving] = useState(false)

  useEffect(() => { setDraft(value ?? '') }, [value])

  async function commit() {
    setSaving(true)
    try {
      await onSave(String(draft))
      setEditing(false)
    } finally { setSaving(false) }
  }

  if (!editing) {
    return (
      <div className="flex justify-between items-start gap-3 py-1.5 text-sm">
        <span className="text-on-surface-variant shrink-0">{label}</span>
        <span
          onClick={() => setEditing(true)}
          className="text-on-surface font-medium text-right break-all cursor-pointer hover:bg-surface-container-low/50 px-2 py-0.5 rounded"
          title="Clic para editar"
        >
          {value ?? <span className="text-on-surface-variant/60 italic">—</span>}
        </span>
      </div>
    )
  }

  return (
    <div className="flex justify-between items-center gap-3 py-1.5 text-sm">
      <span className="text-on-surface-variant shrink-0">{label}</span>
      <input
        autoFocus
        type={type}
        value={String(draft)}
        onChange={e => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={e => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') { setEditing(false); setDraft(value ?? '') }
        }}
        disabled={saving}
        className="flex-1 max-w-[60%] rounded-md bg-surface-container-low px-2 py-1 text-sm text-on-surface outline-none focus:ring-2 focus:ring-primary/30"
      />
    </div>
  )
}

// ═══════════════════════════════════════════
// Section wrapper
// ═══════════════════════════════════════════

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white rounded-xl shadow-sm px-4 py-4 sm:px-5 sm:py-5">
      <h2 className="font-display font-bold text-on-surface text-sm mb-3 uppercase tracking-wider">{title}</h2>
      {children}
    </section>
  )
}

// ═══════════════════════════════════════════
// Main Page
// ═══════════════════════════════════════════

export default function ClientDetailPage() {
  const { cedula } = useParams<{ cedula: string }>()
  const navigate = useNavigate()
  const [client, setClient] = useState<Cliente | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!cedula) return
    setLoading(true)
    try {
      const data = await apiGet<Cliente>(`/crm/clientes/${cedula}`)
      setClient(data)
      setError('')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error cargando cliente')
    } finally { setLoading(false) }
  }, [cedula])

  useEffect(() => { load() }, [load])

  async function saveField(field: string, value: string) {
    if (!cedula) return
    // Convert based on expected type
    let val: unknown = value
    if (['edad', 'ingresos_mensuales'].includes(field)) {
      val = value ? Number(value) : undefined
    }
    const res = await fetch(`/api/crm/clientes/${cedula}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('token') || ''}`,
      },
      body: JSON.stringify({ [field]: val }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'error' }))
      throw new Error(err.detail || 'Error guardando')
    }
    await load()
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full bg-surface">
        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (error || !client) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-surface p-6 text-center">
        <p className="text-sm text-red-600 mb-3">{error || 'Cliente no encontrado'}</p>
        <button onClick={() => navigate('/crm')}
          className="px-4 py-2 rounded-md bg-primary text-white text-sm font-medium">
          ← Volver a Clientes
        </button>
      </div>
    )
  }

  const telClean = cleanPhone(client.telefono)
  const score = client.score_pago || client.score
  const comp = client.comportamiento
  const resumen = client.resumen

  return (
    <div className="flex flex-col h-full bg-surface overflow-y-auto">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-surface/95 backdrop-blur-sm px-4 py-3 sm:px-6">
        <button onClick={() => navigate('/crm')}
          className="text-xs text-on-surface-variant hover:text-on-surface mb-2 flex items-center gap-1">
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
          Volver a Clientes
        </button>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <h1 className="font-display text-lg sm:text-xl font-bold text-on-surface break-words">
              {client.nombre || '—'}
            </h1>
            <p className="text-xs text-on-surface-variant mt-0.5 font-mono">CC {client.cedula}</p>
          </div>
          <div className="flex gap-2 flex-wrap">
            <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold ${scoreBadge(score)}`}>
              Score {score || 'Sin evaluar'}
            </span>
            <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold ${
              client.apto_nuevo_credito === true ? 'bg-emerald-500/15 text-emerald-700'
              : client.apto_nuevo_credito === false ? 'bg-red-500/15 text-red-700'
              : 'bg-neutral-400/15 text-neutral-600'
            }`}>
              {client.apto_nuevo_credito === true ? 'Apto nuevo crédito'
              : client.apto_nuevo_credito === false ? 'No apto'
              : 'Sin evaluar'}
            </span>
          </div>
        </div>
        {/* Contact buttons */}
        {client.telefono && (
          <div className="flex gap-2 mt-3">
            <a href={`https://wa.me/${telClean}`} target="_blank" rel="noopener noreferrer"
              className="flex-1 inline-flex items-center justify-center gap-2 px-3 py-2 rounded-md bg-emerald-500 text-white text-xs font-medium hover:bg-emerald-600">
              WhatsApp
            </a>
            <a href={`tel:+${telClean}`}
              className="flex-1 inline-flex items-center justify-center gap-2 px-3 py-2 rounded-md bg-primary text-white text-xs font-medium hover:bg-primary/90">
              Llamar
            </a>
          </div>
        )}
      </div>

      <div className="flex-1 px-4 sm:px-6 pb-6 space-y-3">

        {/* Datos personales */}
        <Section title="Datos personales">
          <EditableRow label="Teléfono" value={client.telefono} onSave={v => saveField('telefono', v)} />
          <EditableRow label="Teléfono alt." value={client.telefono_alternativo} onSave={v => saveField('telefono_alternativo', v)} />
          <EditableRow label="Email" value={client.email} onSave={v => saveField('email', v)} type="email" />
          <EditableRow label="Dirección" value={client.direccion} onSave={v => saveField('direccion', v)} />
          <EditableRow label="Ciudad" value={client.ciudad} onSave={v => saveField('ciudad', v)} />
          <EditableRow label="Nacionalidad" value={client.nacionalidad} onSave={v => saveField('nacionalidad', v)} />
          <EditableRow label="Lugar nacimiento" value={client.lugar_nacimiento} onSave={v => saveField('lugar_nacimiento', v)} />
          <EditableRow label="Fecha nacimiento" value={client.fecha_nacimiento} onSave={v => saveField('fecha_nacimiento', v)} type="date" />
          {client.edad !== undefined && (
            <div className="flex justify-between py-1.5 text-sm">
              <span className="text-on-surface-variant">Edad</span>
              <span className="text-on-surface font-medium">{client.edad} años</span>
            </div>
          )}
          <EditableRow label="Profesión" value={client.profesion} onSave={v => saveField('profesion', v)} />
          <EditableRow label="Lugar trabajo" value={client.lugar_trabajo} onSave={v => saveField('lugar_trabajo', v)} />
          <EditableRow label="Ingresos mensuales" value={client.ingresos_mensuales ?? ''} onSave={v => saveField('ingresos_mensuales', v)} type="number" />
          <EditableRow label="Estado civil" value={client.estado_civil} onSave={v => saveField('estado_civil', v)} />
        </Section>

        {/* Créditos */}
        <Section title={`Créditos (${(client.loanbooks || []).length})`}>
          {resumen && (
            <div className="grid grid-cols-2 gap-2 mb-3">
              <div className="bg-surface-container-low rounded-md px-3 py-2">
                <div className="text-[10px] text-on-surface-variant uppercase">Total financiado</div>
                <div className="text-sm font-bold text-on-surface">{formatCOP(resumen.total_financiado)}</div>
              </div>
              <div className="bg-surface-container-low rounded-md px-3 py-2">
                <div className="text-[10px] text-on-surface-variant uppercase">Total pagado</div>
                <div className="text-sm font-bold text-emerald-600">{formatCOP(resumen.total_pagado)}</div>
              </div>
              <div className="bg-surface-container-low rounded-md px-3 py-2">
                <div className="text-[10px] text-on-surface-variant uppercase">Saldo total</div>
                <div className="text-sm font-bold text-on-surface">{formatCOP(resumen.saldo_total)}</div>
              </div>
              <div className="bg-surface-container-low rounded-md px-3 py-2">
                <div className="text-[10px] text-on-surface-variant uppercase">Cuotas</div>
                <div className="text-xs text-on-surface">
                  <span className="text-emerald-600 font-bold">{resumen.cuotas_al_dia}</span> al día
                  {resumen.cuotas_en_mora > 0 && (
                    <> / <span className="text-red-600 font-bold">{resumen.cuotas_en_mora}</span> mora</>
                  )}
                </div>
              </div>
            </div>
          )}
          {(client.loanbooks || []).length === 0 ? (
            <p className="text-xs text-on-surface-variant text-center py-4">Sin créditos asociados</p>
          ) : (
            <div className="space-y-2">
              {(client.loanbooks || []).map(lb => (
                <div key={lb.loanbook_id}
                  className="bg-surface-container-lowest shadow-sm rounded-md px-3 py-2">
                  <div className="flex justify-between items-start gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono text-on-surface-variant">{lb.loanbook_id}</span>
                        <span className={`px-1.5 py-0.5 rounded-full text-[9px] font-bold ${estadoBadge(lb.estado)}`}>
                          {lb.estado}
                        </span>
                      </div>
                      <div className="text-xs text-on-surface mt-0.5">
                        {lb.modelo} · {lb.plan_codigo} {lb.modalidad}
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className="text-xs font-bold text-on-surface">{formatCOP(lb.saldo_capital)}</div>
                      <div className="text-[10px] text-on-surface-variant">
                        {lb.cuotas_pagadas}/{lb.num_cuotas}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* Comportamiento */}
        <Section title="Comportamiento de pago">
          {!comp || comp.pct_a_tiempo === null ? (
            <p className="text-xs text-on-surface-variant text-center py-4">Sin datos aún</p>
          ) : (
            <>
              <div className="flex justify-between py-1.5 text-sm">
                <span className="text-on-surface-variant">% Pagos a tiempo</span>
                <span className="text-on-surface font-medium">{comp.pct_a_tiempo}%</span>
              </div>
              <div className="flex justify-between py-1.5 text-sm">
                <span className="text-on-surface-variant">Promedio atraso</span>
                <span className="text-on-surface font-medium">{comp.promedio_atraso} días</span>
              </div>
              <div className="flex justify-between py-1.5 text-sm">
                <span className="text-on-surface-variant">Racha actual</span>
                <span className={comp.racha_tipo === 'a_tiempo' ? 'text-emerald-600 font-medium' : 'text-red-600 font-medium'}>
                  {comp.racha} {comp.racha_tipo === 'a_tiempo' ? 'pagos puntuales' : 'cuotas con atraso'}
                </span>
              </div>
              {/* Últimos 10 pagos */}
              {comp.ultimos_estados.length > 0 && (
                <div className="mt-3">
                  <div className="text-[10px] text-on-surface-variant uppercase mb-1">Últimos pagos</div>
                  <div className="flex gap-1">
                    {comp.ultimos_estados.map((e, i) => (
                      <div key={i}
                        className={`h-4 w-4 rounded ${e === 'a_tiempo' ? 'bg-emerald-500' : 'bg-red-500'}`}
                        title={e === 'a_tiempo' ? 'A tiempo' : 'Con atraso'}
                      />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </Section>

        {/* Historial de pagos */}
        <Section title="Historial de pagos">
          {(client.historial_pagos || []).length === 0 ? (
            <p className="text-xs text-on-surface-variant text-center py-4">Sin pagos registrados</p>
          ) : (
            <div className="max-h-64 overflow-y-auto -mx-1">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-on-surface-variant border-b border-surface-container-low">
                    <th className="text-left px-2 py-2 font-medium">Fecha</th>
                    <th className="text-left px-2 py-2 font-medium">Crédito</th>
                    <th className="text-center px-2 py-2 font-medium">#</th>
                    <th className="text-right px-2 py-2 font-medium">Valor</th>
                    <th className="text-left px-2 py-2 font-medium">Método</th>
                  </tr>
                </thead>
                <tbody>
                  {(client.historial_pagos || []).map((p, i) => (
                    <tr key={i} className="border-b border-surface-container-low/50">
                      <td className="px-2 py-1.5 text-on-surface">{formatDate(p.fecha_pago)}</td>
                      <td className="px-2 py-1.5 font-mono text-[10px] text-on-surface-variant">{p.loanbook_id}</td>
                      <td className="px-2 py-1.5 text-center text-on-surface">{p.cuota_numero}</td>
                      <td className="px-2 py-1.5 text-right text-on-surface">{formatCOP(p.monto)}</td>
                      <td className="px-2 py-1.5 text-on-surface-variant">{p.metodo_pago || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>

        {/* Notas */}
        <Section title="Notas del gestor">
          <EditableRow label="Notas" value={client.notas} onSave={v => saveField('notas', v)} />
        </Section>

      </div>
    </div>
  )
}
