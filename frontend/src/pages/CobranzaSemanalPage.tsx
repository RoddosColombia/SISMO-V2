/**
 * /cartera/cobranza-semanal — Superapp operativa para Liz e Iván.
 *
 * Vista única que agrupa para los próximos 7 días:
 *   - Hero: objetivo semanal, recaudado hoy/semana, % avance, clientes
 *   - Checklist: cuotas que vencen en [hoy, hoy+7d], chequeable
 *   - En mora: clientes con DPD > 0 ordenados desc
 *
 * Fuente única: GET /api/loanbook/cobranza-semanal
 * Acción de pago: PUT /api/loanbook/{id}/pago (motor canónico)
 */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiGet, apiPut } from '@/lib/api'

type Item = {
  loanbook_id: string
  cliente_nombre: string
  cliente_telefono?: string | null
  cuota_numero: number
  es_cuota_inicial: boolean
  monto: number
  monto_capital: number
  monto_interes: number
  fecha_vencimiento: string
  vencida: boolean
  dias_diff: number
  dpd: number
  estado: string
  saldo_pendiente: number
  vin?: string | null
  modelo?: string | null
}

type CobranzaResponse = {
  fecha_corte: string
  ventana_dias: number
  ventana_desde: string
  ventana_hasta: string
  semana_objetivo: number
  recaudado_hoy: number
  recaudado_semana: number
  porcentaje: number
  clientes_por_pagar: number
  clientes_en_mora: number
  checklist: Item[]
  en_mora: Item[]
}

const METODOS = ['transferencia', 'wava', 'efectivo', 'otro'] as const
type Metodo = typeof METODOS[number]

function formatCOP(v: number): string {
  return '$' + (v ?? 0).toLocaleString('es-CO')
}
function formatDate(iso: string): string {
  if (!iso) return ''
  const [y, m, d] = iso.split('-')
  const meses = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic']
  return `${parseInt(d)} ${meses[parseInt(m)-1]}`
}

interface PaymentModalProps {
  item: Item
  onClose: () => void
  onConfirm: (params: { monto: number; metodo: Metodo; fecha: string; referencia: string }) => Promise<void>
}

function PaymentModal({ item, onClose, onConfirm }: PaymentModalProps) {
  const [monto, setMonto] = useState<number>(item.monto)
  const [metodo, setMetodo] = useState<Metodo>('transferencia')
  const [fecha, setFecha] = useState<string>(new Date().toISOString().slice(0, 10))
  const [referencia, setReferencia] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    setSubmitting(true)
    setError(null)
    try {
      await onConfirm({ monto, metodo, fecha, referencia })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error al registrar pago')
      setSubmitting(false)
    }
  }

  const cuotaLabel = item.es_cuota_inicial ? 'Cuota inicial' : `Cuota ${item.cuota_numero}`

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-end sm:items-center justify-center p-4">
      <div className="bg-surface rounded-t-2xl sm:rounded-2xl w-full max-w-md p-6 shadow-2xl">
        <div className="flex justify-between items-start mb-4">
          <div>
            <h2 className="font-display text-xl font-bold text-on-surface">{item.cliente_nombre}</h2>
            <p className="text-xs text-on-surface-variant">{item.loanbook_id} · {cuotaLabel}</p>
          </div>
          <button
            onClick={onClose}
            className="text-on-surface-variant hover:text-on-surface text-2xl leading-none"
            aria-label="Cerrar"
          >×</button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="text-xs text-on-surface-variant uppercase tracking-wider">Monto pagado</label>
            <input
              type="number"
              value={monto}
              onChange={(e) => setMonto(Number(e.target.value))}
              className="w-full mt-1 px-4 py-3 bg-surface-container-low rounded-lg text-on-surface text-xl font-display font-bold focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <div className="text-xs text-on-surface-variant mt-1">Sugerido: {formatCOP(item.monto)}</div>
          </div>

          <div>
            <label className="text-xs text-on-surface-variant uppercase tracking-wider">Método de pago</label>
            <div className="grid grid-cols-2 gap-2 mt-1">
              {METODOS.map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMetodo(m)}
                  className={`py-3 px-4 rounded-lg font-medium text-sm capitalize transition-colors ${
                    metodo === m
                      ? 'bg-primary text-on-primary'
                      : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container'
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs text-on-surface-variant uppercase tracking-wider">Fecha de pago</label>
            <input
              type="date"
              value={fecha}
              onChange={(e) => setFecha(e.target.value)}
              className="w-full mt-1 px-4 py-3 bg-surface-container-low rounded-lg text-on-surface focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          <div>
            <label className="text-xs text-on-surface-variant uppercase tracking-wider">Referencia (opcional)</label>
            <input
              type="text"
              placeholder="Wava-12345 / Bancolombia / Efectivo Liz"
              value={referencia}
              onChange={(e) => setReferencia(e.target.value)}
              className="w-full mt-1 px-4 py-3 bg-surface-container-low rounded-lg text-on-surface focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          {error && <div className="text-sm text-red-600 bg-red-50 p-3 rounded-lg">{error}</div>}

          <div className="flex gap-2 pt-2">
            <button
              onClick={onClose}
              disabled={submitting}
              className="flex-1 py-3 px-4 rounded-lg font-medium bg-surface-container-low text-on-surface-variant hover:bg-surface-container disabled:opacity-50"
            >Cancelar</button>
            <button
              onClick={handleSubmit}
              disabled={submitting || monto <= 0}
              className="flex-1 py-3 px-4 rounded-lg font-bold bg-primary text-on-primary hover:bg-primary/90 disabled:opacity-50"
            >{submitting ? 'Registrando...' : 'Registrar pago'}</button>
          </div>
        </div>
      </div>
    </div>
  )
}

interface ChecklistRowProps {
  item: Item
  highlightVencida: boolean
  onMarkPaid: (item: Item) => void
}

function ChecklistRow({ item, highlightVencida, onMarkPaid }: ChecklistRowProps) {
  const cuotaLabel = item.es_cuota_inicial ? 'Cuota inicial' : `Cuota #${item.cuota_numero}`
  const fechaColor = highlightVencida && item.vencida ? 'text-red-600' : 'text-on-surface'
  const containerColor = highlightVencida && item.vencida ? 'border-l-4 border-red-500 bg-red-50/30' : 'border-l-4 border-transparent'

  return (
    <div className={`${containerColor} bg-surface-container-low rounded-lg p-4 flex items-center gap-3 sm:gap-4`}>
      <button
        onClick={() => onMarkPaid(item)}
        className="w-7 h-7 sm:w-8 sm:h-8 rounded-full border-2 border-primary flex-shrink-0 hover:bg-primary/10 transition-colors flex items-center justify-center"
        aria-label={`Marcar ${cuotaLabel} pagada`}
        title="Click para registrar pago"
      >
        <span className="text-primary text-lg">+</span>
      </button>

      <div className="flex-1 min-w-0">
        <div className="flex flex-col sm:flex-row sm:items-baseline gap-1 sm:gap-2">
          <Link to={`/loanbook/${item.loanbook_id}`} className="font-medium text-on-surface hover:text-primary truncate">
            {item.cliente_nombre}
          </Link>
          <span className="text-[10px] text-on-surface-variant">{item.loanbook_id}</span>
        </div>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <span className="text-xs text-on-surface-variant">{cuotaLabel}</span>
          <span className="text-xs text-on-surface-variant">·</span>
          <span className={`text-xs font-medium ${fechaColor}`}>
            {formatDate(item.fecha_vencimiento)}
            {item.vencida && ` · ${Math.abs(item.dias_diff)}d`}
          </span>
          {item.dpd > 0 && (
            <>
              <span className="text-xs text-on-surface-variant">·</span>
              <span className="text-xs font-medium text-red-600">DPD {item.dpd}</span>
            </>
          )}
        </div>
      </div>

      <div className="text-right flex-shrink-0">
        <div className="font-display font-bold text-on-surface">{formatCOP(item.monto)}</div>
        <div className="text-[10px] text-on-surface-variant">{item.estado}</div>
      </div>
    </div>
  )
}

export default function CobranzaSemanalPage() {
  const [data, setData] = useState<CobranzaResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modalItem, setModalItem] = useState<Item | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  const load = async () => {
    try {
      const res = await apiGet<CobranzaResponse>('/loanbook/cobranza-semanal')
      setData(res)
      setError(null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error al cargar')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleConfirmPayment = async (
    item: Item,
    params: { monto: number; metodo: Metodo; fecha: string; referencia: string }
  ) => {
    const endpoint = item.es_cuota_inicial
      ? `/loanbook/${item.loanbook_id}/pago/inicial`
      : `/loanbook/${item.loanbook_id}/pago`
    const body = item.es_cuota_inicial
      ? {
          monto_pago: params.monto,
          metodo_pago: params.metodo,
          fecha_pago: params.fecha,
          referencia: params.referencia,
        }
      : {
          monto_pago: params.monto,
          metodo_pago: params.metodo,
          fecha_pago: params.fecha,
          referencia: params.referencia,
          cuota_numero: item.cuota_numero,
        }
    await apiPut(endpoint, body)
    setModalItem(null)
    setToast(`Pago de ${formatCOP(params.monto)} registrado para ${item.cliente_nombre}`)
    setTimeout(() => setToast(null), 4000)
    await load()
  }

  const porcentajeBar = useMemo(() => {
    if (!data || data.semana_objetivo === 0) return 0
    return Math.min(100, Math.round((data.recaudado_semana / data.semana_objetivo) * 100))
  }, [data])

  if (loading) return <div className="p-6 text-on-surface-variant">Cargando cobranza semanal...</div>
  if (error) return <div className="p-6 text-red-600">Error: {error}</div>
  if (!data) return null

  return (
    <div className="max-w-5xl mx-auto p-3 sm:p-6 space-y-4 sm:space-y-6">
      <header>
        <h1 className="font-display text-2xl sm:text-3xl font-bold text-on-surface">Cobranza semanal</h1>
        <p className="text-sm text-on-surface-variant">
          Ventana {formatDate(data.ventana_desde)} – {formatDate(data.ventana_hasta)} · Corte {formatDate(data.fecha_corte)}
        </p>
      </header>

      {/* Hero */}
      <section className="bg-primary/5 rounded-xl p-4 sm:p-6 space-y-4 border border-primary/20">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4">
          <div>
            <div className="text-[10px] text-primary uppercase tracking-wider font-medium">Objetivo semanal</div>
            <div className="font-display text-xl sm:text-2xl font-bold text-primary mt-1">{formatCOP(data.semana_objetivo)}</div>
          </div>
          <div>
            <div className="text-[10px] text-primary uppercase tracking-wider font-medium">Recaudado hoy</div>
            <div className="font-display text-xl sm:text-2xl font-bold text-emerald-600 mt-1">{formatCOP(data.recaudado_hoy)}</div>
          </div>
          <div>
            <div className="text-[10px] text-primary uppercase tracking-wider font-medium">Recaudado 7d</div>
            <div className="font-display text-xl sm:text-2xl font-bold text-emerald-600 mt-1">{formatCOP(data.recaudado_semana)}</div>
          </div>
          <div>
            <div className="text-[10px] text-primary uppercase tracking-wider font-medium">Clientes por cobrar</div>
            <div className="font-display text-xl sm:text-2xl font-bold text-on-surface mt-1">{data.clientes_por_pagar}</div>
          </div>
        </div>
        <div>
          <div className="flex justify-between text-xs text-on-surface-variant mb-1">
            <span>Avance semana</span>
            <span className="font-bold">{porcentajeBar}%</span>
          </div>
          <div className="h-2 bg-surface-container-low rounded-full overflow-hidden">
            <div
              className="h-full bg-emerald-500 transition-all"
              style={{ width: `${porcentajeBar}%` }}
            />
          </div>
        </div>
      </section>

      {/* Checklist principal */}
      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="font-display text-lg font-bold text-on-surface">Checklist · próximos 7 días</h2>
          <span className="text-xs text-on-surface-variant">{data.checklist.length} clientes</span>
        </div>
        {data.checklist.length === 0 ? (
          <div className="text-sm text-on-surface-variant bg-surface-container-low rounded-lg p-6 text-center">
            No hay cuotas próximas en los próximos 7 días.
          </div>
        ) : (
          <div className="space-y-2">
            {data.checklist.map((item) => (
              <ChecklistRow
                key={`chk-${item.loanbook_id}-${item.cuota_numero}`}
                item={item}
                highlightVencida={true}
                onMarkPaid={setModalItem}
              />
            ))}
          </div>
        )}
      </section>

      {/* En mora */}
      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="font-display text-lg font-bold text-red-700">⚠ Clientes en mora · acción urgente</h2>
          <span className="text-xs text-on-surface-variant">{data.en_mora.length} clientes</span>
        </div>
        {data.en_mora.length === 0 ? (
          <div className="text-sm text-on-surface-variant bg-emerald-50 border border-emerald-200 rounded-lg p-4 text-center">
            ✓ Sin clientes en mora
          </div>
        ) : (
          <div className="space-y-2">
            {data.en_mora.map((item) => (
              <ChecklistRow
                key={`mor-${item.loanbook_id}-${item.cuota_numero}`}
                item={item}
                highlightVencida={true}
                onMarkPaid={setModalItem}
              />
            ))}
          </div>
        )}
      </section>

      {modalItem && (
        <PaymentModal
          item={modalItem}
          onClose={() => setModalItem(null)}
          onConfirm={(params) => handleConfirmPayment(modalItem, params)}
        />
      )}

      {toast && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 bg-emerald-600 text-white px-6 py-3 rounded-full shadow-lg z-50 animate-pulse">
          ✓ {toast}
        </div>
      )}
    </div>
  )
}
