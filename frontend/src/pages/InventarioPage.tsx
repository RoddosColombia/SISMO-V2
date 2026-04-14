import { useState, useEffect, useCallback } from 'react'
import { apiGet, apiPost } from '@/lib/api'

// ═══════════════════════════════════════════
// Types
// ═══════════════════════════════════════════

interface Moto {
  id_alegra: string
  nombre: string
  descripcion: string
  referencia: string
  categoria: string
  stock: number
  precio: number
  costo_unitario: number
  estado: string
  apartado?: {
    cliente: string
    monto_acumulado: number
    cuota_inicial_total: number
    fecha_apartado: string
    fecha_limite: string
  }
}

interface KitComponente {
  item_id_alegra: string
  nombre: string
  stock_alegra: number
  necesita: number
  alcanza_para: number
}

interface Kit {
  nombre: string
  modelo: string
  tipo: string
  precio_kit: number
  kits_disponibles: number
  componente_limitante: KitComponente | null
  componentes: KitComponente[]
  alerta: boolean
}

interface Repuesto {
  id_alegra: string
  nombre: string
  codigo: string
  stock_actual: number
  precio: number
  categoria: string
  alerta_stock_bajo: boolean
}

const BANCOS = [
  { value: 'bancolombia_2029', label: 'Bancolombia 2029' },
  { value: 'bancolombia_2540', label: 'Bancolombia 2540' },
  { value: 'bbva_0210', label: 'BBVA 0210' },
  { value: 'bbva_0212', label: 'BBVA 0212' },
  { value: 'davivienda_482', label: 'Davivienda 482' },
  { value: 'nequi', label: 'Nequi' },
]

// ═══════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════

function formatCOP(n: number) {
  return new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(n)
}

function estadoBadge(estado: string) {
  const map: Record<string, string> = {
    Disponible: 'bg-emerald-500/10 text-emerald-700',
    Apartada: 'bg-amber-500/10 text-amber-700',
    Agotada: 'bg-neutral-400/10 text-neutral-500',
  }
  return map[estado] || 'bg-neutral-400/10 text-neutral-500'
}

function kitSemaforo(n: number) {
  if (n >= 5) return 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20'
  if (n >= 1) return 'bg-amber-500/10 text-amber-700 border-amber-500/20'
  return 'bg-red-500/10 text-red-700 border-red-500/20'
}

// ═══════════════════════════════════════════
// Apartar Modal
// ═══════════════════════════════════════════

function ApartarModal({ moto, onClose, onSuccess }: {
  moto: Moto
  onClose: () => void
  onSuccess: () => void
}) {
  const [form, setForm] = useState({
    cliente_nombre: '',
    cliente_cedula: '',
    cliente_telefono: '',
    monto_pago: 0,
    cuota_inicial_total: 0,
    banco_recibo: 'bancolombia_2029',
    plan_credito: '',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async () => {
    if (!form.cliente_nombre || !form.cliente_cedula || form.monto_pago <= 0 || form.cuota_inicial_total <= 0) {
      setError('Complete todos los campos obligatorios')
      return
    }
    setLoading(true)
    setError('')
    try {
      await apiPost(`/inventario/motos/${moto.id_alegra}/apartar`, form)
      onSuccess()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error al apartar')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-surface-container-lowest rounded-xl shadow-ambient-2 w-full max-w-md mx-4 p-6" onClick={e => e.stopPropagation()}>
        <h3 className="font-display font-bold text-on-surface text-base mb-1">Apartar moto</h3>
        <p className="text-xs text-on-surface-variant mb-4">{moto.nombre} — {moto.descripcion}</p>

        <div className="space-y-3">
          <input className="w-full rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface placeholder:text-on-surface-variant/50 outline-none focus:ring-2 focus:ring-primary/30"
            placeholder="Nombre cliente *" value={form.cliente_nombre}
            onChange={e => setForm({ ...form, cliente_nombre: e.target.value })} />
          <input className="w-full rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface placeholder:text-on-surface-variant/50 outline-none focus:ring-2 focus:ring-primary/30"
            placeholder="Cedula *" value={form.cliente_cedula}
            onChange={e => setForm({ ...form, cliente_cedula: e.target.value })} />
          <input className="w-full rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface placeholder:text-on-surface-variant/50 outline-none focus:ring-2 focus:ring-primary/30"
            placeholder="Telefono" value={form.cliente_telefono}
            onChange={e => setForm({ ...form, cliente_telefono: e.target.value })} />
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-on-surface-variant">Pago inicial *</label>
              <input type="number" className="w-full rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface outline-none focus:ring-2 focus:ring-primary/30"
                value={form.monto_pago || ''} onChange={e => setForm({ ...form, monto_pago: Number(e.target.value) })} />
            </div>
            <div>
              <label className="text-xs text-on-surface-variant">Cuota inicial total *</label>
              <input type="number" className="w-full rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface outline-none focus:ring-2 focus:ring-primary/30"
                value={form.cuota_inicial_total || ''} onChange={e => setForm({ ...form, cuota_inicial_total: Number(e.target.value) })} />
            </div>
          </div>
          <select className="w-full rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface outline-none focus:ring-2 focus:ring-primary/30"
            value={form.banco_recibo} onChange={e => setForm({ ...form, banco_recibo: e.target.value })}>
            {BANCOS.map(b => <option key={b.value} value={b.value}>{b.label}</option>)}
          </select>
          <input className="w-full rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface placeholder:text-on-surface-variant/50 outline-none focus:ring-2 focus:ring-primary/30"
            placeholder="Plan de credito (ej: 36 cuotas)" value={form.plan_credito}
            onChange={e => setForm({ ...form, plan_credito: e.target.value })} />
        </div>

        {error && <p className="text-xs text-red-600 mt-3">{error}</p>}

        <div className="flex gap-3 mt-5">
          <button onClick={onClose} className="flex-1 rounded-md bg-surface-container-low px-4 py-2 text-sm text-on-surface-variant hover:bg-surface-container-low/80">Cancelar</button>
          <button onClick={handleSubmit} disabled={loading}
            className="flex-1 rounded-md bg-primary px-4 py-2 text-sm text-white font-medium hover:bg-primary/90 disabled:opacity-50">
            {loading ? 'Procesando...' : 'Apartar'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════
// Detalle Apartado Modal
// ═══════════════════════════════════════════

function DetalleApartadoModal({ moto, onClose, onSuccess }: {
  moto: Moto
  onClose: () => void
  onSuccess: () => void
}) {
  const apt = moto.apartado!
  const pct = apt.cuota_inicial_total > 0 ? Math.min((apt.monto_acumulado / apt.cuota_inicial_total) * 100, 100) : 0

  const [pagoMonto, setPagoMonto] = useState(0)
  const [pagoBanco, setPagoBanco] = useState('bancolombia_2029')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handlePago = async () => {
    if (pagoMonto <= 0) { setError('Ingrese un monto'); return }
    setLoading(true); setError('')
    try {
      await apiPost(`/inventario/motos/${moto.id_alegra}/pago-parcial`, { monto_pago: pagoMonto, banco_recibo: pagoBanco })
      onSuccess()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setLoading(false) }
  }

  const handleLiberar = async () => {
    if (!confirm('Liberar esta moto? El apartado se cancelara.')) return
    setLoading(true)
    try {
      await apiPost(`/inventario/motos/${moto.id_alegra}/liberar`, {})
      onSuccess()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error')
    } finally { setLoading(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-surface-container-lowest rounded-xl shadow-ambient-2 w-full max-w-md mx-4 p-6" onClick={e => e.stopPropagation()}>
        <h3 className="font-display font-bold text-on-surface text-base mb-1">Detalle apartado</h3>
        <p className="text-xs text-on-surface-variant mb-4">{moto.nombre} — {moto.descripcion}</p>

        <div className="space-y-3 mb-4">
          <div className="flex justify-between text-sm">
            <span className="text-on-surface-variant">Cliente</span>
            <span className="text-on-surface font-medium">{apt.cliente}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-on-surface-variant">Acumulado</span>
            <span className="text-on-surface font-medium">{formatCOP(apt.monto_acumulado)}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-on-surface-variant">Cuota inicial</span>
            <span className="text-on-surface font-medium">{formatCOP(apt.cuota_inicial_total)}</span>
          </div>
          {/* Progress bar */}
          <div>
            <div className="flex justify-between text-xs text-on-surface-variant mb-1">
              <span>Progreso</span>
              <span>{pct.toFixed(0)}%</span>
            </div>
            <div className="h-2 bg-surface-container-low rounded-full overflow-hidden">
              <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${pct}%` }} />
            </div>
          </div>
        </div>

        {/* Pago parcial */}
        <div className="border-t border-surface-container-low pt-4 space-y-3">
          <p className="text-xs font-medium text-on-surface">Registrar pago parcial</p>
          <div className="grid grid-cols-2 gap-3">
            <input type="number" placeholder="Monto"
              className="rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface outline-none focus:ring-2 focus:ring-primary/30"
              value={pagoMonto || ''} onChange={e => setPagoMonto(Number(e.target.value))} />
            <select className="rounded-md bg-surface-container-low px-3 py-2 text-sm text-on-surface outline-none focus:ring-2 focus:ring-primary/30"
              value={pagoBanco} onChange={e => setPagoBanco(e.target.value)}>
              {BANCOS.map(b => <option key={b.value} value={b.value}>{b.label}</option>)}
            </select>
          </div>
          <button onClick={handlePago} disabled={loading}
            className="w-full rounded-md bg-secondary px-4 py-2 text-sm text-white font-medium hover:bg-secondary/90 disabled:opacity-50">
            {loading ? 'Procesando...' : 'Registrar pago'}
          </button>
        </div>

        {error && <p className="text-xs text-red-600 mt-3">{error}</p>}

        <div className="flex gap-3 mt-5">
          <button onClick={handleLiberar} disabled={loading}
            className="flex-1 rounded-md bg-red-500/10 px-4 py-2 text-sm text-red-700 font-medium hover:bg-red-500/20 disabled:opacity-50">
            Liberar moto
          </button>
          <button onClick={onClose}
            className="flex-1 rounded-md bg-surface-container-low px-4 py-2 text-sm text-on-surface-variant hover:bg-surface-container-low/80">
            Cerrar
          </button>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════
// Main Page
// ═══════════════════════════════════════════

export default function InventarioPage() {
  const [tab, setTab] = useState<'motos' | 'repuestos'>('motos')
  const [motos, setMotos] = useState<Moto[]>([])
  const [kits, setKits] = useState<Kit[]>([])
  const [repuestos, setRepuestos] = useState<Repuesto[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedMoto, setSelectedMoto] = useState<Moto | null>(null)
  const [modalType, setModalType] = useState<'apartar' | 'detalle' | null>(null)
  const [filtroEstado, setFiltroEstado] = useState('')

  const loadMotos = useCallback(async () => {
    try {
      const res = await apiGet<{ data: Moto[] }>('/inventario/motos')
      setMotos(res.data)
    } catch { /* ignore */ }
  }, [])

  const loadRepuestos = useCallback(async () => {
    try {
      const [repRes, kitsRes] = await Promise.all([
        apiGet<{ data: Repuesto[] }>('/inventario/repuestos'),
        apiGet<{ data: Kit[] }>('/inventario/kits'),
      ])
      setRepuestos(repRes.data)
      setKits(kitsRes.data)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    setLoading(true)
    if (tab === 'motos') {
      loadMotos().finally(() => setLoading(false))
    } else {
      loadRepuestos().finally(() => setLoading(false))
    }
  }, [tab, loadMotos, loadRepuestos])

  const handleMotoClick = (moto: Moto) => {
    setSelectedMoto(moto)
    if (moto.estado === 'Disponible') setModalType('apartar')
    else if (moto.estado === 'Apartada') setModalType('detalle')
  }

  const handleModalSuccess = () => {
    setModalType(null)
    setSelectedMoto(null)
    loadMotos()
  }

  const filteredMotos = filtroEstado
    ? motos.filter(m => m.estado.toLowerCase() === filtroEstado.toLowerCase())
    : motos

  const totalStock = motos.reduce((sum, m) => sum + m.stock, 0)
  const disponibles = motos.filter(m => m.estado === 'Disponible').reduce((s, m) => s + m.stock, 0)
  const apartadas = motos.filter(m => m.estado === 'Apartada').length

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* Header */}
      <div className="px-6 pt-6 pb-4 flex items-center justify-between">
        <div>
          <h1 className="font-display text-lg font-bold text-on-surface">Inventario</h1>
          <p className="text-sm text-on-surface-variant mt-0.5">Motos y repuestos — datos en vivo de Alegra</p>
        </div>
        {/* Tabs */}
        <div className="flex bg-surface-container-low rounded-lg p-0.5">
          <button onClick={() => setTab('motos')}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${tab === 'motos' ? 'bg-surface-container-lowest shadow-sm text-on-surface' : 'text-on-surface-variant hover:text-on-surface'}`}>
            Motos
          </button>
          <button onClick={() => setTab('repuestos')}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${tab === 'repuestos' ? 'bg-surface-container-lowest shadow-sm text-on-surface' : 'text-on-surface-variant hover:text-on-surface'}`}>
            Repuestos y Kits
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 pb-6">
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : tab === 'motos' ? (
          <>
            {/* Summary cards */}
            <div className="grid grid-cols-3 gap-4 mb-5">
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                <div className="text-xs text-on-surface-variant uppercase tracking-wider">Total stock</div>
                <div className="font-display text-2xl font-bold text-on-surface">{totalStock}</div>
              </div>
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                <div className="text-xs text-on-surface-variant uppercase tracking-wider">Disponibles</div>
                <div className="font-display text-2xl font-bold text-emerald-600">{disponibles}</div>
              </div>
              <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
                <div className="text-xs text-on-surface-variant uppercase tracking-wider">Apartadas</div>
                <div className="font-display text-2xl font-bold text-amber-600">{apartadas}</div>
              </div>
            </div>

            {/* Filter */}
            <div className="flex gap-2 mb-4">
              {['', 'Disponible', 'Apartada', 'Agotada'].map(est => (
                <button key={est} onClick={() => setFiltroEstado(est)}
                  className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${filtroEstado === est ? 'bg-primary/10 text-primary' : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-low/80'}`}>
                  {est || 'Todas'}
                </button>
              ))}
            </div>

            {/* Moto cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredMotos.map(moto => (
                <div key={moto.id_alegra}
                  onClick={() => handleMotoClick(moto)}
                  className={`bg-surface-container-lowest shadow-ambient-1 rounded-lg px-5 py-4 cursor-pointer transition-shadow hover:shadow-ambient-2 ${moto.estado === 'Agotada' ? 'opacity-50' : ''}`}>
                  <div className="flex items-start justify-between mb-2">
                    <div className="font-display font-bold text-on-surface text-sm">{moto.nombre}</div>
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${estadoBadge(moto.estado)}`}>
                      {moto.estado}
                    </span>
                  </div>
                  <p className="text-xs text-on-surface-variant line-clamp-2 mb-3">{moto.descripcion || 'Sin descripcion'}</p>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-on-surface-variant">{moto.categoria}</span>
                    <span className="font-medium text-on-surface">Stock: {moto.stock}</span>
                  </div>
                  {moto.precio > 0 && (
                    <div className="text-xs font-medium text-primary mt-1">{formatCOP(moto.precio)}</div>
                  )}
                  {moto.apartado && (
                    <div className="mt-2 pt-2 border-t border-surface-container-low">
                      <div className="text-xs text-amber-700 font-medium">{moto.apartado.cliente}</div>
                      <div className="text-[10px] text-on-surface-variant">
                        {formatCOP(moto.apartado.monto_acumulado)} / {formatCOP(moto.apartado.cuota_inicial_total)}
                      </div>
                    </div>
                  )}
                </div>
              ))}
              {filteredMotos.length === 0 && (
                <div className="col-span-full text-center text-sm text-on-surface-variant py-8">
                  No hay motos {filtroEstado ? `con estado "${filtroEstado}"` : ''}
                </div>
              )}
            </div>
          </>
        ) : (
          <>
            {/* Kits section */}
            {kits.length > 0 && (
              <div className="mb-6">
                <h2 className="font-display font-bold text-on-surface text-sm mb-3">Kits disponibles</h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {kits.map(kit => (
                    <div key={kit.nombre} className={`rounded-lg border px-5 py-4 ${kitSemaforo(kit.kits_disponibles)}`}>
                      <div className="flex items-start justify-between mb-2">
                        <div className="font-display font-bold text-sm">{kit.nombre}</div>
                        <span className="text-2xl font-bold">{kit.kits_disponibles}</span>
                      </div>
                      {kit.modelo && <p className="text-xs opacity-70 mb-2">{kit.modelo}</p>}
                      {kit.componente_limitante && (
                        <div className="text-xs mt-2 pt-2 border-t border-current/10">
                          <span className="opacity-70">Limitante: </span>
                          <span className="font-medium">{kit.componente_limitante.item_id_alegra}</span>
                          <span className="opacity-70"> (stock: {kit.componente_limitante.stock}, necesita: {kit.componente_limitante.necesita})</span>
                        </div>
                      )}
                      {kit.precio_kit > 0 && (
                        <div className="text-xs font-medium mt-1">{formatCOP(kit.precio_kit)}</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Repuestos table */}
            <div>
              <h2 className="font-display font-bold text-on-surface text-sm mb-3">Repuestos individuales</h2>
              {repuestos.length === 0 ? (
                <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg p-8 text-center">
                  <p className="text-sm text-on-surface-variant">No hay repuestos registrados en Alegra</p>
                  <p className="text-xs text-on-surface-variant/60 mt-1">Agregue items tipo "product" con categorias de repuestos en Alegra</p>
                </div>
              ) : (
                <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-surface-container-low">
                        <th className="text-left px-4 py-2 text-xs text-on-surface-variant font-medium">Codigo</th>
                        <th className="text-left px-4 py-2 text-xs text-on-surface-variant font-medium">Nombre</th>
                        <th className="text-right px-4 py-2 text-xs text-on-surface-variant font-medium">Stock</th>
                        <th className="text-right px-4 py-2 text-xs text-on-surface-variant font-medium">Precio</th>
                      </tr>
                    </thead>
                    <tbody>
                      {repuestos.map(rep => (
                        <tr key={rep.id_alegra} className="border-t border-surface-container-low">
                          <td className="px-4 py-2 font-mono text-xs">{rep.codigo || '-'}</td>
                          <td className="px-4 py-2">{rep.nombre}</td>
                          <td className={`px-4 py-2 text-right font-medium ${rep.alerta_stock_bajo ? 'text-red-600' : ''}`}>
                            {rep.stock_actual}
                            {rep.alerta_stock_bajo && <span className="ml-1 text-[10px]">bajo</span>}
                          </td>
                          <td className="px-4 py-2 text-right">{formatCOP(rep.precio)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Modals */}
      {selectedMoto && modalType === 'apartar' && (
        <ApartarModal moto={selectedMoto} onClose={() => { setModalType(null); setSelectedMoto(null) }} onSuccess={handleModalSuccess} />
      )}
      {selectedMoto && modalType === 'detalle' && selectedMoto.apartado && (
        <DetalleApartadoModal moto={selectedMoto} onClose={() => { setModalType(null); setSelectedMoto(null) }} onSuccess={handleModalSuccess} />
      )}
    </div>
  )
}
