import { useState } from 'react'
import { apiPost } from '@/lib/api'

// ═══════════════════════════════════════════
// Types
// ═══════════════════════════════════════════

interface Props {
  loanbookId: string
  estado: string
  tipoProducto: string
  cuotaMonto: number
  cuotaInicial: number
  proximaCuota: { fecha: string; monto: number } | null
  numProximaCuota: number | null
  onSuccess: () => void
}

type Modal = 'pago' | 'pago_inicial' | 'entrega' | null

const METODOS = [
  { value: 'efectivo', label: 'Efectivo' },
  { value: 'bancolombia', label: 'Transferencia Bancolombia' },
  { value: 'bbva', label: 'Transferencia BBVA' },
  { value: 'davivienda', label: 'Transferencia Davivienda' },
  { value: 'nequi', label: 'Nequi' },
  { value: 'transferencia', label: 'Otra transferencia' },
  { value: 'otro', label: 'Otro' },
]

const DIAS_COBRO = [
  { value: '', label: 'Miércoles (default)' },
  { value: 'jueves', label: 'Jueves (excepción)' },
  { value: 'viernes', label: 'Viernes (excepción)' },
  { value: 'lunes', label: 'Lunes (excepción)' },
]

function todayISO(): string {
  const d = new Date()
  d.setHours(12, 0, 0, 0)
  return d.toISOString().slice(0, 10)
}

function firstWednesdayAfter(dateStr: string): string {
  const d = new Date(dateStr + 'T12:00:00')
  d.setDate(d.getDate() + 7)
  const offset = (3 - d.getDay() + 7) % 7 // JS: Sunday=0, Wed=3
  d.setDate(d.getDate() + offset)
  return d.toISOString().slice(0, 10)
}

// ═══════════════════════════════════════════
// Component
// ═══════════════════════════════════════════

export default function LoanActionPanel({
  loanbookId,
  estado,
  tipoProducto,
  cuotaMonto,
  cuotaInicial,
  proximaCuota,
  numProximaCuota,
  onSuccess,
}: Props) {
  const [modal, setModal] = useState<Modal>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const esPendienteEntrega = estado === 'pendiente_entrega'
  const esActivo = !['saldado', 'castigado'].includes(estado)

  // Form state (pago)
  const [pagoForm, setPagoForm] = useState({
    cuota_numero: numProximaCuota ?? 1,
    monto_pago: proximaCuota?.monto ?? cuotaMonto,
    metodo_pago: 'efectivo',
    fecha_pago: todayISO(),
    referencia: '',
  })

  // Form state (inicial)
  const [inicialForm, setInicialForm] = useState({
    monto_pago: cuotaInicial,
    metodo_pago: 'efectivo',
    fecha_pago: todayISO(),
    referencia: '',
  })

  // Form state (entrega)
  const today = todayISO()
  const [entregaForm, setEntregaForm] = useState({
    fecha_entrega: today,
    fecha_primera_cuota: firstWednesdayAfter(today),
    dia_cobro_especial: '',
  })

  async function submitPago() {
    setLoading(true); setError('')
    try {
      await apiPost(`/loanbook/${loanbookId}/registrar-pago`, pagoForm)
      setModal(null)
      onSuccess()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setLoading(false) }
  }

  async function submitInicial() {
    setLoading(true); setError('')
    try {
      await apiPost(`/loanbook/${loanbookId}/registrar-pago-inicial`, inicialForm)
      setModal(null)
      onSuccess()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setLoading(false) }
  }

  async function submitEntrega() {
    setLoading(true); setError('')
    try {
      const body: Record<string, string> = {
        fecha_entrega: entregaForm.fecha_entrega,
        fecha_primera_cuota: entregaForm.fecha_primera_cuota,
      }
      if (entregaForm.dia_cobro_especial) body.dia_cobro_especial = entregaForm.dia_cobro_especial
      await apiPost(`/loanbook/${loanbookId}/registrar-entrega`, body)
      setModal(null)
      onSuccess()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setLoading(false) }
  }

  // Modal overlay wrapper
  function ModalWrap({ title, children }: { title: string; children: React.ReactNode }) {
    return (
      <div className="fixed inset-0 z-[60] bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
        onClick={() => !loading && setModal(null)}>
        <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-5" onClick={e => e.stopPropagation()}>
          <h3 className="font-display font-bold text-on-surface text-base mb-4">{title}</h3>
          {children}
          {error && <p className="text-xs text-red-600 mt-3">{error}</p>}
        </div>
      </div>
    )
  }

  function inputClass() {
    return "w-full rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface placeholder:text-on-surface-variant/50 outline-none focus:ring-2 focus:ring-primary/30"
  }

  return (
    <>
      {/* Action buttons */}
      <div className="flex flex-wrap gap-2">
        {esPendienteEntrega && tipoProducto === 'moto' && (
          <button onClick={() => setModal('pago_inicial')}
            className="flex-1 min-w-[140px] px-3 py-2 rounded-md bg-emerald-500 text-white text-xs font-medium hover:bg-emerald-600 transition-colors">
            Registrar Cuota Inicial
          </button>
        )}
        {esPendienteEntrega && (
          <button onClick={() => setModal('entrega')}
            className="flex-1 min-w-[140px] px-3 py-2 rounded-md bg-primary text-white text-xs font-medium hover:bg-primary/90 transition-colors">
            Registrar Entrega
          </button>
        )}
        {esActivo && !esPendienteEntrega && (
          <button onClick={() => setModal('pago')}
            className="flex-1 min-w-[140px] px-3 py-2 rounded-md bg-primary text-white text-xs font-medium hover:bg-primary/90 transition-colors">
            Registrar Pago
          </button>
        )}
      </div>

      {/* Pago modal */}
      {modal === 'pago' && (
        <ModalWrap title="Registrar pago de cuota">
          <div className="space-y-3">
            <div>
              <label className="text-xs text-on-surface-variant">Cuota #</label>
              <input type="number" className={inputClass()}
                value={pagoForm.cuota_numero}
                onChange={e => setPagoForm({ ...pagoForm, cuota_numero: Number(e.target.value) })} />
            </div>
            <div>
              <label className="text-xs text-on-surface-variant">Monto pagado</label>
              <input type="number" className={inputClass()}
                value={pagoForm.monto_pago}
                onChange={e => setPagoForm({ ...pagoForm, monto_pago: Number(e.target.value) })} />
            </div>
            <div>
              <label className="text-xs text-on-surface-variant">Método</label>
              <select className={inputClass()} value={pagoForm.metodo_pago}
                onChange={e => setPagoForm({ ...pagoForm, metodo_pago: e.target.value })}>
                {METODOS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-on-surface-variant">Fecha</label>
              <input type="date" className={inputClass()}
                value={pagoForm.fecha_pago}
                onChange={e => setPagoForm({ ...pagoForm, fecha_pago: e.target.value })} />
            </div>
            <div>
              <label className="text-xs text-on-surface-variant">Referencia (opcional)</label>
              <input type="text" className={inputClass()}
                placeholder="Comprobante, autorización..."
                value={pagoForm.referencia}
                onChange={e => setPagoForm({ ...pagoForm, referencia: e.target.value })} />
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={() => setModal(null)} disabled={loading}
              className="flex-1 rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface-variant">
              Cancelar
            </button>
            <button onClick={submitPago} disabled={loading}
              className="flex-1 rounded-md bg-primary px-3 py-2 text-sm text-white font-medium disabled:opacity-50">
              {loading ? 'Procesando...' : 'Confirmar'}
            </button>
          </div>
        </ModalWrap>
      )}

      {/* Cuota inicial modal */}
      {modal === 'pago_inicial' && (
        <ModalWrap title="Registrar cuota inicial">
          <div className="space-y-3">
            <div>
              <label className="text-xs text-on-surface-variant">Monto</label>
              <input type="number" className={inputClass()}
                value={inicialForm.monto_pago}
                onChange={e => setInicialForm({ ...inicialForm, monto_pago: Number(e.target.value) })} />
            </div>
            <div>
              <label className="text-xs text-on-surface-variant">Método</label>
              <select className={inputClass()} value={inicialForm.metodo_pago}
                onChange={e => setInicialForm({ ...inicialForm, metodo_pago: e.target.value })}>
                {METODOS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-on-surface-variant">Fecha</label>
              <input type="date" className={inputClass()}
                value={inicialForm.fecha_pago}
                onChange={e => setInicialForm({ ...inicialForm, fecha_pago: e.target.value })} />
            </div>
            <div>
              <label className="text-xs text-on-surface-variant">Referencia (opcional)</label>
              <input type="text" className={inputClass()}
                value={inicialForm.referencia}
                onChange={e => setInicialForm({ ...inicialForm, referencia: e.target.value })} />
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={() => setModal(null)} disabled={loading}
              className="flex-1 rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface-variant">
              Cancelar
            </button>
            <button onClick={submitInicial} disabled={loading}
              className="flex-1 rounded-md bg-emerald-500 px-3 py-2 text-sm text-white font-medium disabled:opacity-50">
              {loading ? 'Procesando...' : 'Confirmar'}
            </button>
          </div>
        </ModalWrap>
      )}

      {/* Entrega modal */}
      {modal === 'entrega' && (
        <ModalWrap title="Registrar entrega de moto">
          <div className="space-y-3">
            <div>
              <label className="text-xs text-on-surface-variant">Fecha entrega</label>
              <input type="date" className={inputClass()}
                value={entregaForm.fecha_entrega}
                onChange={e => {
                  const v = e.target.value
                  setEntregaForm({
                    ...entregaForm,
                    fecha_entrega: v,
                    fecha_primera_cuota: firstWednesdayAfter(v),
                  })
                }} />
            </div>
            <div>
              <label className="text-xs text-on-surface-variant">Día de cobro</label>
              <select className={inputClass()} value={entregaForm.dia_cobro_especial}
                onChange={e => setEntregaForm({ ...entregaForm, dia_cobro_especial: e.target.value })}>
                {DIAS_COBRO.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-on-surface-variant">Primera cuota</label>
              <input type="date" className={inputClass()}
                value={entregaForm.fecha_primera_cuota}
                onChange={e => setEntregaForm({ ...entregaForm, fecha_primera_cuota: e.target.value })} />
              <p className="text-[10px] text-on-surface-variant/70 mt-1">
                Auto-calculada como primer miércoles ≥ entrega+7. Ajusta si es caso excepcional.
              </p>
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={() => setModal(null)} disabled={loading}
              className="flex-1 rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface-variant">
              Cancelar
            </button>
            <button onClick={submitEntrega} disabled={loading}
              className="flex-1 rounded-md bg-primary px-3 py-2 text-sm text-white font-medium disabled:opacity-50">
              {loading ? 'Procesando...' : 'Confirmar entrega'}
            </button>
          </div>
        </ModalWrap>
      )}
    </>
  )
}
