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
}

const CUENTAS_RODDOS = [
  { id: '5480', label: 'Arrendamientos (512010)' },
  { id: '5485', label: 'Acueducto (513525)' },
  { id: '5487', label: 'Telefono/Internet (513535)' },
  { id: '5492', label: 'Construcciones (514510)' },
  { id: '5497', label: 'Utiles papeleria (519530)' },
  { id: '5494', label: 'FALLBACK Deudores (51991001)' },
  { id: '5462', label: 'Sueldos (510506)' },
  { id: '5475', label: 'Asesoria juridica (511025)' },
  { id: '5499', label: 'Taxis y buses (519545)' },
  { id: '5508', label: 'Comisiones bancarias (530515)' },
  { id: '5507', label: 'Gastos bancarios (530505)' },
  { id: '5509', label: 'Gravamen 4x1000 (531520)' },
]

export default function BacklogPage() {
  const [movimientos, setMovimientos] = useState<BacklogMovimiento[]>([])
  const [loading, setLoading] = useState(true)
  const [banco, setBanco] = useState('')
  const [causarTarget, setCausarTarget] = useState<BacklogMovimiento | null>(null)
  const [cuentaId, setCuentaId] = useState('5494')
  const [retefuente, setRetefuente] = useState(0)
  const [reteica, setReteica] = useState(0)
  const [causarLoading, setCausarLoading] = useState(false)
  const [causarError, setCausarError] = useState('')

  const fetchBacklog = useCallback(async () => {
    setLoading(true)
    try {
      const params = banco ? `?banco=${banco}` : ''
      const data = await apiGet<{ success: boolean; data: BacklogMovimiento[] }>(`/backlog${params}`)
      if (data.success) setMovimientos(data.data)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [banco])

  useEffect(() => { fetchBacklog() }, [fetchBacklog])

  async function handleCausar() {
    if (!causarTarget) return
    setCausarLoading(true)
    setCausarError('')
    try {
      const data = await apiPost<{ success: boolean; error?: string }>(`/backlog/${causarTarget._id}/causar?cuenta_id=${cuentaId}&retefuente=${retefuente}&reteica=${reteica}`, {})
      if (data.success) {
        setCausarTarget(null)
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

  return (
    <div className="p-6">
      <h1 className="text-lg font-semibold text-neutral-900 mb-4">Backlog — Movimientos Pendientes</h1>

      <div className="flex gap-3 mb-4">
        <select
          value={banco}
          onChange={(e) => setBanco(e.target.value)}
          className="px-3 py-2 border border-neutral-300 rounded text-sm"
        >
          <option value="">Todos los bancos</option>
          <option value="Bancolombia">Bancolombia</option>
          <option value="BBVA">BBVA</option>
          <option value="Davivienda">Davivienda</option>
          <option value="Nequi">Nequi</option>
        </select>
        <button onClick={fetchBacklog} className="px-3 py-2 text-sm border border-neutral-300 rounded hover:bg-neutral-50">
          Refrescar
        </button>
      </div>

      {loading ? (
        <p className="text-neutral-500">Cargando...</p>
      ) : movimientos.length === 0 ? (
        <p className="text-neutral-500">No hay movimientos pendientes.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b-2 border-neutral-200">
                <th className="text-left p-2">Fecha</th>
                <th className="text-left p-2">Banco</th>
                <th className="text-left p-2">Descripcion</th>
                <th className="text-right p-2">Monto</th>
                <th className="text-left p-2">Razon</th>
                <th className="text-center p-2">Int.</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {movimientos.map((m) => (
                <tr key={m._id} className="border-b border-neutral-100 hover:bg-neutral-50">
                  <td className="p-2">{m.fecha}</td>
                  <td className="p-2">{m.banco}</td>
                  <td className="p-2 max-w-[300px] truncate">{m.descripcion}</td>
                  <td className="p-2 text-right">${m.monto.toLocaleString('es-CO')}</td>
                  <td className="p-2 text-xs text-neutral-500">{m.razon_pendiente}</td>
                  <td className="p-2 text-center">{m.intentos}</td>
                  <td className="p-2">
                    <button
                      onClick={() => { setCausarTarget(m); setCausarError('') }}
                      className="px-3 py-1 text-xs bg-neutral-900 text-white rounded hover:bg-neutral-800"
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

      {/* Causar Modal */}
      {causarTarget && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
            <h3 className="font-semibold text-neutral-900 mb-3">Causar Movimiento</h3>
            <div className="text-sm space-y-1 mb-4 text-neutral-600">
              <p><span className="font-medium">Fecha:</span> {causarTarget.fecha}</p>
              <p><span className="font-medium">Banco:</span> {causarTarget.banco}</p>
              <p><span className="font-medium">Descripcion:</span> {causarTarget.descripcion}</p>
              <p><span className="font-medium">Monto:</span> ${causarTarget.monto.toLocaleString('es-CO')}</p>
            </div>

            <label className="block text-sm text-neutral-600 mb-1">Cuenta contable</label>
            <select
              value={cuentaId}
              onChange={(e) => setCuentaId(e.target.value)}
              className="w-full px-3 py-2 border border-neutral-300 rounded text-sm mb-3"
            >
              {CUENTAS_RODDOS.map((c) => (
                <option key={c.id} value={c.id}>{c.id} — {c.label}</option>
              ))}
            </select>

            <div className="grid grid-cols-2 gap-3 mb-4">
              <div>
                <label className="block text-sm text-neutral-600 mb-1">ReteFuente ($)</label>
                <input type="number" value={retefuente} onChange={(e) => setRetefuente(Number(e.target.value))}
                  className="w-full px-3 py-2 border border-neutral-300 rounded text-sm" />
              </div>
              <div>
                <label className="block text-sm text-neutral-600 mb-1">ReteICA ($)</label>
                <input type="number" value={reteica} onChange={(e) => setReteica(Number(e.target.value))}
                  className="w-full px-3 py-2 border border-neutral-300 rounded text-sm" />
              </div>
            </div>

            {causarError && <p className="text-sm text-red-600 mb-3">{causarError}</p>}

            <div className="flex gap-3 justify-end">
              <button onClick={() => setCausarTarget(null)} disabled={causarLoading}
                className="px-4 py-2 text-sm border border-neutral-300 rounded hover:bg-neutral-50">
                Cancelar
              </button>
              <button onClick={handleCausar} disabled={causarLoading}
                className="px-4 py-2 text-sm bg-neutral-900 text-white rounded hover:bg-neutral-800 disabled:opacity-50">
                {causarLoading ? 'Causando...' : 'Confirmar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
