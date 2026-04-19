import { useState, useEffect, useCallback } from 'react'
import { apiGet, apiPost, apiPatch } from '@/lib/api'

// ═══════════════════════════════════════════
// Plan Separe — Commercial module for advances
// ═══════════════════════════════════════════

interface Abono {
  abono_id?: string
  fecha: string
  monto: number
  banco: string
  banco_label?: string
  referencia?: string | null
  registrado_por?: string | null
  alegra_journal_id?: string | null
  timestamp?: string
}

interface Cliente {
  cc: string
  tipo_documento?: string
  nombre: string
  telefono?: string
}

interface Moto {
  modelo: string
  precio_venta?: number
  cuota_inicial_requerida: number
}

interface Separacion {
  separacion_id: string
  cliente: Cliente
  moto: Moto
  abonos: Abono[]
  total_abonado: number
  saldo_pendiente: number
  porcentaje_pagado: number
  matricula_provision: number
  estado: 'activa' | 'completada' | 'facturada' | 'cancelada'
  fecha_creacion: string
  fecha_100porciento?: string | null
  alegra_invoice_id?: string | null
  notas?: string | null
}

const BANCOS = [
  { value: 'bancolombia_2029', label: 'Bancolombia 2029' },
  { value: 'bancolombia_2540', label: 'Bancolombia 2540' },
  { value: 'bbva_0210', label: 'BBVA 0210' },
  { value: 'bbva_0212', label: 'BBVA 0212' },
  { value: 'davivienda_482', label: 'Davivienda 482' },
  { value: 'banco_bogota', label: 'Banco de Bogotá' },
  { value: 'global_66', label: 'Global 66' },
  { value: 'nequi', label: 'Nequi' },
  { value: 'efectivo', label: 'Efectivo' },
]

function formatCOP(n: number | undefined | null): string {
  if (n === undefined || n === null) return '—'
  return new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(n)
}

function formatDate(d: string | null | undefined): string {
  if (!d) return '—'
  try {
    return new Date(d + (d.length === 10 ? 'T12:00:00' : '')).toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric' })
  } catch { return d }
}

function estadoPill(estado: string) {
  const map: Record<string, string> = {
    activa: 'bg-amber-50 text-amber-800 border-amber-200',
    completada: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    facturada: 'bg-gray-100 text-gray-600 border-gray-200',
    cancelada: 'bg-red-50 text-red-600 border-red-200',
  }
  return map[estado] || 'bg-gray-100 text-gray-600 border-gray-200'
}

// ═══════════════════════════════════════════
// Nueva separación modal
// ═══════════════════════════════════════════

function NuevaSeparacionModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState({
    cliente_cc: '',
    cliente_nombre: '',
    cliente_telefono: '',
    cliente_tipo_documento: 'CC',
    moto_modelo: 'Raider 125',
    cuota_inicial: 1_460_000,
    moto_precio_venta: 0,
    notas: '',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    if (!form.cliente_cc || !form.cliente_nombre) {
      setError('Cédula y nombre son obligatorios')
      return
    }
    setLoading(true); setError('')
    try {
      await apiPost('/plan-separe/crear', form)
      onCreated()
      onClose()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setLoading(false) }
  }

  return (
    <div className="fixed inset-0 z-[60] bg-neutral-950/50 backdrop-blur-[2px] flex items-center justify-center p-4"
      onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-5" onClick={e => e.stopPropagation()}>
        <h3 className="font-display font-semibold text-gray-900 text-base mb-4">Nueva separación</h3>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] text-gray-400 uppercase tracking-wider">Tipo doc</label>
              <select value={form.cliente_tipo_documento}
                onChange={e => setForm({ ...form, cliente_tipo_documento: e.target.value })}
                className="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-100">
                <option value="CC">CC</option>
                <option value="PPT">PPT</option>
                <option value="PEP">PEP</option>
                <option value="CE">CE</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] text-gray-400 uppercase tracking-wider">Número</label>
              <input type="text" placeholder="123456789"
                value={form.cliente_cc} onChange={e => setForm({ ...form, cliente_cc: e.target.value })}
                className="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-100" />
            </div>
          </div>
          <div>
            <label className="text-[10px] text-gray-400 uppercase tracking-wider">Nombre cliente</label>
            <input type="text" placeholder="Juan Pérez"
              value={form.cliente_nombre} onChange={e => setForm({ ...form, cliente_nombre: e.target.value })}
              className="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-100" />
          </div>
          <div>
            <label className="text-[10px] text-gray-400 uppercase tracking-wider">Teléfono</label>
            <input type="text" placeholder="3001234567"
              value={form.cliente_telefono} onChange={e => setForm({ ...form, cliente_telefono: e.target.value })}
              className="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-100" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] text-gray-400 uppercase tracking-wider">Moto</label>
              <input type="text" value={form.moto_modelo}
                onChange={e => setForm({ ...form, moto_modelo: e.target.value })}
                className="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-100" />
            </div>
            <div>
              <label className="text-[10px] text-gray-400 uppercase tracking-wider">Cuota inicial</label>
              <input type="number" value={form.cuota_inicial}
                onChange={e => setForm({ ...form, cuota_inicial: Number(e.target.value) })}
                className="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-100" />
            </div>
          </div>
          <div>
            <label className="text-[10px] text-gray-400 uppercase tracking-wider">Notas</label>
            <input type="text" value={form.notas}
              onChange={e => setForm({ ...form, notas: e.target.value })}
              className="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-100" />
          </div>
        </div>
        {error && <p className="text-xs text-red-600 mt-3">{error}</p>}
        <div className="flex gap-2 mt-5">
          <button onClick={onClose} disabled={loading}
            className="flex-1 px-3 py-2 rounded-md bg-gray-100 text-gray-700 text-sm hover:bg-gray-200">Cancelar</button>
          <button onClick={submit} disabled={loading}
            className="flex-1 px-3 py-2 rounded-md bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-50">
            {loading ? 'Creando...' : 'Crear separación'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════
// Registrar abono modal
// ═══════════════════════════════════════════

function RegistrarAbonoModal({
  separacionId, saldoPendiente, onClose, onSuccess,
}: {
  separacionId: string
  saldoPendiente: number
  onClose: () => void
  onSuccess: () => void
}) {
  const [form, setForm] = useState({
    monto: saldoPendiente,
    fecha: new Date().toISOString().slice(0, 10),
    banco: 'bancolombia_2029',
    referencia: '',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    if (form.monto <= 0) { setError('Monto debe ser > 0'); return }
    if (form.monto > saldoPendiente + 0.01) { setError(`Excede saldo (${formatCOP(saldoPendiente)})`); return }
    setLoading(true); setError('')
    try {
      await apiPost(`/plan-separe/${separacionId}/abono`, form)
      onSuccess()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setLoading(false) }
  }

  return (
    <div className="fixed inset-0 z-[60] bg-neutral-950/50 backdrop-blur-[2px] flex items-center justify-center p-4"
      onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-5" onClick={e => e.stopPropagation()}>
        <h3 className="font-display font-semibold text-gray-900 text-base mb-1">Registrar abono</h3>
        <p className="text-xs text-gray-500 mb-4">Saldo pendiente: <span className="font-semibold text-gray-900">{formatCOP(saldoPendiente)}</span></p>
        <div className="space-y-3">
          <div>
            <label className="text-[10px] text-gray-400 uppercase tracking-wider">Monto</label>
            <input type="number" value={form.monto}
              onChange={e => setForm({ ...form, monto: Number(e.target.value) })}
              className="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-100" />
          </div>
          <div>
            <label className="text-[10px] text-gray-400 uppercase tracking-wider">Fecha</label>
            <input type="date" value={form.fecha}
              onChange={e => setForm({ ...form, fecha: e.target.value })}
              className="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-100" />
          </div>
          <div>
            <label className="text-[10px] text-gray-400 uppercase tracking-wider">Banco</label>
            <select value={form.banco}
              onChange={e => setForm({ ...form, banco: e.target.value })}
              className="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-100">
              {BANCOS.map(b => <option key={b.value} value={b.value}>{b.label}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[10px] text-gray-400 uppercase tracking-wider">Referencia</label>
            <input type="text" placeholder="Comprobante..."
              value={form.referencia} onChange={e => setForm({ ...form, referencia: e.target.value })}
              className="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-100" />
          </div>
        </div>
        {error && <p className="text-xs text-red-600 mt-3">{error}</p>}
        <div className="flex gap-2 mt-5">
          <button onClick={onClose} disabled={loading}
            className="flex-1 px-3 py-2 rounded-md bg-gray-100 text-gray-700 text-sm hover:bg-gray-200">Cancelar</button>
          <button onClick={submit} disabled={loading}
            className="flex-1 px-3 py-2 rounded-md bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-50">
            {loading ? 'Procesando...' : 'Registrar'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════
// Notificar contador modal
// ═══════════════════════════════════════════

function NotificarContadorModal({ separacion, onClose, onDone }: { separacion: Separacion; onClose: () => void; onDone: () => void }) {
  const [loading, setLoading] = useState(false)
  const [copiado, setCopiado] = useState(false)
  const [instruccion, setInstruccion] = useState('')

  async function notificar() {
    setLoading(true)
    try {
      const res = await apiPost<{ instruccion_contador: string }>(`/plan-separe/${separacion.separacion_id}/notificar-contador`, {})
      setInstruccion(res.instruccion_contador)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  async function copiar() {
    try {
      await navigator.clipboard.writeText(instruccion)
      setCopiado(true)
      setTimeout(() => setCopiado(false), 2000)
    } catch { /* ignore */ }
  }

  useEffect(() => { notificar() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="fixed inset-0 z-[60] bg-neutral-950/50 backdrop-blur-[2px] flex items-center justify-center p-4"
      onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-5" onClick={e => e.stopPropagation()}>
        <h3 className="font-display font-semibold text-gray-900 text-base mb-1">Notificar al Contador</h3>
        <p className="text-xs text-gray-500 mb-4">Cliente pagó 100%. Copia la instrucción para avisar al Contador.</p>
        {loading ? (
          <div className="flex items-center justify-center py-6">
            <div className="w-5 h-5 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <>
            <div className="bg-gray-50 border border-gray-100 rounded-md p-3 mb-3">
              <code className="text-xs text-gray-800 break-all">{instruccion}</code>
            </div>
            <button onClick={copiar}
              className={`w-full px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                copiado ? 'bg-emerald-100 text-emerald-800' : 'bg-emerald-600 text-white hover:bg-emerald-700'
              }`}>
              {copiado ? '✓ Copiado' : 'Copiar instrucción'}
            </button>
            <button onClick={() => { onDone(); onClose() }}
              className="w-full mt-2 px-3 py-2 rounded-md bg-gray-100 text-gray-700 text-sm hover:bg-gray-200">
              Cerrar
            </button>
          </>
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════
// Panel detalle (drawer)
// ═══════════════════════════════════════════

function DetallePanel({ sep, onClose, onUpdated, toast }: {
  sep: Separacion
  onClose: () => void
  onUpdated: () => void
  toast: (kind: 'success' | 'error' | 'warning', msg: string) => void
}) {
  const [showAbono, setShowAbono] = useState(false)
  const [showNotificar, setShowNotificar] = useState(false)
  const [showEditar, setShowEditar] = useState(false)
  const tel = sep.cliente.telefono?.replace(/[^\d]/g, '') || ''
  const pct = sep.porcentaje_pagado
  const completa = sep.estado === 'completada'
  const puedeAbonar = sep.estado === 'activa' || sep.estado === 'completada'
  const esFacturada = sep.estado === 'facturada'

  return (
    <>
      <div className="fixed inset-0 z-40 bg-neutral-950/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="fixed right-0 top-0 h-screen w-full sm:w-[480px] bg-white shadow-2xl z-50 overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-gray-100 p-5 flex items-start justify-between">
          <div>
            <div className="text-[10px] text-gray-400 uppercase tracking-wider">{sep.separacion_id}</div>
            <h2 className="text-lg font-semibold text-gray-900 mt-1">{sep.cliente.nombre}</h2>
            <p className="text-xs text-gray-500 mt-0.5">{sep.cliente.tipo_documento || 'CC'} {sep.cliente.cc} · {sep.moto.modelo}</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 flex items-center justify-center rounded-full text-gray-400 hover:text-gray-700 hover:bg-gray-100">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/* Estado + progreso */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className={`px-2.5 py-1 rounded-full text-[11px] font-medium border ${estadoPill(sep.estado)}`}>
                {sep.estado}
              </span>
              <span className="text-xs font-semibold text-gray-900">{pct}%</span>
            </div>
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
              <div className={`h-full ${completa ? 'bg-emerald-500' : 'bg-amber-400'}`} style={{ width: `${Math.min(pct, 100)}%` }} />
            </div>
            <div className="flex justify-between mt-2 text-xs">
              <div>
                <div className="text-gray-400">Pagado</div>
                <div className="font-semibold text-gray-900">{formatCOP(sep.total_abonado)}</div>
              </div>
              <div className="text-right">
                <div className="text-gray-400">Falta</div>
                <div className="font-semibold text-gray-900">{formatCOP(sep.saldo_pendiente)}</div>
              </div>
            </div>
          </div>

          {/* Teléfono */}
          {tel && (
            <div className="flex gap-2">
              <a href={`tel:+${tel}`}
                className="flex-1 text-center px-3 py-1.5 rounded-full bg-gray-50 text-gray-700 border border-gray-200 text-xs hover:bg-gray-100">
                Llamar
              </a>
              <a href={`https://wa.me/${tel}`} target="_blank" rel="noreferrer"
                className="flex-1 text-center px-3 py-1.5 rounded-full bg-green-50 text-green-700 border border-green-200 text-xs hover:bg-green-100">
                WhatsApp
              </a>
            </div>
          )}

          {/* Acciones */}
          <div className="space-y-2">
            {puedeAbonar && sep.saldo_pendiente > 0 && (
              <button onClick={() => setShowAbono(true)}
                className="w-full px-3 py-2 rounded-md bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700">
                + Registrar abono
              </button>
            )}
            {completa && (
              <button onClick={() => setShowNotificar(true)}
                className="w-full px-3 py-2 rounded-md bg-amber-500 text-white text-sm font-medium hover:bg-amber-600">
                Notificar Contador para facturar
              </button>
            )}
            <button
              onClick={() => !esFacturada && setShowEditar(true)}
              disabled={esFacturada}
              title={esFacturada ? 'Separación facturada, no editable' : 'Editar datos de la separación'}
              className={`w-full px-3 py-2 rounded-md text-sm font-medium border transition-colors ${
                esFacturada
                  ? 'bg-gray-50 text-gray-400 border-gray-200 cursor-not-allowed'
                  : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
              }`}>
              Editar
            </button>
          </div>

          {/* Historial de abonos */}
          <div>
            <h3 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Historial de abonos</h3>
            {sep.abonos.length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-4">Sin abonos registrados</p>
            ) : (
              <div className="divide-y divide-gray-50">
                {sep.abonos.map((a, i) => (
                  <div key={a.abono_id || i} className="py-2.5 flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-sm text-gray-900">{formatDate(a.fecha)}</div>
                      <div className="text-[11px] text-gray-500">{a.banco_label || a.banco}{a.referencia && ` · ref ${a.referencia}`}</div>
                      {a.alegra_journal_id && (
                        <div className="text-[10px] text-gray-400 font-mono mt-0.5">Alegra {a.alegra_journal_id}</div>
                      )}
                    </div>
                    <div className="text-sm font-semibold text-gray-900 shrink-0">{formatCOP(a.monto)}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Notas */}
          {sep.notas && (
            <div>
              <h3 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Notas</h3>
              <p className="text-sm text-gray-700">{sep.notas}</p>
            </div>
          )}
        </div>
      </div>

      {showAbono && (
        <RegistrarAbonoModal
          separacionId={sep.separacion_id}
          saldoPendiente={sep.saldo_pendiente}
          onClose={() => setShowAbono(false)}
          onSuccess={() => { setShowAbono(false); onUpdated() }}
        />
      )}
      {showNotificar && (
        <NotificarContadorModal
          separacion={sep}
          onClose={() => setShowNotificar(false)}
          onDone={onUpdated}
        />
      )}
      {showEditar && (
        <EditarSeparacionModal
          sep={sep}
          toast={toast}
          onClose={() => setShowEditar(false)}
          onSuccess={() => { setShowEditar(false); onUpdated() }}
        />
      )}
    </>
  )
}

// ═══════════════════════════════════════════
// Editar separacion modal — con diff visual + motivo
// ═══════════════════════════════════════════

interface EditarForm {
  cliente_nombre: string
  cliente_documento_tipo: string
  cliente_documento_numero: string
  cliente_telefono: string
  moto_modelo: string
  cuota_inicial_esperada: number
  notas: string
}

const TIPOS_DOC = ['CC', 'PPT', 'CE', 'TI']

function EditarSeparacionModal({
  sep, toast, onClose, onSuccess,
}: {
  sep: Separacion
  toast: (kind: 'success' | 'error' | 'warning', msg: string) => void
  onClose: () => void
  onSuccess: () => void
}) {
  const original: EditarForm = {
    cliente_nombre: sep.cliente.nombre || '',
    cliente_documento_tipo: (sep.cliente.tipo_documento || 'CC').toUpperCase(),
    cliente_documento_numero: sep.cliente.cc || '',
    cliente_telefono: sep.cliente.telefono || '',
    moto_modelo: sep.moto.modelo || '',
    cuota_inicial_esperada: sep.moto.cuota_inicial_requerida || 0,
    notas: sep.notas || '',
  }
  const [form, setForm] = useState<EditarForm>(original)
  const [motivo, setMotivo] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [showDiff, setShowDiff] = useState(false)

  const diffs = Object.entries(form)
    .filter(([k, v]) => (original as unknown as Record<string, unknown>)[k] !== v)
    .map(([k, v]) => ({
      campo: k,
      anterior: (original as unknown as Record<string, unknown>)[k],
      nuevo: v,
    }))

  const puedeGuardar =
    diffs.length > 0 &&
    form.cuota_inicial_esperada > 0

  // Human-readable hint for why the button is disabled
  const guardarHint =
    diffs.length === 0
      ? 'Modifica al menos un campo para habilitar'
      : form.cuota_inicial_esperada <= 0
      ? 'La cuota inicial debe ser mayor a 0'
      : null

  async function submit() {
    if (diffs.length === 0) { setError('No hay cambios que guardar'); return }
    setLoading(true); setError('')
    try {
      const payload: Record<string, unknown> = { motivo: motivo.trim() }
      for (const d of diffs) payload[d.campo] = d.nuevo
      await apiPatch(`/plan-separe/${sep.separacion_id}`, payload)
      toast('success', 'Separación actualizada')
      onSuccess()
    } catch (e: unknown) {
      const err = e as Error & { status?: number }
      if (err.status === 423) {
        toast('error', 'No se puede editar separación facturada')
      } else if (err.status === 422) {
        toast('warning', err.message || 'Datos inválidos')
      } else {
        toast('error', err.message || 'Error')
      }
      setError(err.message || 'Error')
    } finally { setLoading(false) }
  }

  const inputCls =
    'w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-100 focus:border-emerald-300'
  const labelCls = 'text-[10px] text-gray-400 uppercase tracking-wider'

  return (
    <div className="fixed inset-0 z-[60] bg-neutral-950/50 backdrop-blur-[2px] flex items-center justify-center p-4"
      onClick={() => !loading && onClose()}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg p-5 max-h-[90vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="font-display font-semibold text-gray-900 text-base">Editar separación</h3>
            <p className="text-[11px] text-gray-500 mt-0.5 font-mono">{sep.separacion_id}</p>
          </div>
          <button onClick={onClose} disabled={loading}
            className="w-7 h-7 flex items-center justify-center rounded-full text-gray-400 hover:text-gray-700 hover:bg-gray-100">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {!showDiff ? (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="sm:col-span-2">
                <label className={labelCls}>Nombre cliente</label>
                <input type="text" className={inputCls}
                  value={form.cliente_nombre}
                  onChange={e => setForm({ ...form, cliente_nombre: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>Tipo documento</label>
                <select className={inputCls}
                  value={form.cliente_documento_tipo}
                  onChange={e => setForm({ ...form, cliente_documento_tipo: e.target.value })}>
                  {TIPOS_DOC.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className={labelCls}>Número</label>
                <input type="text" className={inputCls}
                  value={form.cliente_documento_numero}
                  onChange={e => setForm({ ...form, cliente_documento_numero: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>Teléfono</label>
                <input type="text" className={inputCls}
                  value={form.cliente_telefono}
                  onChange={e => setForm({ ...form, cliente_telefono: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>Moto</label>
                <input type="text" className={inputCls}
                  value={form.moto_modelo}
                  onChange={e => setForm({ ...form, moto_modelo: e.target.value })} />
              </div>
              <div className="sm:col-span-2">
                <label className={labelCls}>Cuota inicial esperada (COP)</label>
                <input type="number" className={inputCls}
                  value={form.cuota_inicial_esperada}
                  onChange={e => setForm({ ...form, cuota_inicial_esperada: Number(e.target.value) })} />
              </div>
              <div className="sm:col-span-2">
                <label className={labelCls}>Notas</label>
                <textarea className={`${inputCls} min-h-[60px]`}
                  value={form.notas}
                  onChange={e => setForm({ ...form, notas: e.target.value })} />
              </div>
              <div className="sm:col-span-2">
                <label className={labelCls}>Motivo del cambio <span className="text-gray-400">(opcional)</span></label>
                <textarea className={`${inputCls} min-h-[60px]`}
                  placeholder="Razón del cambio — quedará en el historial de auditoría"
                  value={motivo}
                  onChange={e => setMotivo(e.target.value)} />
              </div>
            </div>

            {error && <p className="text-xs text-red-600 mt-3">{error}</p>}
            {guardarHint && (
              <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-100 rounded-md px-3 py-2 mt-3">
                {guardarHint}
              </p>
            )}

            <div className="flex gap-2 mt-4">
              <button onClick={onClose} disabled={loading}
                className="flex-1 px-3 py-2 rounded-md bg-gray-100 text-gray-700 text-sm hover:bg-gray-200">
                Cancelar
              </button>
              <button onClick={() => setShowDiff(true)}
                disabled={!puedeGuardar || loading}
                className="flex-1 px-3 py-2 rounded-md bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed">
                Revisar cambios {diffs.length > 0 ? `(${diffs.length})` : ''}
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="text-xs text-gray-500 mb-3">Revisa los cambios antes de guardar:</p>
            <div className="space-y-2 max-h-80 overflow-y-auto">
              {diffs.map(d => (
                <div key={d.campo} className="rounded-md border border-gray-100 p-3 bg-gray-50/40">
                  <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{d.campo}</div>
                  <div className="text-xs text-red-600 line-through break-words">
                    {String(d.anterior ?? '—')}
                  </div>
                  <div className="text-xs text-emerald-700 font-medium mt-1 break-words">
                    {String(d.nuevo ?? '—')}
                  </div>
                </div>
              ))}
              <div className="rounded-md border border-gray-100 p-3 bg-gray-50/40">
                <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Motivo</div>
                <div className="text-xs text-gray-700 italic">"{motivo}"</div>
              </div>
            </div>

            {error && <p className="text-xs text-red-600 mt-3">{error}</p>}

            <div className="flex gap-2 mt-5">
              <button onClick={() => setShowDiff(false)} disabled={loading}
                className="flex-1 px-3 py-2 rounded-md bg-gray-100 text-gray-700 text-sm hover:bg-gray-200">
                Volver
              </button>
              <button onClick={submit} disabled={loading}
                className="flex-1 px-3 py-2 rounded-md bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-50">
                {loading ? 'Guardando...' : 'Guardar cambios'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════
// Main Page
// ═══════════════════════════════════════════

const ESTADO_FILTERS = [
  { value: '', label: 'Todos' },
  { value: 'activa', label: 'Activas' },
  { value: 'completada', label: 'Completadas' },
  { value: 'facturada', label: 'Facturadas' },
  { value: 'cancelada', label: 'Canceladas' },
]

type ToastKind = 'success' | 'error' | 'warning'
interface ToastState { kind: ToastKind; msg: string }

interface PlanSepareStats {
  total_retenido: number
  dinero_pendiente: number
  matriculas_provision_proyectada: number
  por_estado: { activa: number; completada: number; facturada: number; cancelada: number }
  matricula_unit: number
}

const MATRICULA = 580_000

export default function PlanSeparePage() {
  const [items, setItems] = useState<Separacion[]>([])
  const [loading, setLoading] = useState(true)
  const [filtroEstado, setFiltroEstado] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [showNueva, setShowNueva] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [stats, setStats] = useState<PlanSepareStats | null>(null)

  const showToast = useCallback((kind: ToastKind, msg: string) => {
    setToast({ kind, msg })
    window.setTimeout(() => setToast(null), 4000)
  }, [])

  // Stats — siempre sobre el total, independiente del filtro
  useEffect(() => {
    apiGet<PlanSepareStats>('/plan-separe/stats').then(setStats).catch(() => {})
  }, [])

  const load = useCallback(async () => {
    try {
      const path = filtroEstado ? `/plan-separe?estado=${filtroEstado}` : '/plan-separe'
      const res = await apiGet<{ separaciones: Separacion[] }>(path)
      setItems(res.separaciones || [])
    } catch { /* ignore */ }
  }, [filtroEstado])

  useEffect(() => {
    setLoading(true)
    load().finally(() => setLoading(false))
  }, [load])

  const searchLower = search.toLowerCase().trim()
  const filtered = items.filter(it => {
    if (!searchLower) return true
    return it.cliente.cc.toLowerCase().includes(searchLower)
      || it.cliente.nombre.toLowerCase().includes(searchLower)
      || it.separacion_id.toLowerCase().includes(searchLower)
  })

  const selectedDoc = items.find(i => i.separacion_id === selected)

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-100 px-6 py-5 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 tracking-tight">Plan Separe</h1>
          <p className="text-sm text-gray-500 mt-0.5">Separaciones con abonos parciales (anticipos a clientes)</p>
        </div>
        <button onClick={() => setShowNueva(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-700">
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          Nueva separación
        </button>
      </div>

      {/* Stats cards */}
      <div className="bg-white border-b border-gray-100 px-6 py-4">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {/* Total recibido */}
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] text-gray-400 uppercase tracking-wider">Total recibido</span>
            {stats ? (
              <>
                <span className="text-2xl font-semibold text-emerald-700">{formatCOP(stats.total_retenido)}</span>
                <span className="text-[11px] text-gray-400">
                  {stats.por_estado.activa + stats.por_estado.completada} separaciones activas/completadas
                </span>
              </>
            ) : (
              <div className="h-7 w-32 bg-gray-100 rounded animate-pulse mt-0.5" />
            )}
          </div>
          {/* Pendiente por recibir */}
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] text-gray-400 uppercase tracking-wider">Pendiente por recibir</span>
            {stats ? (
              <>
                <span className="text-2xl font-semibold text-amber-600">{formatCOP(stats.dinero_pendiente)}</span>
                <span className="text-[11px] text-gray-400">
                  {stats.por_estado.activa} separaciones abiertas
                </span>
              </>
            ) : (
              <div className="h-7 w-32 bg-gray-100 rounded animate-pulse mt-0.5" />
            )}
          </div>
          {/* Caja para matrícula */}
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] text-gray-400 uppercase tracking-wider">Caja para matrícula</span>
            {stats ? (
              <>
                <span className="text-2xl font-semibold text-blue-700">{formatCOP(stats.matriculas_provision_proyectada)}</span>
                <span className="text-[11px] text-gray-400">
                  {formatCOP(MATRICULA)} × {stats.por_estado.activa + stats.por_estado.completada} motos
                </span>
              </>
            ) : (
              <div className="h-7 w-32 bg-gray-100 rounded animate-pulse mt-0.5" />
            )}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {/* Search + filters */}
        <div className="mb-4 flex flex-col sm:flex-row gap-3 sm:items-center">
          <div className="relative flex-1">
            <input
              type="search"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Buscar por CC o nombre..."
              className="w-full rounded-md border border-gray-200 bg-white pl-9 pr-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-100 focus:border-emerald-300"
            />
            <svg className="w-4 h-4 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 10.5a6.5 6.5 0 11-13 0 6.5 6.5 0 0113 0z" />
            </svg>
          </div>
          <div className="flex gap-1.5 flex-wrap">
            {ESTADO_FILTERS.map(f => (
              <button key={f.value} onClick={() => setFiltroEstado(f.value)}
                className={`px-2.5 py-1 rounded-full text-xs transition-colors ${
                  filtroEstado === f.value
                    ? 'bg-emerald-600 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}>
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {/* Table */}
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="w-5 h-5 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-12 text-center">
            <p className="text-sm text-gray-500">No hay separaciones{search ? ' para ese filtro' : ''}</p>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-[10px] text-gray-500 uppercase tracking-wider">
                  <th className="px-4 py-2.5 text-left font-medium">ID</th>
                  <th className="px-4 py-2.5 text-left font-medium">Cliente</th>
                  <th className="px-4 py-2.5 text-left font-medium hidden md:table-cell">Documento</th>
                  <th className="px-4 py-2.5 text-left font-medium hidden lg:table-cell">Moto</th>
                  <th className="px-4 py-2.5 text-right font-medium hidden xl:table-cell">Cuota</th>
                  <th className="px-4 py-2.5 text-right font-medium hidden xl:table-cell">Matrícula</th>
                  <th className="px-4 py-2.5 text-right font-medium">Total</th>
                  <th className="px-4 py-2.5 text-right font-medium">Pagado</th>
                  <th className="px-4 py-2.5 text-right font-medium">Falta</th>
                  <th className="px-4 py-2.5 text-center font-medium">Estado</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(sep => (
                  <tr key={sep.separacion_id}
                    onClick={() => setSelected(sep.separacion_id)}
                    className="border-t border-gray-50 hover:bg-gray-50 cursor-pointer transition-colors">
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-600">{sep.separacion_id}</td>
                    <td className="px-4 py-2.5 text-gray-900 font-medium">{sep.cliente.nombre}</td>
                    <td className="px-4 py-2.5 text-gray-600 font-mono text-xs hidden md:table-cell">
                      {sep.cliente.tipo_documento || 'CC'} {sep.cliente.cc}
                    </td>
                    <td className="px-4 py-2.5 text-gray-600 hidden lg:table-cell">{sep.moto.modelo}</td>
                    <td className="px-4 py-2.5 text-right text-gray-600 hidden xl:table-cell">{formatCOP(sep.moto.cuota_inicial_requerida - MATRICULA)}</td>
                    <td className="px-4 py-2.5 text-right text-gray-600 hidden xl:table-cell">{formatCOP(MATRICULA)}</td>
                    <td className="px-4 py-2.5 text-right text-gray-900 font-medium">{formatCOP(sep.moto.cuota_inicial_requerida)}</td>
                    <td className="px-4 py-2.5 text-right font-semibold text-gray-900">{formatCOP(sep.total_abonado)}</td>
                    <td className="px-4 py-2.5 text-right">
                      <span className={`font-semibold ${sep.saldo_pendiente <= 0 ? 'text-emerald-600' : 'text-red-500'}`}>
                        {sep.saldo_pendiente <= 0 ? '✓' : formatCOP(sep.saldo_pendiente)}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border ${estadoPill(sep.estado)}`}>
                        {sep.estado}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showNueva && <NuevaSeparacionModal onClose={() => setShowNueva(false)} onCreated={load} />}
      {selectedDoc && (
        <DetallePanel
          sep={selectedDoc}
          toast={showToast}
          onClose={() => setSelected(null)}
          onUpdated={() => { load(); setSelected(selectedDoc.separacion_id) }}
        />
      )}

      {/* Toast */}
      {toast && (
        <div
          role="status"
          className={`fixed bottom-4 right-4 z-[70] max-w-sm rounded-lg shadow-lg px-4 py-3 text-sm border ${
            toast.kind === 'success'
              ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
              : toast.kind === 'warning'
              ? 'bg-amber-50 text-amber-900 border-amber-200'
              : 'bg-red-50 text-red-700 border-red-200'
          }`}
        >
          {toast.msg}
        </div>
      )}
    </div>
  )
}
