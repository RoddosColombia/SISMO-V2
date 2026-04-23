import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'

// ─── Types ────────────────────────────────────────────────────────────────────

type EstadoGestion = 'pendiente' | 'contactado' | 'acuerdo' | 'pagó'

interface CreditoSinPago {
  loanbook_id: string
  cliente_nombre: string
  telefono: string
  saldo: number
  cuotas_vencidas: number
  dpd: number
  sub_bucket: string | null
  estado_gestion: EstadoGestion
  notas: string
  actualizado_por: string | null
  actualizado_at: string | null
}

interface Informe {
  semana_id: string
  fecha_corte: string
  fecha_generacion: string
  generado_por: string
  sin_pago: CreditoSinPago[]
  total_sin_pago: number
  valor_en_riesgo: number
  notas_generales: string
}

interface HistorialEntry {
  semana_id: string
  fecha_corte: string
  total_sin_pago: number
  valor_en_riesgo: number
  generado_por: string
}

// ─── Colores estado gestión ───────────────────────────────────────────────────

const ESTADO_COLORS: Record<EstadoGestion, string> = {
  pendiente:   'bg-yellow-100 text-yellow-800',
  contactado:  'bg-blue-100 text-blue-700',
  acuerdo:     'bg-orange-100 text-orange-700',
  'pagó':      'bg-green-100 text-green-700',
}

const ESTADOS: EstadoGestion[] = ['pendiente', 'contactado', 'acuerdo', 'pagó']

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmt(n: number) {
  return '$' + Math.round(n).toLocaleString('es-CO')
}

function apiHeaders() {
  return {
    Authorization: `Bearer ${localStorage.getItem('token')}`,
    'Content-Type': 'application/json',
  }
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function InformePage() {
  const navigate = useNavigate()

  const [informe, setInforme] = useState<Informe | null>(null)
  const [historial, setHistorial] = useState<HistorialEntry[]>([])
  const [semanaSeleccionada, setSemanaSeleccionada] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [generando, setGenerando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editandoNotas, setEditandoNotas] = useState(false)
  const [notasGenerales, setNotasGenerales] = useState('')

  // Cargar informe para una semana concreta (o semana-actual si no se especifica)
  const cargarInforme = useCallback(async (semana?: string) => {
    setLoading(true)
    setError(null)
    try {
      const url = semana
        ? `/api/informes/semana/${semana}`
        : '/api/informes/semana-actual'
      const res = await fetch(url, { headers: apiHeaders() })
      if (!res.ok) {
        if (res.status === 404) {
          setInforme(null)
          return
        }
        throw new Error('Error cargando informe')
      }
      const raw = await res.json()
      // Guard: el backend puede devolver {} si hubo un edge case post-inserción.
      // Si no tiene semana_id válido, tratar como 404.
      if (!raw?.semana_id) {
        setInforme(null)
        return
      }
      const data: Informe = {
        ...raw,
        sin_pago: Array.isArray(raw.sin_pago) ? raw.sin_pago : [],
        notas_generales: raw.notas_generales ?? '',
        total_sin_pago: raw.total_sin_pago ?? 0,
        valor_en_riesgo: raw.valor_en_riesgo ?? 0,
      }
      console.log('[InformePage] informe recibido:', JSON.stringify(data.sin_pago?.[0]))
      setInforme(data)
      setNotasGenerales(data.notas_generales)
      setSemanaSeleccionada(data.semana_id)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  // Cargar historial y retornarlo (para encadenar con cargarInforme)
  const cargarHistorial = useCallback(async (): Promise<HistorialEntry[]> => {
    try {
      const res = await fetch('/api/informes/historial', { headers: apiHeaders() })
      if (!res.ok) return []
      const data: HistorialEntry[] = await res.json()
      setHistorial(data)
      return data
    } catch {
      return []
    }
  }, [])

  // Montar: hit /semana-actual PRIMERO (activa stale detection del backend),
  // luego cargar historial para el selector. El orden importa: si cargamos
  // hist[0].semana_id primero, llamamos /semana/{id} que NO tiene stale detection
  // y retorna el snapshot viejo con dpd=0.
  useEffect(() => {
    const init = async () => {
      await cargarInforme(undefined)  // /semana-actual → detecta stale → regenera
      await cargarHistorial()         // historial ya tiene el informe refrescado
    }
    init()
  }, [])

  // Selector de semana: el usuario elige manualmente — no hay useEffect extra
  const handleSemanaChange = useCallback(async (semana: string) => {
    setSemanaSeleccionada(semana)
    await cargarInforme(semana)
  }, [cargarInforme])

  // Generar informe manual: refrescar historial + informe inmediatamente
  const handleGenerar = async () => {
    setGenerando(true)
    try {
      const res = await fetch('/api/informes/generar?forzar=true', {
        method: 'POST',
        headers: apiHeaders(),
      })
      if (!res.ok) throw new Error('Error generando informe')
      // Refrescar historial primero (puede haber semana nueva)
      const hist = await cargarHistorial()
      const semana = semanaSeleccionada || hist[0]?.semana_id
      await cargarInforme(semana)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setGenerando(false)
    }
  }

  // Actualizar estado gestión de un crédito
  const handleEstadoGestion = async (loanbook_id: string, estado_gestion: EstadoGestion) => {
    if (!informe) return
    await fetch(`/api/informes/semana/${informe.semana_id}/credito/${loanbook_id}`, {
      method: 'PATCH',
      headers: apiHeaders(),
      body: JSON.stringify({ estado_gestion }),
    })
    setInforme(prev => prev ? {
      ...prev,
      sin_pago: prev.sin_pago.map(c =>
        c.loanbook_id === loanbook_id ? { ...c, estado_gestion } : c
      ),
    } : null)
  }

  // Actualizar notas de un crédito (inline)
  const handleNotas = async (loanbook_id: string, notas: string) => {
    if (!informe) return
    await fetch(`/api/informes/semana/${informe.semana_id}/credito/${loanbook_id}`, {
      method: 'PATCH',
      headers: apiHeaders(),
      body: JSON.stringify({ notas }),
    })
    setInforme(prev => prev ? {
      ...prev,
      sin_pago: prev.sin_pago.map(c =>
        c.loanbook_id === loanbook_id ? { ...c, notas } : c
      ),
    } : null)
  }

  // Guardar notas generales
  const handleGuardarNotasGenerales = async () => {
    if (!informe) return
    await fetch(`/api/informes/semana/${informe.semana_id}/notas`, {
      method: 'PATCH',
      headers: apiHeaders(),
      body: JSON.stringify({ notas_generales: notasGenerales }),
    })
    setInforme(prev => prev ? { ...prev, notas_generales: notasGenerales } : null)
    setEditandoNotas(false)
  }

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* Header */}
      <div className="px-6 pt-6 pb-4 border-b border-surface-container">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/loanbook')}
              className="text-on-surface-variant hover:text-on-surface"
            >
              ←
            </button>
            <div>
              <h1 className="font-display text-lg font-bold text-on-surface">
                Informe Semanal
              </h1>
              <p className="text-sm text-on-surface-variant mt-0.5">
                Créditos sin pago — gestión de cobranza
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Selector de semana */}
            {historial.length > 0 && (
              <select
                value={semanaSeleccionada}
                onChange={e => handleSemanaChange(e.target.value)}
                className="text-xs border border-surface-container rounded-lg px-2 py-1.5 bg-surface-container-low text-on-surface"
              >
                {historial.map(h => (
                  <option key={h.semana_id} value={h.semana_id}>
                    {h.semana_id} — {h.total_sin_pago} sin pago
                  </option>
                ))}
              </select>
            )}

            <button
              onClick={handleGenerar}
              disabled={generando}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-container-low text-on-surface-variant hover:bg-surface-container hover:text-on-surface transition-colors disabled:opacity-50"
            >
              {generando ? (
                <span className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />
              ) : '↻'}
              Generar
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {error && (
          <div className="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">{error}</div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-32">
            <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : !informe ? (
          <div className="text-center py-16 text-on-surface-variant">
            <p className="text-sm">No hay informe para esta semana.</p>
            <button
              onClick={handleGenerar}
              className="mt-3 px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary/90"
            >
              Generar ahora
            </button>
          </div>
        ) : (
          <>
            {/* Banner: informe desactualizado — DPD=0 con cuotas vencidas indica snapshot viejo */}
            {(informe.sin_pago ?? []).some(c => c.dpd === 0 && c.cuotas_vencidas > 0) && (
              <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg flex items-center justify-between">
                <p className="text-xs text-amber-800">
                  ⚠️ El informe tiene DPD=0 para créditos con cuotas vencidas. Los datos pueden estar desactualizados — regénera para ver los valores correctos.
                </p>
                <button
                  onClick={handleGenerar}
                  disabled={generando}
                  className="ml-3 px-3 py-1 text-xs font-medium bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50 shrink-0"
                >
                  Regenerar ahora
                </button>
              </div>
            )}
            {/* Resumen */}
            <div className="grid grid-cols-3 gap-3 mb-4">
              <div className="bg-surface-container-low rounded-xl p-4">
                <p className="text-xs text-on-surface-variant mb-1">Sin pago esta semana</p>
                <p className="text-2xl font-bold text-on-surface">{informe.total_sin_pago}</p>
                <p className="text-xs text-on-surface-variant mt-1">créditos</p>
              </div>
              <div className="bg-surface-container-low rounded-xl p-4">
                <p className="text-xs text-on-surface-variant mb-1">Valor en riesgo</p>
                <p className="text-xl font-bold text-red-600">{fmt(informe.valor_en_riesgo)}</p>
                <p className="text-xs text-on-surface-variant mt-1">saldo total</p>
              </div>
              <div className="bg-surface-container-low rounded-xl p-4">
                <p className="text-xs text-on-surface-variant mb-1">Notas generales</p>
                {editandoNotas ? (
                  <div className="flex flex-col gap-1">
                    <textarea
                      className="text-xs border rounded p-1 w-full resize-none"
                      rows={2}
                      value={notasGenerales}
                      onChange={e => setNotasGenerales(e.target.value)}
                      autoFocus
                    />
                    <div className="flex gap-1">
                      <button onClick={handleGuardarNotasGenerales} className="text-xs text-blue-600 hover:underline">Guardar</button>
                      <button onClick={() => setEditandoNotas(false)} className="text-xs text-gray-400 hover:underline">Cancelar</button>
                    </div>
                  </div>
                ) : (
                  <div
                    className="text-xs text-on-surface cursor-pointer hover:text-primary min-h-[2.5rem]"
                    onClick={() => setEditandoNotas(true)}
                    title="Click para editar"
                  >
                    {informe.notas_generales || <span className="text-on-surface-variant italic">Sin notas — click para añadir</span>}
                  </div>
                )}
              </div>
            </div>

            {/* Tabla */}
            {(() => { console.log('sin_pago[0]:', informe?.sin_pago?.[0]); return null })()}
            {(!informe || !Array.isArray(informe.sin_pago)) ? (
              <div className="p-8 text-center text-on-surface-variant text-sm">Cargando datos del informe...</div>
            ) : (
            <div className="bg-surface-container-lowest rounded-xl overflow-hidden shadow-ambient-1">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-surface-container text-xs text-on-surface-variant">
                    <th className="text-left px-4 py-3 font-medium">Cliente</th>
                    <th className="text-left px-3 py-3 font-medium">Teléfono</th>
                    <th className="text-right px-3 py-3 font-medium">DPD</th>
                    <th className="text-left px-3 py-3 font-medium">Bucket</th>
                    <th className="text-right px-3 py-3 font-medium">Saldo</th>
                    <th className="text-right px-3 py-3 font-medium">Vencidas</th>
                    <th className="text-left px-3 py-3 font-medium">Estado gestión</th>
                    <th className="text-left px-3 py-3 font-medium">Notas</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-container">
                  {(informe.sin_pago ?? []).map(credito => (
                    <tr
                      key={credito.loanbook_id}
                      className="hover:bg-surface-container/50 transition-colors"
                    >
                      <td className="px-4 py-3">
                        <div className="font-medium text-on-surface leading-tight">
                          {credito.cliente_nombre || '—'}
                        </div>
                        <div className="text-xs text-on-surface-variant">{credito.loanbook_id}</div>
                      </td>
                      <td className="px-3 py-3 text-on-surface-variant">{credito.telefono || '—'}</td>
                      <td className="px-3 py-3 text-right">
                        <span className={`font-mono text-xs font-medium ${credito.dpd > 30 ? 'text-red-600' : credito.dpd > 7 ? 'text-orange-600' : 'text-yellow-600'}`}>
                          {credito.dpd}d
                        </span>
                      </td>
                      <td className="px-3 py-3 text-xs text-on-surface-variant">{credito.sub_bucket || '—'}</td>
                      <td className="px-3 py-3 text-right font-mono text-xs">{fmt(credito.saldo)}</td>
                      <td className="px-3 py-3 text-right text-xs text-on-surface-variant">{credito.cuotas_vencidas}</td>
                      <td className="px-3 py-3">
                        <select
                          value={credito.estado_gestion}
                          onChange={e => handleEstadoGestion(credito.loanbook_id, e.target.value as EstadoGestion)}
                          className={`text-xs px-2 py-1 rounded-full border-0 font-medium cursor-pointer ${ESTADO_COLORS[credito.estado_gestion]}`}
                        >
                          {ESTADOS.map(e => (
                            <option key={e} value={e}>{e}</option>
                          ))}
                        </select>
                      </td>
                      <td className="px-3 py-3">
                        <input
                          type="text"
                          value={credito.notas ?? ''}
                          onChange={e => {
                            const val = e.target.value
                            setInforme(prev => prev ? {
                              ...prev,
                              sin_pago: prev.sin_pago.map(c =>
                                c.loanbook_id === credito.loanbook_id ? { ...c, notas: val } : c
                              ),
                            } : null)
                          }}
                          onBlur={e => handleNotas(credito.loanbook_id, e.target.value)}
                          placeholder="Añadir nota..."
                          className="text-xs border border-transparent rounded px-1.5 py-1 w-full bg-transparent hover:border-surface-container focus:border-primary focus:outline-none focus:bg-white"
                        />
                      </td>
                    </tr>
                  ))}
                  {(informe.sin_pago ?? []).length === 0 && (
                    <tr>
                      <td colSpan={8} className="text-center py-8 text-sm text-on-surface-variant">
                        Todos los créditos al día esta semana.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
