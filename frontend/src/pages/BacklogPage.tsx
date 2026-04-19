import { useState, useEffect, useCallback } from 'react'
import { apiGet, apiPost } from '@/lib/api'

interface BacklogMovimiento {
  _id: string
  fecha: string
  banco: string
  descripcion: string
  monto: number
  tipo: string
  razon_pendiente: string
  intentos: number
  estado: string
  confianza_v1?: number
}

interface CuentaAlegra {
  id: string
  nombre: string
  codigo: string
  es_banco?: boolean
}

const CUENTAS_FALLBACK: CuentaAlegra[] = [
  { id: '5480', nombre: 'Arrendamientos', codigo: '512010' },
  { id: '5485', nombre: 'Acueducto', codigo: '513525' },
  { id: '5487', nombre: 'Telefono / Internet', codigo: '513535' },
  { id: '5494', nombre: 'Gastos Varios', codigo: '51991001' },
  { id: '5462', nombre: 'Sueldos y salarios', codigo: '510506' },
  { id: '5475', nombre: 'Asesoria juridica', codigo: '511025' },
  { id: '5508', nombre: 'Comisiones', codigo: '530515' },
  { id: '5507', nombre: 'Gastos bancarios', codigo: '530505' },
  { id: '5509', nombre: 'Gravamen al movimiento Financiero', codigo: '531520' },
  { id: '5329', nombre: 'CXC Socios y accionistas', codigo: '132505' },
]

const BANCOS = ['Bancolombia', 'BBVA', 'Davivienda', 'Nequi', 'Global66']

export default function BacklogPage() {
  const [movimientos, setMovimientos] = useState<BacklogMovimiento[]>([])
  const [loading, setLoading] = useState(true)
  const [banco, setBanco] = useState('')
  const [estado, setEstado] = useState('pendiente')
  const [causarTarget, setCausarTarget] = useState<BacklogMovimiento | null>(null)
  const [cuentaId, setCuentaId] = useState('5494')
  const [retefuente, setRetefuente] = useState(0)
  const [reteica, setReteica] = useState(0)
  const [causarLoading, setCausarLoading] = useState(false)
  const [causarError, setCausarError] = useState('')
  const [cuentas, setCuentas] = useState<CuentaAlegra[]>(CUENTAS_FALLBACK)
  const [cuentaSearch, setCuentaSearch] = useState('')
  const [batchJobId, setBatchJobId] = useState<string | null>(null)
  const [batchStatus, setBatchStatus] = useState<{estado: string, total: number, procesados: number, exitosos: number, errores: number} | null>(null)
  const [showBatchConfirm, setShowBatchConfirm] = useState(false)
  const [tipoOperacion, setTipoOperacion] = useState<'gasto' | 'transferencia'>('gasto')
  const [cuentaOrigen, setCuentaOrigen] = useState('')
  const [cuentaDestino, setCuentaDestino] = useState('')

  const fetchBacklog = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (banco) params.set('banco', banco)
      if (estado) params.set('estado', estado)
      const qs = params.toString() ? `?${params.toString()}` : ''
      const data = await apiGet<{ success: boolean; data: BacklogMovimiento[] }>(`/backlog${qs}`)
      if (data.success) setMovimientos(data.data)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [banco, estado])

  useEffect(() => { fetchBacklog() }, [fetchBacklog])

  useEffect(() => {
    apiGet<{ success: boolean; data: CuentaAlegra[] }>('/alegra/cuentas')
      .then(res => { if (res.success && res.data.length > 0) setCuentas(res.data) })
      .catch(() => {})
  }, [])

  const cuentasFiltradas = cuentaSearch
    ? cuentas.filter(c => `${c.id} ${c.nombre} ${c.codigo}`.toLowerCase().includes(cuentaSearch.toLowerCase()))
    : cuentas

  const bancosCuentas = cuentas.filter(c => c.es_banco)

  const elegibles = movimientos.filter(m => (m as any).confianza_v1 >= 0.70).length

  async function startBatch() {
    setShowBatchConfirm(false)
    try {
      const res = await apiPost<{success: boolean, job_id: string, total_elegibles: number}>('/backlog/causar-batch', { confianza_minima: 0.70 })
      if (res.success && res.total_elegibles > 0) {
        setBatchJobId(res.job_id)
        pollJob(res.job_id)
      }
    } catch (err) {
      // silent
    }
  }

  function pollJob(jobId: string) {
    const interval = setInterval(async () => {
      try {
        const res = await apiGet<{success: boolean, estado: string, total: number, procesados: number, exitosos: number, errores: number}>(`/backlog/job/${jobId}`)
        if (res.success) {
          setBatchStatus(res)
          if (res.estado === 'completado') {
            clearInterval(interval)
            setTimeout(() => { setBatchJobId(null); setBatchStatus(null); fetchBacklog() }, 3000)
          }
        }
      } catch {
        clearInterval(interval)
      }
    }, 2000)
  }

  async function handleCausar() {
    if (!causarTarget) return
    setCausarLoading(true)
    setCausarError('')
    try {
      let data: { success: boolean; error?: string }
      if (tipoOperacion === 'transferencia') {
        data = await apiPost<{ success: boolean; error?: string }>(
          `/backlog/${causarTarget._id}/causar-transferencia`, {
            cuenta_origen: cuentaOrigen,
            cuenta_destino: cuentaDestino,
          }
        )
      } else {
        data = await apiPost<{ success: boolean; error?: string }>(
          `/backlog/${causarTarget._id}/causar?cuenta_id=${cuentaId}&retefuente=${retefuente}&reteica=${reteica}`, {}
        )
      }
      if (data.success) {
        setCausarTarget(null)
        setTipoOperacion('gasto')
        fetchBacklog()
      } else {
        setCausarError(data.error || 'Error al causar')
      }
    } catch (err) {
      setCausarError(err instanceof Error ? err.message : 'Error')
    } finally {
      setCausarLoading(false)
    }
  }

  const pendientes = movimientos.length

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* Header */}
      <div className="px-6 pt-6 pb-4">
        <h1 className="font-display text-lg font-bold text-on-surface">Conciliacion</h1>
        <p className="text-sm text-on-surface-variant mt-1">Movimientos pendientes de causar</p>
      </div>

      {/* Metrics */}
      <div className="px-6 pb-4 flex gap-4">
        <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-5 py-3 flex-1">
          <div className="text-xs text-on-surface-variant">Pendientes</div>
          <div className="font-display text-2xl font-bold text-on-surface">{pendientes}</div>
        </div>
        <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-5 py-3 flex-1">
          <div className="text-xs text-on-surface-variant">Monto total</div>
          <div className="font-display text-2xl font-bold text-on-surface">
            ${movimientos.reduce((s, m) => s + m.monto, 0).toLocaleString('es-CO')}
          </div>
        </div>
      </div>

      {/* Batch causar button */}
      <div className="px-6 pb-4">
        {batchJobId && batchStatus ? (
          <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg p-4">
            <div className="flex justify-between text-sm mb-2">
              <span className="text-on-surface font-medium">Causando automaticos...</span>
              <span className="text-on-surface-variant">{batchStatus.procesados}/{batchStatus.total}</span>
            </div>
            <div className="w-full bg-surface-container-low rounded-full h-2">
              <div className="bg-primary h-2 rounded-full transition-all" style={{width: `${batchStatus.total > 0 ? (batchStatus.procesados / batchStatus.total) * 100 : 0}%`}} />
            </div>
            {batchStatus.estado === 'completado' && (
              <div className="mt-2 text-xs text-on-surface-variant">
                {batchStatus.exitosos} causados, {batchStatus.errores} errores
              </div>
            )}
          </div>
        ) : (
          <button
            onClick={() => setShowBatchConfirm(true)}
            disabled={elegibles === 0}
            className="px-4 py-2 text-sm bg-primary text-white rounded-md hover:brightness-110 disabled:opacity-30 transition-all"
          >
            Causar Automaticos ({elegibles} elegibles)
          </button>
        )}
      </div>

      {/* Estado filter */}
      <div className="px-6 pb-2 flex gap-2">
        {[
          { value: 'pendiente', label: 'Pendientes' },
          { value: 'causado', label: 'Causados' },
          { value: 'error', label: 'Con error' },
        ].map(({ value, label }) => (
          <button
            key={value}
            onClick={() => setEstado(value)}
            className={`px-4 py-1.5 text-xs rounded-md transition-colors ${
              estado === value ? 'bg-primary text-white' : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-lowest'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Banco filter tabs */}
      <div className="px-6 pb-4 flex gap-2 flex-wrap">
        <button
          onClick={() => setBanco('')}
          className={`px-4 py-2 text-xs rounded-md transition-colors ${
            banco === '' ? 'bg-primary/20 text-primary font-medium' : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-lowest'
          }`}
        >
          Todos los bancos
        </button>
        {BANCOS.map((b) => (
          <button
            key={b}
            onClick={() => setBanco(b)}
            className={`px-4 py-2 text-xs rounded-md transition-colors ${
              banco === b ? 'bg-primary/20 text-primary font-medium' : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-lowest'
            }`}
          >
            {b}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-y-auto px-6">
        {loading ? (
          <p className="text-on-surface-variant text-sm py-8 text-center">Cargando...</p>
        ) : movimientos.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-on-surface-variant text-sm">No hay movimientos pendientes</div>
          </div>
        ) : (
          <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-surface-container-low">
                  <th className="text-left px-4 py-3 text-xs font-medium text-on-surface-variant uppercase tracking-wider">Fecha</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-on-surface-variant uppercase tracking-wider">Banco</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-on-surface-variant uppercase tracking-wider">Descripcion</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-on-surface-variant uppercase tracking-wider">Monto</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-on-surface-variant uppercase tracking-wider">Razon</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {movimientos.map((m) => (
                  <tr key={m._id} className="hover:bg-surface-container-low/50 transition-colors">
                    <td className="px-4 py-3 text-on-surface">{m.fecha}</td>
                    <td className="px-4 py-3 text-on-surface">{m.banco}</td>
                    <td className="px-4 py-3 text-on-surface max-w-[280px] truncate">{m.descripcion}</td>
                    <td className="px-4 py-3 text-right font-mono text-on-surface">${m.monto.toLocaleString('es-CO')}</td>
                    <td className="px-4 py-3 text-xs text-on-surface-variant">{m.razon_pendiente}</td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => {
                          setCausarTarget(m)
                          setCausarError('')
                          setTipoOperacion('gasto')
                          const bancoMap: Record<string, string> = {
                            'Bancolombia': '5314', 'BBVA': '5318', 'Davivienda': '5322',
                            'Nequi': '5314', 'Global66': '5536',
                          }
                          const origen = bancoMap[m.banco] || '5314'
                          setCuentaOrigen(origen)
                          // Pre-select a different bank as destino
                          const destinos = Object.values(bancoMap).filter(v => v !== origen)
                          setCuentaDestino(destinos[0] || '5314')
                        }}
                        className="px-3 py-1.5 text-xs bg-primary text-white rounded-md hover:brightness-110 transition-all"
                      >
                        Causar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Batch Confirm Modal */}
      {showBatchConfirm && (
        <div className="fixed inset-0 bg-on-surface/30 flex items-center justify-center z-50">
          <div className="glass shadow-ambient-3 rounded-lg p-6 max-w-sm mx-4">
            <h3 className="font-display font-bold text-on-surface mb-3">Causar Automaticos</h3>
            <p className="text-sm text-on-surface-variant mb-5">
              Se van a causar {elegibles} movimientos con confianza &ge;70% automaticamente en Alegra. Esta accion no se puede deshacer.
            </p>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowBatchConfirm(false)}
                className="px-4 py-2.5 text-sm text-on-surface-variant bg-surface-container-low rounded-md hover:bg-surface transition-colors">
                Cancelar
              </button>
              <button onClick={startBatch}
                className="px-5 py-2.5 text-sm bg-primary text-white rounded-md hover:brightness-110 transition-all">
                Confirmar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Causar Modal — Glass */}
      {causarTarget && (
        <div className="fixed inset-0 bg-on-surface/30 flex items-center justify-center z-50">
          <div className="glass shadow-ambient-3 rounded-lg p-6 max-w-md w-full mx-4">
            <h3 className="font-display font-bold text-on-surface mb-4">Causar Movimiento</h3>
            <div className="text-sm space-y-1.5 mb-5 text-on-surface-variant">
              <p><span className="font-medium text-on-surface">Fecha:</span> {causarTarget.fecha}</p>
              <p><span className="font-medium text-on-surface">Banco:</span> {causarTarget.banco}</p>
              <p><span className="font-medium text-on-surface">Descripcion:</span> {causarTarget.descripcion}</p>
              <p><span className="font-medium text-on-surface">Monto:</span> ${causarTarget.monto.toLocaleString('es-CO')}</p>
            </div>

            {/* Tipo de operacion */}
            <div className="flex gap-2 mb-4">
              <button
                onClick={() => setTipoOperacion('gasto')}
                className={`flex-1 py-2 text-xs rounded-md transition-colors ${
                  tipoOperacion === 'gasto' ? 'bg-primary text-white' : 'bg-surface-container-low text-on-surface-variant'
                }`}
              >
                Gasto / Ingreso
              </button>
              <button
                onClick={() => setTipoOperacion('transferencia')}
                className={`flex-1 py-2 text-xs rounded-md transition-colors ${
                  tipoOperacion === 'transferencia' ? 'bg-primary text-white' : 'bg-surface-container-low text-on-surface-variant'
                }`}
              >
                Transferencia entre cuentas
              </button>
            </div>

            {tipoOperacion === 'transferencia' ? (
              <>
                <label className="block text-xs font-medium text-on-surface-variant uppercase tracking-wider mb-2">Banco origen</label>
                <select value={cuentaOrigen} onChange={(e) => setCuentaOrigen(e.target.value)}
                  className="w-full px-3 py-2.5 bg-surface-container-low rounded-md text-sm text-on-surface mb-4 focus:outline-none focus:ring-2 focus:ring-primary/30">
                  {bancosCuentas.map(c => (
                    <option key={c.id} value={c.id}>{c.id} — {c.nombre} ({c.codigo})</option>
                  ))}
                </select>
                <label className="block text-xs font-medium text-on-surface-variant uppercase tracking-wider mb-2">Banco destino</label>
                <select value={cuentaDestino} onChange={(e) => setCuentaDestino(e.target.value)}
                  className="w-full px-3 py-2.5 bg-surface-container-low rounded-md text-sm text-on-surface mb-5 focus:outline-none focus:ring-2 focus:ring-primary/30">
                  {bancosCuentas.map(c => (
                    <option key={c.id} value={c.id}>{c.id} — {c.nombre} ({c.codigo})</option>
                  ))}
                </select>
              </>
            ) : (
              <>
                <label className="block text-xs font-medium text-on-surface-variant uppercase tracking-wider mb-2">Cuenta contable</label>
                <input
                  type="text"
                  value={cuentaSearch}
                  onChange={(e) => setCuentaSearch(e.target.value)}
                  placeholder="Buscar cuenta..."
                  className="w-full px-3 py-2 bg-surface-container-low rounded-md text-sm text-on-surface mb-1 focus:outline-none focus:ring-2 focus:ring-primary/30"
                />
                <select
                  value={cuentaId}
                  onChange={(e) => setCuentaId(e.target.value)}
                  size={Math.min(cuentasFiltradas.length, 6)}
                  className="w-full px-3 py-1 bg-surface-container-low rounded-md text-sm text-on-surface mb-4 focus:outline-none focus:ring-2 focus:ring-primary/30"
                >
                  {cuentasFiltradas.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.id} — {c.id === '5494' ? 'Gastos Varios' : c.nombre} ({c.codigo})
                    </option>
                  ))}
                </select>

                <div className="grid grid-cols-2 gap-3 mb-5">
                  <div>
                    <label className="block text-xs font-medium text-on-surface-variant uppercase tracking-wider mb-2">ReteFuente ($)</label>
                    <input type="number" value={retefuente} onChange={(e) => setRetefuente(Number(e.target.value))}
                      className="w-full px-3 py-2.5 bg-surface-container-low rounded-md text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30" />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-on-surface-variant uppercase tracking-wider mb-2">ReteICA ($)</label>
                    <input type="number" value={reteica} onChange={(e) => setReteica(Number(e.target.value))}
                      className="w-full px-3 py-2.5 bg-surface-container-low rounded-md text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary/30" />
                  </div>
                </div>
              </>
            )}

            {causarError && <p className="text-sm text-error mb-4">{causarError}</p>}

            <div className="flex gap-3 justify-end">
              <button onClick={() => { setCausarTarget(null); setTipoOperacion('gasto') }} disabled={causarLoading}
                className="px-4 py-2.5 text-sm text-on-surface-variant bg-surface-container-low rounded-md hover:bg-surface transition-colors">
                Cancelar
              </button>
              <button onClick={handleCausar} disabled={causarLoading}
                className="px-5 py-2.5 text-sm bg-primary text-white rounded-md hover:brightness-110 disabled:opacity-50 transition-all">
                {causarLoading ? 'Causando...' : 'Confirmar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
