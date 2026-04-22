import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { apiGet, apiPatch } from '@/lib/api'
import LoanActionPanel from '@/components/LoanActionPanel'

interface LoanDetailPageProps {
  /** If provided, overrides useParams id. Used when rendered inside a drawer. */
  idProp?: string
  /** If provided, renders an X button instead of back-to-list. */
  onClose?: () => void
}

// ═══════════════════════════════════════════
// Types
// ═══════════════════════════════════════════

interface Cuota {
  numero: number
  monto: number
  estado: string
  fecha: string | null
  fecha_pago: string | null
  mora_acumulada: number
  timeline_status?: string
}

interface Cliente {
  nombre: string
  cedula: string
  telefono?: string
  telefono_alternativo?: string | null
}

interface Moto {
  modelo?: string
  vin?: string | null
  motor?: string | null
}

interface Plan {
  codigo?: string
  modalidad?: string
  cuota_valor?: number
  cuota_inicial?: number
  total_cuotas?: number
}

interface Fechas {
  factura?: string
  entrega?: string
  primera_cuota?: string
}

interface Loanbook {
  loanbook_id: string
  tipo_producto?: string
  cliente: Cliente
  moto?: Moto | null
  plan?: Plan
  fechas?: Fechas
  cuotas: Cuota[]
  estado: string
  valor_total?: number
  saldo_pendiente?: number
  saldo_capital?: number
  vin?: string | null
  modelo?: string
  modalidad?: string
  plan_codigo?: string
  cuota_monto?: number
  num_cuotas?: number
  total_pagado?: number
  total_mora_pagada?: number
  total_anzi_pagado?: number
  anzi_pct?: number
  alegra_factura_id?: string | null
  cuotas_pagadas?: number
  cuotas_total?: number
  dpd?: number
  proxima_cuota?: { fecha: string; monto: number } | null
  fecha_entrega?: string
  fecha_primer_pago?: string | null
  score_bucket?: string
  score?: number
}

// ═══════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════

const MORA_TASA = 2000 // COP/dia

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

function estadoBadge(estado: string) {
  const map: Record<string, string> = {
    activo: 'bg-emerald-500/15 text-emerald-700',
    al_dia: 'bg-emerald-500/15 text-emerald-700',
    mora: 'bg-red-500/15 text-red-700',
    mora_grave: 'bg-red-600/20 text-red-800',
    en_riesgo: 'bg-amber-500/15 text-amber-700',
    saldado: 'bg-neutral-400/20 text-neutral-600',
    pendiente_entrega: 'bg-orange-500/15 text-orange-700',
    reestructurado: 'bg-purple-500/15 text-purple-700',
    castigado: 'bg-neutral-500/20 text-neutral-700',
  }
  return map[estado] || 'bg-neutral-400/15 text-neutral-600'
}

function estadoLabel(estado: string) {
  const map: Record<string, string> = {
    activo: 'Activo', al_dia: 'Al día', mora: 'Mora', mora_grave: 'Mora grave',
    en_riesgo: 'En riesgo', saldado: 'Saldado', pendiente_entrega: 'Pend. entrega',
    reestructurado: 'Reestructurado', castigado: 'Castigado',
  }
  return map[estado] || estado
}

function tipoBadge(tipo: string | undefined) {
  const t = (tipo || 'moto').toLowerCase()
  const map: Record<string, string> = {
    moto: 'bg-neutral-200 text-neutral-700',
    comparendo: 'bg-blue-500/15 text-blue-700',
    licencia: 'bg-purple-500/15 text-purple-700',
  }
  return map[t] || 'bg-neutral-200 text-neutral-700'
}

function scoreBadge(bucket: string | undefined) {
  if (!bucket) return null
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

function cleanPhone(p: string | undefined | null) {
  if (!p) return ''
  return p.replace(/[^\d]/g, '')
}

// ═══════════════════════════════════════════
// Small UI components
// ═══════════════════════════════════════════

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white rounded-xl shadow-sm px-4 py-4 sm:px-5 sm:py-5">
      <h2 className="font-display font-bold text-on-surface text-sm mb-3 uppercase tracking-wider">{title}</h2>
      {children}
    </section>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between items-start gap-3 py-1.5 text-sm">
      <span className="text-on-surface-variant shrink-0">{label}</span>
      <span className="text-on-surface font-medium text-right break-all">{value}</span>
    </div>
  )
}

// ═══════════════════════════════════════════
// Main Page
// ═══════════════════════════════════════════

export default function LoanDetailPage({ idProp, onClose }: LoanDetailPageProps = {}) {
  const params = useParams<{ id: string }>()
  const navigate = useNavigate()
  const id = idProp ?? params.id
  const [lb, setLb] = useState<Loanbook | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Edit credito state
  const [editingCredito, setEditingCredito] = useState(false)
  const [creditoForm, setCreditoForm] = useState<Record<string, string | boolean>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  // Edit cuota state
  const [editingCuota, setEditingCuota] = useState<Cuota | null>(null)
  const [cuotaForm, setCuotaForm] = useState<Record<string, string>>({})
  const [savingCuota, setSavingCuota] = useState(false)
  const [saveCuotaError, setSaveCuotaError] = useState('')

  const loadLoanbook = useCallback(async () => {
    if (!id) return
    setLoading(true)
    try {
      const data = await apiGet<Loanbook>(`/loanbook/${id}`)
      setLb(data)
      setError('')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error cargando crédito')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    loadLoanbook()
  }, [loadLoanbook])

  function startEditCredito() {
    if (!lb) return
    setCreditoForm({
      plan_codigo: lb.plan?.codigo || lb.plan_codigo || '',
      modalidad: lb.plan?.modalidad || lb.modalidad || '',
      cuota_valor: String(lb.plan?.cuota_valor ?? lb.cuota_monto ?? ''),
      total_cuotas: String(lb.plan?.total_cuotas ?? lb.num_cuotas ?? ''),
      fecha_factura: lb.fechas?.factura || '',
      fecha_entrega: lb.fechas?.entrega || lb.fecha_entrega || '',
      primera_cuota: lb.fechas?.primera_cuota || lb.fecha_primer_pago || '',
      vin: lb.moto?.vin || lb.vin || '',
      modelo: lb.moto?.modelo || lb.modelo || '',
      cliente_telefono: lb.cliente?.telefono || '',
      cliente_telefono_alternativo: lb.cliente?.telefono_alternativo || '',
    })
    setEditingCredito(true)
    setSaveError('')
  }

  async function handlePatchCredito(e: React.FormEvent) {
    e.preventDefault()
    if (!id) return
    const payload: Record<string, string | number | boolean> = {}
    const f = creditoForm
    if (f.plan_codigo !== undefined && f.plan_codigo !== '') payload.plan_codigo = f.plan_codigo as string
    if (f.modalidad !== undefined && f.modalidad !== '') payload.modalidad = f.modalidad as string
    if (f.cuota_valor !== undefined && f.cuota_valor !== '') payload.cuota_valor = parseFloat(f.cuota_valor as string)
    if (f.total_cuotas !== undefined && f.total_cuotas !== '') payload.total_cuotas = parseInt(f.total_cuotas as string, 10)
    if (f.fecha_factura !== undefined && f.fecha_factura !== '') payload.fecha_factura = f.fecha_factura as string
    if (f.fecha_entrega !== undefined && f.fecha_entrega !== '') payload.fecha_entrega = f.fecha_entrega as string
    if (f.primera_cuota !== undefined && f.primera_cuota !== '') payload.primera_cuota = f.primera_cuota as string
    if (f.vin !== undefined && f.vin !== '') payload.vin = f.vin as string
    if (f.modelo !== undefined && f.modelo !== '') payload.modelo = f.modelo as string
    if (f.cliente_telefono !== undefined && f.cliente_telefono !== '') payload.cliente_telefono = f.cliente_telefono as string
    if (f.cliente_telefono_alternativo !== undefined) payload.cliente_telefono_alternativo = f.cliente_telefono_alternativo as string

    if (Object.keys(payload).length === 0) {
      setEditingCredito(false)
      return
    }
    setSaving(true)
    setSaveError('')
    try {
      await apiPatch(`/loanbook/${id}`, payload)
      await loadLoanbook()
      setEditingCredito(false)
      setCreditoForm({})
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : 'Error al guardar')
    } finally {
      setSaving(false)
    }
  }

  function startEditCuota(c: Cuota) {
    setCuotaForm({
      estado: c.estado || '',
      fecha_pago: c.fecha_pago || '',
      referencia: '',
      valor: String(c.monto ?? ''),
      fecha: c.fecha || '',
    })
    setSaveCuotaError('')
    setEditingCuota(c)
  }

  async function handlePatchCuota(e: React.FormEvent) {
    e.preventDefault()
    if (!id || !editingCuota) return
    const payload: Record<string, string | number> = {}
    const f = cuotaForm
    if (f.estado) payload.estado = f.estado
    if (f.fecha_pago) payload.fecha_pago = f.fecha_pago
    if (f.referencia) payload.referencia = f.referencia
    if (f.valor) payload.valor = parseFloat(f.valor)
    if (f.fecha) payload.fecha = f.fecha
    if (Object.keys(payload).length === 0) { setEditingCuota(null); return }
    setSavingCuota(true)
    setSaveCuotaError('')
    try {
      await apiPatch(`/loanbook/${id}/cuotas/${editingCuota.numero}`, payload)
      await loadLoanbook()
      setEditingCuota(null)
    } catch (e: unknown) {
      setSaveCuotaError(e instanceof Error ? e.message : 'Error al guardar')
    } finally {
      setSavingCuota(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full bg-surface">
        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (error || !lb) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-surface p-6 text-center">
        <p className="text-sm text-red-600 mb-3">{error || 'Crédito no encontrado'}</p>
        <button onClick={() => (onClose ? onClose() : navigate('/loanbook'))}
          className="px-4 py-2 rounded-md bg-primary text-white text-sm font-medium">
          {onClose ? 'Cerrar' : '← Volver a Créditos'}
        </button>
      </div>
    )
  }

  const tipo = (lb.tipo_producto || 'moto').toLowerCase()
  const esMoto = tipo === 'moto'
  const cuotas = lb.cuotas || []
  const pagadas = cuotas.filter(c => c.estado === 'pagada').length
  const vencidas = cuotas.filter(c => c.timeline_status === 'vencida').length
  const totalCuotas = cuotas.length
  const saldo = lb.saldo_pendiente ?? lb.saldo_capital ?? 0
  const valorTotal = lb.valor_total ?? (lb.num_cuotas ?? 0) * (lb.cuota_monto ?? 0)
  const totalPagado = lb.total_pagado ?? (valorTotal - saldo)
  const cuotaMonto = lb.cuota_monto ?? lb.plan?.cuota_valor ?? 0
  const anziPct = lb.anzi_pct ?? 0.02

  // Mora acumulada $ = sum(dias_atraso × $2000) de cuotas no pagadas con fecha vencida
  const today = new Date()
  today.setHours(12, 0, 0, 0)
  let moraAcumTotal = 0
  for (const c of cuotas) {
    if (c.estado === 'pagada' || !c.fecha) continue
    const fc = new Date(c.fecha + 'T12:00:00')
    const dias = Math.floor((today.getTime() - fc.getTime()) / (1000 * 60 * 60 * 24))
    if (dias > 0) moraAcumTotal += dias * MORA_TASA
  }

  // Waterfall de un pago típico (cuota del miércoles)
  const ejemploPago = cuotaMonto
  const wfAnzi = Math.round(ejemploPago * anziPct)
  const wfMora = Math.min(ejemploPago - wfAnzi, moraAcumTotal)
  const wfVencidas = Math.min(
    ejemploPago - wfAnzi - wfMora,
    vencidas * cuotaMonto
  )
  const wfCorriente = Math.max(0, ejemploPago - wfAnzi - wfMora - wfVencidas)
  const wfCapital = 0 // Solo hay abono a capital cuando pago > cuota + mora + vencidas
  const wfTotal = Math.max(1, wfAnzi + wfMora + wfVencidas + wfCorriente + wfCapital)

  const tel = lb.cliente?.telefono
  const telAlt = lb.cliente?.telefono_alternativo
  const telClean = cleanPhone(tel)

  const pagadasList = cuotas.filter(c => c.estado === 'pagada')

  return (
    <>
    <div className="flex flex-col h-full bg-surface overflow-y-auto">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-surface/95 backdrop-blur-sm px-4 py-3 sm:px-6">
        {onClose ? (
          <button onClick={onClose}
            className="text-xs text-on-surface-variant hover:text-on-surface mb-2 flex items-center gap-1">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
            Cerrar
          </button>
        ) : (
          <button onClick={() => navigate('/loanbook')}
            className="text-xs text-on-surface-variant hover:text-on-surface mb-2 flex items-center gap-1">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
            </svg>
            Volver a Créditos
          </button>
        )}
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <h1 className="font-display text-lg sm:text-xl font-bold text-on-surface break-words">
              {lb.cliente?.nombre || '—'}
            </h1>
            <p className="text-xs text-on-surface-variant mt-0.5">{lb.loanbook_id}</p>
          </div>
          <div className="flex gap-2 flex-wrap">
            <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider ${tipoBadge(lb.tipo_producto)}`}>
              {(lb.tipo_producto || 'moto').toUpperCase()}
            </span>
            <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold ${estadoBadge(lb.estado)}`}>
              {estadoLabel(lb.estado)}
            </span>
            {lb.score_bucket && (
              <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold ${scoreBadge(lb.score_bucket)}`}>
                {lb.score_bucket}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 px-4 sm:px-6 pb-6 space-y-3">

        {/* ACCIONES OPERACIONALES (Bloque 2) */}
        <Section title="Operaciones">
          <LoanActionPanel
            loanbookId={lb.loanbook_id}
            estado={lb.estado}
            tipoProducto={tipo}
            cuotaMonto={cuotaMonto}
            cuotaInicial={lb.plan?.cuota_inicial ?? 0}
            proximaCuota={lb.proxima_cuota ?? null}
            numProximaCuota={
              (lb.cuotas || []).find(c => c.estado !== 'pagada')?.numero ?? null
            }
            onSuccess={loadLoanbook}
          />
        </Section>

        {/* SECCION 1: CLIENTE */}
        <Section title="Cliente">
          <Row label="Cédula" value={<span className="font-mono text-xs">{lb.cliente?.cedula || '—'}</span>} />
          <Row label="Teléfono" value={
            tel ? (
              <a href={`tel:+${telClean}`} className="text-primary underline-offset-2 hover:underline font-mono text-xs">
                {tel}
              </a>
            ) : '—'
          } />
          {telAlt && (
            <Row label="Alternativo" value={
              <a href={`tel:+${cleanPhone(telAlt)}`} className="text-primary underline-offset-2 hover:underline font-mono text-xs">
                {telAlt}
              </a>
            } />
          )}
          {tel && (
            <div className="mt-3 flex gap-2">
              <a href={`https://wa.me/${telClean}`} target="_blank" rel="noopener noreferrer"
                className="flex-1 inline-flex items-center justify-center gap-2 px-3 py-2 rounded-md bg-emerald-500 text-white text-xs font-medium hover:bg-emerald-600 transition-colors">
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z"/></svg>
                WhatsApp
              </a>
              <a href={`tel:+${telClean}`}
                className="flex-1 inline-flex items-center justify-center gap-2 px-3 py-2 rounded-md bg-primary text-white text-xs font-medium hover:bg-primary/90 transition-colors">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 6.75c0 8.284 6.716 15 15 15h2.25a2.25 2.25 0 002.25-2.25v-1.372c0-.516-.351-.966-.852-1.091l-4.423-1.106c-.44-.11-.902.055-1.173.417l-.97 1.293c-.282.376-.769.542-1.21.38a12.035 12.035 0 01-7.143-7.143c-.162-.441.004-.928.38-1.21l1.293-.97c.363-.271.527-.734.417-1.173L6.963 3.102a1.125 1.125 0 00-1.091-.852H4.5A2.25 2.25 0 002.25 4.5v2.25z" />
                </svg>
                Llamar
              </a>
            </div>
          )}
        </Section>

        {/* SECCION 2: PRODUCTO */}
        <Section title="Producto">
          {esMoto ? (
            <>
              <Row label="Modelo" value={lb.moto?.modelo || lb.modelo || '—'} />
              <Row label="VIN" value={<span className="font-mono text-[11px] break-all">{lb.moto?.vin || lb.vin || '—'}</span>} />
              <Row label="Motor" value={<span className="font-mono text-[11px] break-all">{lb.moto?.motor || '—'}</span>} />
            </>
          ) : (
            <>
              <Row label="Tipo" value={(lb.tipo_producto || 'servicio').toUpperCase()} />
              <Row label="Modelo" value={lb.moto?.modelo || lb.modelo || '—'} />
              <p className="text-[11px] text-on-surface-variant italic mt-2">Sin VIN — financiación de servicio</p>
            </>
          )}
        </Section>

        {/* SECCION 3: CREDITO */}
        <section className="bg-white rounded-xl shadow-sm px-4 py-4 sm:px-5 sm:py-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display font-bold text-on-surface text-sm uppercase tracking-wider">Datos del crédito</h2>
            {!editingCredito ? (
              <button
                onClick={startEditCredito}
                className="flex items-center gap-1 text-xs text-primary hover:opacity-75 transition-opacity"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
                </svg>
                Editar
              </button>
            ) : (
              <button
                onClick={() => { setEditingCredito(false); setCreditoForm({}); setSaveError('') }}
                className="text-xs text-on-surface-variant hover:opacity-75 transition-opacity"
              >
                Cancelar
              </button>
            )}
          </div>

          {editingCredito ? (
            <form onSubmit={handlePatchCredito} className="space-y-3">
              {([
                { label: 'Plan', field: 'plan_codigo', type: 'text' },
                { label: 'Modalidad', field: 'modalidad', type: 'select', options: ['semanal', 'quincenal', 'mensual'] },
                { label: 'Valor cuota', field: 'cuota_valor', type: 'number' },
                { label: 'Total cuotas', field: 'total_cuotas', type: 'number' },
                { label: 'Fecha factura', field: 'fecha_factura', type: 'date' },
                { label: 'Fecha entrega', field: 'fecha_entrega', type: 'date' },
                { label: 'Primera cuota', field: 'primera_cuota', type: 'date' },
                { label: 'VIN', field: 'vin', type: 'text' },
                { label: 'Modelo', field: 'modelo', type: 'text' },
                { label: 'Teléfono cliente', field: 'cliente_telefono', type: 'text' },
                { label: 'Tel. alternativo', field: 'cliente_telefono_alternativo', type: 'text' },
              ] as Array<{ label: string; field: string; type: string; options?: string[] }>).map(({ label, field, type, options }) => (
                <div key={field}>
                  <label className="block text-[11px] text-on-surface-variant mb-0.5">{label}</label>
                  {type === 'select' ? (
                    <select
                      value={String(creditoForm[field] ?? '')}
                      onChange={e => setCreditoForm(f => ({ ...f, [field]: e.target.value }))}
                      className="w-full px-2 py-1.5 text-sm border border-surface-container-low rounded-md bg-white focus:outline-none focus:ring-1 focus:ring-primary"
                    >
                      <option value="">— sin cambio —</option>
                      {options!.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : (
                    <input
                      type={type}
                      value={String(creditoForm[field] ?? '')}
                      onChange={e => setCreditoForm(f => ({ ...f, [field]: e.target.value }))}
                      className="w-full px-2 py-1.5 text-sm border border-surface-container-low rounded-md bg-white focus:outline-none focus:ring-1 focus:ring-primary font-mono"
                    />
                  )}
                </div>
              ))}
              {saveError && (
                <p className="text-xs text-red-600 bg-red-50 rounded-md px-3 py-2">{saveError}</p>
              )}
              <button
                type="submit"
                disabled={saving}
                className="w-full py-2 bg-primary text-white rounded-md text-sm font-medium disabled:opacity-50 transition-opacity"
              >
                {saving ? 'Guardando...' : 'Guardar cambios'}
              </button>
            </form>
          ) : (
            <>
              <Row label="Plan" value={lb.plan?.codigo || lb.plan_codigo || '—'} />
              <Row label="Modalidad" value={lb.plan?.modalidad || lb.modalidad || '—'} />
              <Row label="Valor cuota" value={formatCOP(cuotaMonto)} />
              <Row label="Cuota inicial pagada" value={formatCOP(lb.plan?.cuota_inicial)} />
              <Row label="Fecha factura" value={formatDate(lb.fechas?.factura)} />
              <Row label="Fecha entrega" value={formatDate(lb.fechas?.entrega || lb.fecha_entrega)} />
              <Row label="Primera cuota" value={formatDate(lb.fechas?.primera_cuota || lb.fecha_primer_pago)} />
              <div className="border-t border-surface-container-low my-2"></div>
              <Row label="Valor total crédito" value={formatCOP(valorTotal)} />
              <div className="flex justify-between items-baseline gap-3 py-2">
                <span className="text-on-surface-variant text-sm">Saldo pendiente</span>
                <span className="font-display text-xl font-bold text-on-surface">{formatCOP(saldo)}</span>
              </div>
              {lb.alegra_factura_id && (
                <Row label="Alegra factura" value={<span className="font-mono text-xs">{lb.alegra_factura_id}</span>} />
              )}
            </>
          )}
        </section>

        {/* SECCION 4: CARTERA */}
        <Section title="Resumen de cartera">
          <div className="mb-3">
            <div className="flex justify-between text-[11px] text-on-surface-variant mb-1">
              <span>{pagadas} pagadas / {vencidas} vencidas / {totalCuotas - pagadas - vencidas} pendientes</span>
              <span>{totalCuotas > 0 ? Math.round((pagadas / totalCuotas) * 100) : 0}%</span>
            </div>
            <div className="flex h-2 rounded-full overflow-hidden bg-surface-container-low">
              <div className="bg-emerald-500" style={{ width: `${totalCuotas > 0 ? (pagadas / totalCuotas) * 100 : 0}%` }} />
              <div className="bg-red-500" style={{ width: `${totalCuotas > 0 ? (vencidas / totalCuotas) * 100 : 0}%` }} />
            </div>
          </div>
          <Row label="DPD" value={
            <span className={lb.dpd && lb.dpd > 0 ? 'text-red-600 font-bold' : 'text-emerald-600 font-bold'}>
              {lb.dpd ?? 0} días
            </span>
          } />
          <Row label="Score" value={
            lb.score_bucket
              ? <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${scoreBadge(lb.score_bucket)}`}>{lb.score_bucket}</span>
              : <span className="text-on-surface-variant italic text-xs">Sin score aún</span>
          } />
          <Row label="Mora acumulada" value={
            <span className={moraAcumTotal > 0 ? 'text-red-600 font-bold' : 'text-on-surface-variant'}>
              {formatCOP(moraAcumTotal)}
            </span>
          } />
          <Row label="Total pagado" value={<span className="text-emerald-600 font-medium">{formatCOP(totalPagado)}</span>} />
          {lb.proxima_cuota && (
            <div className="mt-3 p-3 rounded-md bg-primary/5 border border-primary/20">
              <div className="text-[10px] text-primary font-bold uppercase tracking-wider">Próximo pago</div>
              <div className="flex justify-between items-baseline mt-1">
                <span className="text-sm text-on-surface">{formatDate(lb.proxima_cuota.fecha)}</span>
                <span className="font-display text-lg font-bold text-primary">{formatCOP(lb.proxima_cuota.monto)}</span>
              </div>
            </div>
          )}
        </Section>

        {/* SECCION 5: CRONOGRAMA */}
        <Section title="Cronograma de cuotas">
          <div className="max-h-80 overflow-y-auto -mx-1">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-white">
                <tr className="text-on-surface-variant border-b border-surface-container-low">
                  <th className="text-left px-2 py-2 font-medium">#</th>
                  <th className="text-left px-2 py-2 font-medium">Fecha</th>
                  <th className="text-right px-2 py-2 font-medium">Valor</th>
                  <th className="text-center px-2 py-2 font-medium">Estado</th>
                  <th className="text-right px-2 py-2 font-medium">Mora</th>
                  <th className="w-6"></th>
                </tr>
              </thead>
              <tbody>
                {cuotas.map(c => {
                  const status = c.timeline_status || c.estado
                  const rowClass =
                    status === 'pagada' ? 'bg-emerald-50'
                    : status === 'vencida' ? 'bg-red-50'
                    : status === 'proxima' ? 'bg-blue-50 border-l-2 border-blue-500'
                    : 'bg-white'
                  const emoji =
                    status === 'pagada' ? '✅'
                    : status === 'vencida' ? '🔴'
                    : status === 'proxima' ? '🔵'
                    : '⏳'
                  const fc = c.fecha ? new Date(c.fecha + 'T12:00:00') : null
                  const dias = fc ? Math.floor((today.getTime() - fc.getTime()) / (1000 * 60 * 60 * 24)) : 0
                  const mora = status === 'vencida' && dias > 0 ? dias * MORA_TASA : 0
                  return (
                    <tr key={c.numero} className={`${rowClass} border-b border-surface-container-low/50`}>
                      <td className="px-2 py-1.5 text-on-surface">{c.numero}</td>
                      <td className="px-2 py-1.5 text-on-surface-variant">{formatDate(c.fecha)}</td>
                      <td className="px-2 py-1.5 text-right text-on-surface">{formatCOP(c.monto)}</td>
                      <td className="px-2 py-1.5 text-center">{emoji}</td>
                      <td className="px-2 py-1.5 text-right">
                        {mora > 0 ? <span className="text-red-600 font-medium">{formatCOP(mora)}</span> : '—'}
                      </td>
                      <td className="px-1 py-1.5 text-center">
                        <button
                          onClick={() => startEditCuota(c)}
                          className="text-on-surface-variant hover:text-primary transition-colors"
                          title={`Editar cuota #${c.numero}`}
                        >
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
                          </svg>
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Section>

        {/* SECCION 6: WATERFALL */}
        <Section title="Waterfall de distribución (pago típico)">
          <p className="text-[11px] text-on-surface-variant mb-3">
            Con un pago de {formatCOP(ejemploPago)} (valor de cuota), así se distribuye:
          </p>
          <div className="space-y-2">
            {[
              { label: `1. ANZI ${(anziPct * 100).toFixed(1)}%`, value: wfAnzi, color: 'bg-purple-400' },
              { label: '2. Mora acumulada', value: wfMora, color: 'bg-red-400' },
              { label: '3. Cuotas vencidas', value: wfVencidas, color: 'bg-orange-400' },
              { label: '4. Cuota corriente', value: wfCorriente, color: 'bg-emerald-400' },
              { label: '5. Abono a capital', value: wfCapital, color: 'bg-blue-400' },
            ].map((w, i) => (
              <div key={i}>
                <div className="flex justify-between text-[11px] mb-1">
                  <span className="text-on-surface-variant">{w.label}</span>
                  <span className="font-medium text-on-surface">{formatCOP(w.value)}</span>
                </div>
                <div className="h-2 bg-surface-container-low rounded-full overflow-hidden">
                  <div className={`h-full ${w.color}`} style={{ width: `${(w.value / wfTotal) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* SECCION 7: GESTIONES */}
        <Section title="Timeline de gestiones">
          <div className="py-6 text-center">
            <svg className="w-8 h-8 mx-auto mb-2 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p className="text-sm text-on-surface-variant">Sin gestiones registradas</p>
            <p className="text-[11px] text-on-surface-variant/60 mt-1">Se activa con RADAR (Phase 8)</p>
          </div>
        </Section>

        {/* SECCION 8: HISTORIAL PAGOS */}
        <Section title="Historial de pagos">
          {pagadasList.length === 0 ? (
            <p className="text-xs text-on-surface-variant text-center py-4">Sin pagos registrados aún</p>
          ) : (
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-on-surface-variant border-b border-surface-container-low">
                    <th className="text-left px-2 py-2 font-medium">Fecha pago</th>
                    <th className="text-center px-2 py-2 font-medium">Cuota #</th>
                    <th className="text-right px-2 py-2 font-medium">Valor</th>
                    <th className="text-left px-2 py-2 font-medium">Método</th>
                  </tr>
                </thead>
                <tbody>
                  {pagadasList.map(c => (
                    <tr key={c.numero} className="border-b border-surface-container-low/50">
                      <td className="px-2 py-1.5 text-on-surface">{formatDate(c.fecha_pago)}</td>
                      <td className="px-2 py-1.5 text-center text-on-surface">{c.numero}</td>
                      <td className="px-2 py-1.5 text-right text-on-surface">{formatCOP(c.monto)}</td>
                      <td className="px-2 py-1.5 text-on-surface-variant">—</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>

      </div>
    </div>

    {/* ── Cuota edit modal ── */}

    {editingCuota && (
      <div
        className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/40 backdrop-blur-sm"
        onClick={(e) => { if (e.target === e.currentTarget) setEditingCuota(null) }}
      >
        <div className="w-full max-w-sm bg-white rounded-2xl shadow-2xl overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-surface-container-low">
            <h3 className="font-display font-bold text-sm text-on-surface">
              Editar cuota #{editingCuota.numero}
            </h3>
            <button
              onClick={() => setEditingCuota(null)}
              className="text-on-surface-variant hover:text-on-surface transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <p className="text-[11px] text-amber-700 bg-amber-50 px-5 py-2 border-b border-amber-100">
            Solo corrige metadatos. No afecta saldo capital.
          </p>
          <form onSubmit={handlePatchCuota} className="px-5 py-4 space-y-3">
            <div>
              <label className="block text-[11px] text-on-surface-variant mb-0.5">Estado</label>
              <select
                value={cuotaForm.estado ?? ''}
                onChange={e => setCuotaForm(f => ({ ...f, estado: e.target.value }))}
                className="w-full px-2 py-1.5 text-sm border border-surface-container-low rounded-md bg-white focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="">— sin cambio —</option>
                <option value="pendiente">pendiente</option>
                <option value="pagada">pagada</option>
                <option value="condonada">condonada</option>
              </select>
            </div>
            {([
              { label: 'Fecha pago', field: 'fecha_pago', type: 'date' },
              { label: 'Referencia', field: 'referencia', type: 'text' },
              { label: 'Valor cuota (sobreescribe)', field: 'valor', type: 'number' },
              { label: 'Fecha cuota (reprogramar)', field: 'fecha', type: 'date' },
            ] as Array<{ label: string; field: string; type: string }>).map(({ label, field, type }) => (
              <div key={field}>
                <label className="block text-[11px] text-on-surface-variant mb-0.5">{label}</label>
                <input
                  type={type}
                  value={cuotaForm[field] ?? ''}
                  onChange={e => setCuotaForm(f => ({ ...f, [field]: e.target.value }))}
                  className="w-full px-2 py-1.5 text-sm border border-surface-container-low rounded-md bg-white focus:outline-none focus:ring-1 focus:ring-primary font-mono"
                />
              </div>
            ))}
            {saveCuotaError && (
              <p className="text-xs text-red-600 bg-red-50 rounded-md px-3 py-2">{saveCuotaError}</p>
            )}
            <button
              type="submit"
              disabled={savingCuota}
              className="w-full py-2 bg-primary text-white rounded-md text-sm font-medium disabled:opacity-50 transition-opacity"
            >
              {savingCuota ? 'Guardando...' : 'Guardar cambios'}
            </button>
          </form>
        </div>
      </div>
    )}
    </>
  )
}
