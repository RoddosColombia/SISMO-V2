import { useState, useEffect, useCallback } from 'react'
import { apiGet } from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface PagoRegistrado {
  fecha?: string
  monto?: number
  alegra_journal_id?: string
}

interface CreditoLegacy {
  codigo_sismo: string
  cedula: string
  numero_credito_original: string
  nombre_completo: string
  placa?: string
  aliado: string
  estado: string
  estado_legacy_excel: string
  saldo_actual: number
  saldo_inicial: number
  dias_mora_maxima?: number
  pct_on_time?: number
  score_total?: number
  decision_historica?: string
  analisis_texto?: string
  alegra_contact_id?: string
  pagos_recibidos?: PagoRegistrado[]
}

interface Stats {
  total_creditos?: number
  saldo_total?: number
  activos?: number
  saldados?: number
  castigados?: number
  en_mora?: number
  al_dia?: number
  por_aliado?: { aliado: string; count: number; saldo: number }[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const COP = (n: number) =>
  n.toLocaleString('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 })

const pctFmt = (v?: number) =>
  v != null ? `${(v * 100).toFixed(0)}%` : '—'

const estadoBadge = (excel: string) => {
  const mora = excel === 'En Mora'
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        mora
          ? 'bg-error/10 text-error'
          : 'bg-primary/10 text-primary'
      }`}
    >
      {excel}
    </span>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function CarteraLegacyPage() {
  const [stats, setStats]         = useState<Stats>({})
  const [creditos, setCreditos]   = useState<CreditoLegacy[]>([])
  const [total, setTotal]         = useState(0)
  const [page, setPage]           = useState(1)
  const [loading, setLoading]     = useState(true)
  const [statsLoading, setStatsLoading] = useState(true)
  const [error, setError]         = useState('')

  // Filters
  const [estado, setEstado]     = useState('')
  const [aliado, setAliado]     = useState('')
  const [enMora, setEnMora]     = useState('')   // '' | 'true' | 'false'

  // Drawer
  const [selected, setSelected] = useState<CreditoLegacy | null>(null)
  const [detalle, setDetalle]   = useState<CreditoLegacy | null>(null)
  const [detalleLoading, setDetalleLoading] = useState(false)

  const LIMIT = 50

  // ── Stats ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    setStatsLoading(true)
    apiGet<{ success: boolean; data: Stats }>('/cartera-legacy/stats')
      .then(r => setStats(r.data ?? {}))
      .catch(() => {/* silent */})
      .finally(() => setStatsLoading(false))
  }, [])

  // ── List ───────────────────────────────────────────────────────────────────
  const fetchList = useCallback(async (p = 1) => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ page: String(p), limit: String(LIMIT) })
      if (estado)  params.set('estado', estado)
      if (aliado)  params.set('aliado', aliado)
      if (enMora)  params.set('en_mora', enMora)

      const r = await apiGet<{ success: boolean; data: CreditoLegacy[]; total: number }>(
        `/cartera-legacy?${params}`
      )
      setCreditos(r.data ?? [])
      setTotal(r.total ?? 0)
      setPage(p)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error al cargar')
    } finally {
      setLoading(false)
    }
  }, [estado, aliado, enMora])

  useEffect(() => { fetchList(1) }, [fetchList])

  // ── Drawer detail ──────────────────────────────────────────────────────────
  const openDetalle = async (c: CreditoLegacy) => {
    setSelected(c)
    setDetalle(null)
    setDetalleLoading(true)
    try {
      const r = await apiGet<{ success: boolean; data: CreditoLegacy }>(
        `/cartera-legacy/${c.codigo_sismo}`
      )
      setDetalle(r.data)
    } catch { /* show basic info */ }
    finally { setDetalleLoading(false) }
  }

  const closeDetalle = () => { setSelected(null); setDetalle(null) }

  const pages = Math.max(1, Math.ceil(total / LIMIT))

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <header className="shrink-0 px-6 py-4 border-b border-surface-container-low bg-surface">
        <h1 className="text-lg font-semibold text-on-surface">Cartera Legacy</h1>
        <p className="text-xs text-on-surface-variant mt-0.5">
          Créditos pre-SISMO · read-only · BUILD 0.1
        </p>
      </header>

      {/* Stat cards */}
      <div className="shrink-0 grid grid-cols-2 sm:grid-cols-4 gap-3 px-6 py-3 bg-surface border-b border-surface-container-low">
        {[
          { label: 'Activos',  value: statsLoading ? '…' : String(stats.activos ?? 0) },
          { label: 'En mora',  value: statsLoading ? '…' : String(stats.en_mora ?? 0) },
          { label: 'Al día',   value: statsLoading ? '…' : String(stats.al_dia ?? 0) },
          {
            label: 'Saldo total',
            value: statsLoading ? '…' : COP(stats.saldo_total ?? 0),
          },
        ].map(c => (
          <div key={c.label} className="bg-surface-container-low rounded-lg px-4 py-3">
            <div className="text-xs text-on-surface-variant">{c.label}</div>
            <div className="text-base font-semibold text-on-surface mt-0.5">{c.value}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="shrink-0 flex flex-wrap gap-2 px-6 py-2 bg-surface border-b border-surface-container-low">
        <select
          value={estado}
          onChange={e => setEstado(e.target.value)}
          className="text-xs border border-surface-container-low rounded-md px-2 py-1.5 bg-surface text-on-surface"
        >
          <option value="">Todos los estados</option>
          <option value="activo">Activo</option>
          <option value="saldado">Saldado</option>
          <option value="castigado">Castigado</option>
        </select>

        <select
          value={aliado}
          onChange={e => setAliado(e.target.value)}
          className="text-xs border border-surface-container-low rounded-md px-2 py-1.5 bg-surface text-on-surface"
        >
          <option value="">Todos los aliados</option>
          <option value="RODDOS_Directo">RODDOS Directo</option>
          <option value="Motai">Motai</option>
          <option value="Yamarinos">Yamarinos</option>
          <option value="MDT">MDT</option>
          <option value="BMR">BMR</option>
          <option value="Sin aliado">Sin aliado</option>
        </select>

        <select
          value={enMora}
          onChange={e => setEnMora(e.target.value)}
          className="text-xs border border-surface-container-low rounded-md px-2 py-1.5 bg-surface text-on-surface"
        >
          <option value="">Al día + En mora</option>
          <option value="false">Solo Al día</option>
          <option value="true">Solo En mora</option>
        </select>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto px-6 py-3">
        {error && (
          <div className="mb-3 rounded-lg bg-error/10 text-error px-4 py-2 text-sm">{error}</div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-32 text-sm text-on-surface-variant">
            Cargando…
          </div>
        ) : creditos.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-sm text-on-surface-variant gap-2">
            <span>Sin datos</span>
            <span className="text-xs">Ejecuta BUILD 0.2 para migrar los créditos.</span>
          </div>
        ) : (
          <>
            <div className="text-xs text-on-surface-variant mb-2">
              {total} crédito{total !== 1 ? 's' : ''} · página {page}/{pages}
            </div>
            <div className="overflow-x-auto rounded-lg border border-surface-container-low">
              <table className="w-full text-xs">
                <thead className="bg-surface-container-low text-on-surface-variant">
                  <tr>
                    {['Código', 'Cliente', 'Cédula', 'Placa', 'Aliado', 'Estado', 'Score', 'Saldo', 'Mora'].map(h => (
                      <th key={h} className="px-3 py-2 text-left font-medium whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-container-low">
                  {creditos.map(c => (
                    <tr
                      key={c.codigo_sismo}
                      onClick={() => openDetalle(c)}
                      className="hover:bg-surface-container-lowest/60 cursor-pointer transition-colors"
                    >
                      <td className="px-3 py-2 font-mono text-on-surface-variant">{c.codigo_sismo}</td>
                      <td className="px-3 py-2 font-medium text-on-surface max-w-[160px] truncate">{c.nombre_completo}</td>
                      <td className="px-3 py-2 text-on-surface-variant">{c.cedula}</td>
                      <td className="px-3 py-2 text-on-surface-variant">{c.placa ?? '—'}</td>
                      <td className="px-3 py-2 text-on-surface-variant">{c.aliado}</td>
                      <td className="px-3 py-2">{estadoBadge(c.estado_legacy_excel)}</td>
                      <td className="px-3 py-2 text-on-surface-variant">{c.score_total?.toFixed(0) ?? '—'}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-on-surface">{COP(c.saldo_actual)}</td>
                      <td className="px-3 py-2 text-right text-on-surface-variant">{c.dias_mora_maxima ?? '—'}d</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {pages > 1 && (
              <div className="flex items-center justify-center gap-2 mt-3">
                <button
                  onClick={() => fetchList(page - 1)}
                  disabled={page <= 1}
                  className="px-3 py-1 text-xs rounded-md border border-surface-container-low disabled:opacity-40 hover:bg-surface-container-lowest/60 transition-colors"
                >
                  ← Anterior
                </button>
                <span className="text-xs text-on-surface-variant">{page} / {pages}</span>
                <button
                  onClick={() => fetchList(page + 1)}
                  disabled={page >= pages}
                  className="px-3 py-1 text-xs rounded-md border border-surface-container-low disabled:opacity-40 hover:bg-surface-container-lowest/60 transition-colors"
                >
                  Siguiente →
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* Drawer */}
      {selected && (
        <div className="fixed inset-0 z-50 flex">
          <div className="flex-1 bg-black/30" onClick={closeDetalle} />
          <aside className="w-full max-w-md bg-surface shadow-xl flex flex-col overflow-hidden">
            {/* Drawer header */}
            <div className="flex items-start justify-between px-5 py-4 border-b border-surface-container-low">
              <div>
                <div className="text-sm font-semibold text-on-surface">{selected.nombre_completo}</div>
                <div className="text-xs text-on-surface-variant font-mono mt-0.5">{selected.codigo_sismo}</div>
              </div>
              <button
                onClick={closeDetalle}
                className="text-on-surface-variant hover:text-on-surface transition-colors"
                aria-label="Cerrar"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Drawer body */}
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
              {detalleLoading ? (
                <div className="text-sm text-on-surface-variant">Cargando detalle…</div>
              ) : (
                <>
                  {/* Key info grid */}
                  <div className="grid grid-cols-2 gap-3">
                    {[
                      ['Cédula',    (detalle ?? selected).cedula],
                      ['Placa',     (detalle ?? selected).placa ?? '—'],
                      ['Aliado',    (detalle ?? selected).aliado],
                      ['Estado Excel', (detalle ?? selected).estado_legacy_excel],
                      ['Saldo actual', COP((detalle ?? selected).saldo_actual)],
                      ['Saldo inicial', COP((detalle ?? selected).saldo_inicial)],
                      ['Score total', (detalle ?? selected).score_total?.toFixed(1) ?? '—'],
                      ['On Time',   pctFmt((detalle ?? selected).pct_on_time)],
                      ['Días mora máx', `${(detalle ?? selected).dias_mora_maxima ?? '—'}d`],
                      ['Alegra ID', (detalle ?? selected).alegra_contact_id ?? 'Sin contacto'],
                    ].map(([label, value]) => (
                      <div key={label} className="bg-surface-container-low rounded-lg px-3 py-2">
                        <div className="text-xs text-on-surface-variant">{label}</div>
                        <div className="text-sm font-medium text-on-surface mt-0.5 truncate">{value}</div>
                      </div>
                    ))}
                  </div>

                  {/* Decisión */}
                  {(detalle ?? selected).decision_historica && (
                    <div className="bg-surface-container-low rounded-lg px-3 py-2">
                      <div className="text-xs text-on-surface-variant mb-1">Decisión scoring</div>
                      <div className="text-sm font-semibold text-on-surface">
                        {(detalle ?? selected).decision_historica}
                      </div>
                    </div>
                  )}

                  {/* Análisis */}
                  {(detalle ?? selected).analisis_texto && (
                    <div className="bg-surface-container-low rounded-lg px-3 py-2">
                      <div className="text-xs text-on-surface-variant mb-1">Análisis</div>
                      <p className="text-xs text-on-surface leading-relaxed">
                        {(detalle ?? selected).analisis_texto}
                      </p>
                    </div>
                  )}

                  {/* Pagos recibidos */}
                  <div>
                    <div className="text-xs font-semibold text-on-surface-variant mb-2 uppercase tracking-wider">
                      Pagos recibidos ({detalle?.pagos_recibidos?.length ?? 0})
                    </div>
                    {!detalle?.pagos_recibidos?.length ? (
                      <p className="text-xs text-on-surface-variant">Sin pagos registrados aún.</p>
                    ) : (
                      <div className="space-y-2">
                        {detalle.pagos_recibidos.map((p, i) => (
                          <div key={i} className="flex items-center justify-between bg-surface-container-low rounded-lg px-3 py-2">
                            <div>
                              <div className="text-xs text-on-surface-variant">{p.fecha ?? '—'}</div>
                              {p.alegra_journal_id && (
                                <div className="text-xs font-mono text-on-surface-variant">
                                  Journal: {p.alegra_journal_id}
                                </div>
                              )}
                            </div>
                            <div className="text-sm font-semibold text-on-surface">{COP(p.monto ?? 0)}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
