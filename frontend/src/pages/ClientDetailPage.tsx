import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { apiGet } from '@/lib/api'

// ═══════════════════════════════════════════
// ClientDetailPage — Refined minimalist design
//
// Design intent: premium concessionaire UX — mucho whitespace, tipografía
// clara (text-sm/text-xs), bordes gray-100 apenas visibles, sombras mínimas.
// Accent color único (#006e2a primary) reservado para acciones y score A/A+.
// ═══════════════════════════════════════════

// ── Types ─────────────────────────────────────────────────────────────

interface LoanbookRef {
  loanbook_id: string
  tipo_producto?: string
  modelo?: string
  vin?: string | null
  estado: string
  plan_codigo?: string | null
  modalidad?: string
  cuota_monto?: number
  num_cuotas?: number
  cuotas_pagadas?: number
  saldo_capital?: number | null
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

// ── Helpers ──────────────────────────────────────────────────────────

function formatCOP(n: number | undefined | null): string {
  if (n === undefined || n === null) return '—'
  return new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(n)
}

function formatDate(d: string | null | undefined): string {
  if (!d) return '—'
  try {
    return new Date(d + 'T12:00:00').toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric' })
  } catch { return d }
}

function cleanPhone(p: string | undefined | null): string {
  return (p || '').replace(/[^\d]/g, '')
}

// Score pill — sutil, bg claro + text oscuro + border del mismo tono
function scorePillClass(bucket: string | undefined): string {
  if (!bucket) return 'bg-gray-100 text-gray-500 border-gray-200'
  const map: Record<string, string> = {
    'A+': 'bg-emerald-100 text-emerald-800 border-emerald-200',
    'A':  'bg-emerald-50 text-emerald-700 border-emerald-200',
    'B':  'bg-amber-50 text-amber-800 border-amber-200',
    'C':  'bg-orange-50 text-orange-800 border-orange-200',
    'D':  'bg-red-50 text-red-700 border-red-200',
    'E':  'bg-red-100 text-red-800 border-red-300',
  }
  return map[bucket] || 'bg-gray-100 text-gray-500 border-gray-200'
}

function estadoPillClass(estado: string | undefined): string {
  const map: Record<string, string> = {
    activo: 'bg-emerald-50 text-emerald-700 border-emerald-100',
    al_dia: 'bg-emerald-50 text-emerald-700 border-emerald-100',
    mora: 'bg-red-50 text-red-700 border-red-100',
    mora_grave: 'bg-red-100 text-red-800 border-red-200',
    saldado: 'bg-gray-100 text-gray-600 border-gray-200',
    pendiente_entrega: 'bg-amber-50 text-amber-800 border-amber-100',
    en_riesgo: 'bg-yellow-50 text-yellow-800 border-yellow-100',
  }
  return map[estado || ''] || 'bg-gray-100 text-gray-600 border-gray-200'
}

function estadoLabel(estado: string | undefined): string {
  const map: Record<string, string> = {
    activo: 'Activo', al_dia: 'Al día', mora: 'Mora', mora_grave: 'Mora grave',
    en_riesgo: 'En riesgo', saldado: 'Saldado', pendiente_entrega: 'Pend. entrega',
  }
  return map[estado || ''] || estado || '—'
}

// ── Icons (lucide-style inline SVGs) ─────────────────────────────────

function IconPhone({ className = '' }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
    </svg>
  )
}

function IconMessage({ className = '' }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
    </svg>
  )
}

function IconEdit({ className = '' }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
    </svg>
  )
}

// ── Inline editable row ──────────────────────────────────────────────

function EditableRow({
  label,
  value,
  onSave,
  type = 'text',
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

  const isEmpty = value === undefined || value === null || value === ''

  if (editing) {
    return (
      <div className="flex items-center gap-3 py-3 border-b border-gray-100 last:border-b-0 transition-all">
        <span className="text-[10px] text-gray-400 uppercase tracking-wider w-32 shrink-0">{label}</span>
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
          className="flex-1 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm text-gray-900 outline-none focus:ring-2 focus:ring-emerald-100 focus:border-emerald-300 transition-all"
        />
      </div>
    )
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      className="w-full flex items-center gap-3 py-3 border-b border-gray-100 last:border-b-0 text-left group hover:bg-gray-50/50 -mx-3 px-3 rounded transition-colors"
    >
      <span className="text-[10px] text-gray-400 uppercase tracking-wider w-32 shrink-0">{label}</span>
      <span className="flex-1 text-sm text-gray-900 flex items-center gap-2">
        {isEmpty
          ? <span className="text-gray-300">—</span>
          : <span className="break-all">{value}</span>
        }
        <IconEdit className="w-3 h-3 text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity ml-auto" />
      </span>
    </button>
  )
}

// ── Section wrapper ──────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white rounded-xl border border-gray-100 shadow-sm px-5 py-5 sm:px-6 sm:py-6">
      <h2 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-4">{title}</h2>
      {children}
    </section>
  )
}

// ══════════════════════════════════════════════════════════════════════
// Main Page
// ══════════════════════════════════════════════════════════════════════

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
      <div className="flex items-center justify-center h-full bg-gray-50">
        <div className="w-5 h-5 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (error || !client) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-gray-50 p-6 text-center">
        <p className="text-sm text-red-600 mb-4">{error || 'Cliente no encontrado'}</p>
        <button onClick={() => navigate('/crm')}
          className="px-4 py-2 rounded-md bg-gray-100 text-gray-700 text-sm font-medium hover:bg-gray-200 transition-colors">
          ← Volver a Clientes
        </button>
      </div>
    )
  }

  const telClean = cleanPhone(client.telefono)
  const score = client.score_pago || client.score
  const comp = client.comportamiento
  const resumen = client.resumen
  const loanbooks = client.loanbooks || []
  const historial = client.historial_pagos || []

  const aptoText = client.apto_nuevo_credito === true ? 'Apto nuevo crédito'
    : client.apto_nuevo_credito === false ? 'No apto'
    : 'Sin evaluar'
  const aptoClass = client.apto_nuevo_credito === true
    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
    : client.apto_nuevo_credito === false
    ? 'bg-red-50 text-red-600 border-red-200'
    : 'bg-gray-100 text-gray-500 border-gray-200'

  return (
    <div className="flex flex-col h-full bg-gray-50 overflow-y-auto">
      {/* Header */}
      <div className="bg-white border-b border-gray-100">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-5">
          <button onClick={() => navigate('/crm')}
            className="text-xs text-gray-400 hover:text-gray-700 mb-3 flex items-center gap-1 transition-colors">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
            </svg>
            Volver a Clientes
          </button>

          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            {/* Name + CC */}
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold text-gray-900 tracking-tight break-words">
                {client.nombre || '—'}
              </h1>
              <p className="text-xs text-gray-400 mt-1 font-mono">CC {client.cedula}</p>
            </div>

            {/* Score + Apto pills */}
            <div className="flex flex-wrap items-center gap-2 shrink-0">
              <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-medium border ${scorePillClass(score)}`}>
                Score {score || 'Sin evaluar'}
              </span>
              <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-medium border ${aptoClass}`}>
                {aptoText}
              </span>
            </div>
          </div>

          {/* Contact actions — pills, no full-width */}
          {client.telefono && (
            <div className="flex flex-wrap gap-2 mt-4">
              <a href={`https://wa.me/${telClean}`} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-green-50 text-green-700 border border-green-200 hover:bg-green-100 transition-colors">
                <IconMessage className="w-3.5 h-3.5" />
                WhatsApp
              </a>
              <a href={`tel:+${telClean}`}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-gray-50 text-gray-700 border border-gray-200 hover:bg-gray-100 transition-colors">
                <IconPhone className="w-3.5 h-3.5" />
                Llamar
              </a>
            </div>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="max-w-5xl mx-auto w-full px-4 sm:px-6 py-6 space-y-4">

        {/* Datos personales — 2 col grid on desktop */}
        <Section title="Datos personales">
          <div className="grid grid-cols-1 sm:grid-cols-2 sm:gap-x-8">
            <div className="sm:col-span-1">
              <EditableRow label="Teléfono" value={client.telefono} onSave={v => saveField('telefono', v)} />
              <EditableRow label="Alternativo" value={client.telefono_alternativo} onSave={v => saveField('telefono_alternativo', v)} />
              <EditableRow label="Email" value={client.email} onSave={v => saveField('email', v)} type="email" />
              <EditableRow label="Dirección" value={client.direccion} onSave={v => saveField('direccion', v)} />
              <EditableRow label="Ciudad" value={client.ciudad} onSave={v => saveField('ciudad', v)} />
              <EditableRow label="Nacionalidad" value={client.nacionalidad} onSave={v => saveField('nacionalidad', v)} />
              <EditableRow label="Lugar nacim." value={client.lugar_nacimiento} onSave={v => saveField('lugar_nacimiento', v)} />
            </div>
            <div className="sm:col-span-1">
              <EditableRow label="Fecha nacim." value={client.fecha_nacimiento} onSave={v => saveField('fecha_nacimiento', v)} type="date" />
              {client.edad !== undefined && (
                <div className="flex items-center gap-3 py-3 border-b border-gray-100">
                  <span className="text-[10px] text-gray-400 uppercase tracking-wider w-32 shrink-0">Edad</span>
                  <span className="text-sm text-gray-900">{client.edad} años</span>
                </div>
              )}
              <EditableRow label="Profesión" value={client.profesion} onSave={v => saveField('profesion', v)} />
              <EditableRow label="Lugar trabajo" value={client.lugar_trabajo} onSave={v => saveField('lugar_trabajo', v)} />
              <EditableRow label="Ingresos" value={client.ingresos_mensuales ?? ''} onSave={v => saveField('ingresos_mensuales', v)} type="number" />
              <EditableRow label="Estado civil" value={client.estado_civil} onSave={v => saveField('estado_civil', v)} />
            </div>
          </div>
        </Section>

        {/* Créditos — minimalist cards */}
        <Section title={`Créditos (${loanbooks.length})`}>
          {resumen && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-5 pb-5 border-b border-gray-100">
              <div>
                <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Financiado</div>
                <div className="text-sm font-semibold text-gray-900">{formatCOP(resumen.total_financiado)}</div>
              </div>
              <div>
                <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Pagado</div>
                <div className="text-sm font-semibold text-emerald-700">{formatCOP(resumen.total_pagado)}</div>
              </div>
              <div>
                <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Saldo</div>
                <div className="text-sm font-semibold text-gray-900">{formatCOP(resumen.saldo_total)}</div>
              </div>
              <div>
                <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Cuotas</div>
                <div className="text-sm text-gray-900">
                  <span className="text-emerald-700 font-semibold">{resumen.cuotas_al_dia}</span>
                  {resumen.cuotas_en_mora > 0 && (
                    <span className="text-red-600"> · {resumen.cuotas_en_mora} mora</span>
                  )}
                </div>
              </div>
            </div>
          )}
          {loanbooks.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-6">Sin créditos asociados</p>
          ) : (
            <div className="space-y-2">
              {loanbooks.map(lb => (
                <button
                  key={lb.loanbook_id}
                  onClick={() => navigate(`/loanbook/${lb.loanbook_id}`)}
                  className="w-full flex items-center justify-between gap-4 py-3 px-4 rounded-lg hover:bg-gray-50 transition-colors text-left border border-transparent hover:border-gray-100"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-xs font-mono text-gray-400">{lb.loanbook_id}</span>
                      <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium border ${estadoPillClass(lb.estado)}`}>
                        {estadoLabel(lb.estado)}
                      </span>
                    </div>
                    <div className="text-sm text-gray-900">
                      {lb.modelo}{lb.plan_codigo && ` · ${lb.plan_codigo}`}{lb.modalidad && ` · ${lb.modalidad}`}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-sm font-semibold text-gray-900">{formatCOP(lb.saldo_capital ?? 0)}</div>
                    <div className="text-[10px] text-gray-400">{lb.cuotas_pagadas ?? 0}/{lb.num_cuotas ?? 0}</div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Section>

        {/* Comportamiento — mini chart */}
        <Section title="Comportamiento de pago">
          {!comp || comp.pct_a_tiempo === null ? (
            <p className="text-sm text-gray-400 text-center py-4">Sin datos de pagos aún</p>
          ) : (
            <div className="flex flex-col sm:flex-row sm:items-center gap-6">
              {/* % a tiempo — número grande */}
              <div>
                <div className="text-4xl font-semibold text-gray-900 leading-none">
                  {comp.pct_a_tiempo}<span className="text-xl text-gray-400">%</span>
                </div>
                <div className="text-[11px] text-gray-500 mt-1">pagos a tiempo</div>
              </div>
              {/* Separator */}
              <div className="hidden sm:block w-px h-12 bg-gray-100" />
              {/* Stats + dots */}
              <div className="flex-1 space-y-2">
                <div className="text-xs text-gray-500">
                  Promedio atraso <span className="text-gray-900 font-medium">{comp.promedio_atraso}</span> días
                </div>
                <div className={`text-xs ${comp.racha_tipo === 'a_tiempo' ? 'text-emerald-700' : 'text-red-600'}`}>
                  {comp.racha} {comp.racha_tipo === 'a_tiempo' ? 'pagos puntuales consecutivos' : 'cuotas con atraso'}
                </div>
                {/* Últimos 10 dots */}
                {comp.ultimos_estados.length > 0 && (
                  <div className="flex items-center gap-1.5 mt-2">
                    {comp.ultimos_estados.map((e, i) => (
                      <div key={i}
                        className={`h-2 w-2 rounded-full ${e === 'a_tiempo' ? 'bg-emerald-500' : 'bg-red-500'}`}
                        title={e === 'a_tiempo' ? 'A tiempo' : 'Con atraso'}
                      />
                    ))}
                    <span className="text-[10px] text-gray-400 ml-2">últimos {comp.ultimos_estados.length}</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </Section>

        {/* Historial de pagos */}
        <Section title="Historial de pagos">
          {historial.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-4">Sin pagos registrados</p>
          ) : (
            <div className="max-h-72 overflow-y-auto -mx-1">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[10px] text-gray-400 uppercase tracking-wider border-b border-gray-100">
                    <th className="text-left px-3 py-2 font-medium">Fecha</th>
                    <th className="text-left px-3 py-2 font-medium hidden sm:table-cell">Crédito</th>
                    <th className="text-center px-3 py-2 font-medium">#</th>
                    <th className="text-right px-3 py-2 font-medium">Valor</th>
                    <th className="text-left px-3 py-2 font-medium hidden sm:table-cell">Método</th>
                  </tr>
                </thead>
                <tbody>
                  {historial.map((p, i) => (
                    <tr key={i} className="border-b border-gray-50 last:border-b-0">
                      <td className="px-3 py-2.5 text-gray-900">{formatDate(p.fecha_pago)}</td>
                      <td className="px-3 py-2.5 font-mono text-[10px] text-gray-400 hidden sm:table-cell">{p.loanbook_id}</td>
                      <td className="px-3 py-2.5 text-center text-gray-900">{p.cuota_numero}</td>
                      <td className="px-3 py-2.5 text-right text-gray-900">{formatCOP(p.monto)}</td>
                      <td className="px-3 py-2.5 text-gray-500 hidden sm:table-cell">{p.metodo_pago || '—'}</td>
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
