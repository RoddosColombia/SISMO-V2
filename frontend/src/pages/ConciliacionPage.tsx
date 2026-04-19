import { useState, useRef, useCallback } from 'react'
import { apiGet } from '@/lib/api'

// ═══════════════════════════════════════════
// Conciliación bancaria — Subir extracto
// ═══════════════════════════════════════════

const BANCOS = [
  { value: 'bancolombia_2029', label: 'Bancolombia 2029' },
  { value: 'bancolombia_2540', label: 'Bancolombia 2540' },
  { value: 'bbva_0210', label: 'BBVA 0210' },
  { value: 'bbva_0212', label: 'BBVA 0212' },
  { value: 'davivienda_482', label: 'Davivienda 482' },
  { value: 'banco_bogota', label: 'Banco de Bogotá' },
  { value: 'nequi', label: 'Nequi' },
]

interface JobStatus {
  job_id: string
  estado?: string
  progress?: number
  resultado?: Record<string, unknown>
  error?: string
  created_at?: string
  updated_at?: string
}

function StatusBadge({ estado }: { estado: string }) {
  const map: Record<string, string> = {
    pendiente: 'bg-gray-100 text-gray-600',
    procesando: 'bg-amber-50 text-amber-700',
    completado: 'bg-emerald-50 text-emerald-700',
    error: 'bg-red-50 text-red-600',
  }
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium ${map[estado] ?? 'bg-gray-100 text-gray-600'}`}>
      {estado}
    </span>
  )
}

export default function ConciliacionPage() {
  const token = localStorage.getItem('token') ?? ''
  const [banco, setBanco] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null)
  const [error, setError] = useState('')
  const [polling, setPolling] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    setPolling(false)
  }, [])

  const startPoll = useCallback((jid: string) => {
    setPolling(true)
    pollRef.current = setInterval(async () => {
      try {
        const res = await apiGet<{ success: boolean; data: JobStatus }>(`/conciliacion/estado/${jid}`)
        if (res.success && res.data) {
          setJobStatus(res.data)
          const done = res.data.estado === 'completado' || res.data.estado === 'error'
          if (done) stopPoll()
        }
      } catch { /* ignore */ }
    }, 2500)
  }, [stopPoll])

  function handleFile(f: File) {
    const ext = f.name.split('.').pop()?.toLowerCase()
    if (!ext || !['xlsx', 'pdf', 'xls'].includes(ext)) {
      setError('Solo se aceptan archivos .xlsx, .xls o .pdf')
      return
    }
    setFile(f)
    setError('')
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }

  async function upload() {
    if (!file) { setError('Selecciona un archivo'); return }
    setUploading(true); setError(''); setJobStatus(null); setJobId(null)
    stopPoll()

    try {
      const form = new FormData()
      form.append('file', file)
      if (banco) form.append('banco', banco)

      const apiBase = (import.meta.env.VITE_API_URL ?? '') + '/api'
      const res = await fetch(`${apiBase}/conciliacion/cargar-extracto`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      })

      if (!res.ok) {
        const txt = await res.text()
        throw new Error(`Error ${res.status}: ${txt}`)
      }

      const data = await res.json()
      const jid = data?.job_id ?? data?.data?.job_id
      if (jid) {
        setJobId(jid)
        setJobStatus(data?.data ?? data)
        startPoll(jid)
      } else {
        // Respuesta síncrona sin job_id
        setJobStatus(data)
      }
      setFile(null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Error al subir el archivo')
    } finally {
      setUploading(false)
    }
  }

  function reset() {
    stopPoll()
    setFile(null)
    setJobId(null)
    setJobStatus(null)
    setError('')
  }

  return (
    <div className="flex flex-col h-full bg-gray-50 overflow-y-auto">
      {/* Header */}
      <div className="bg-white border-b border-gray-100 px-6 py-5">
        <h1 className="text-xl font-semibold text-gray-900 tracking-tight">Conciliación bancaria</h1>
        <p className="text-sm text-gray-500 mt-0.5">Sube el extracto del banco para conciliar con Alegra</p>
      </div>

      <div className="px-6 py-5 max-w-2xl w-full mx-auto space-y-5">

        {/* Selector banco */}
        <div>
          <label className="text-[10px] text-gray-400 uppercase tracking-wider block mb-1.5">
            Banco (opcional — se detecta automáticamente)
          </label>
          <select
            value={banco}
            onChange={e => setBanco(e.target.value)}
            className="w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-emerald-100 focus:border-emerald-300"
          >
            <option value="">Detectar automáticamente</option>
            {BANCOS.map(b => <option key={b.value} value={b.value}>{b.label}</option>)}
          </select>
        </div>

        {/* Drop zone */}
        <div
          onDragOver={e => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => fileInput.current?.click()}
          className={`relative border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors ${
            dragging
              ? 'border-emerald-400 bg-emerald-50'
              : file
              ? 'border-emerald-300 bg-emerald-50/40'
              : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'
          }`}
        >
          <input
            ref={fileInput}
            type="file"
            accept=".xlsx,.xls,.pdf"
            className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
          />
          {file ? (
            <div className="space-y-1">
              <div className="text-2xl">📄</div>
              <p className="text-sm font-semibold text-gray-900">{file.name}</p>
              <p className="text-xs text-gray-500">{(file.size / 1024).toFixed(0)} KB</p>
              <button
                onClick={e => { e.stopPropagation(); setFile(null) }}
                className="text-xs text-red-500 hover:text-red-700 mt-1"
              >
                Quitar
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="text-3xl text-gray-300">⬆</div>
              <p className="text-sm font-medium text-gray-700">Arrastra el extracto aquí</p>
              <p className="text-xs text-gray-400">o haz clic para seleccionar · .xlsx, .xls, .pdf</p>
            </div>
          )}
        </div>

        {error && (
          <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-md px-3 py-2">{error}</p>
        )}

        {/* Botones */}
        <div className="flex gap-3">
          {(jobStatus || file) && (
            <button onClick={reset} className="px-4 py-2 rounded-md bg-gray-100 text-gray-700 text-sm hover:bg-gray-200">
              Nueva conciliación
            </button>
          )}
          <button
            onClick={upload}
            disabled={!file || uploading}
            className="flex-1 px-4 py-2 rounded-md bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {uploading ? 'Procesando...' : 'Subir y conciliar'}
          </button>
        </div>

        {/* Estado del job */}
        {jobStatus && (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-900">Estado de la conciliación</h3>
              <div className="flex items-center gap-2">
                {polling && (
                  <div className="w-3 h-3 rounded-full border-2 border-emerald-500 border-t-transparent animate-spin" />
                )}
                {jobStatus.estado && <StatusBadge estado={jobStatus.estado} />}
              </div>
            </div>

            {jobId && (
              <p className="text-[10px] font-mono text-gray-400">Job ID: {jobId}</p>
            )}

            {jobStatus.progress != null && (
              <div>
                <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 transition-all"
                    style={{ width: `${Math.min(jobStatus.progress, 100)}%` }}
                  />
                </div>
                <p className="text-[11px] text-gray-400 mt-1">{jobStatus.progress}%</p>
              </div>
            )}

            {jobStatus.resultado && (
              <div className="bg-gray-50 rounded-md p-3">
                <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-2">Resultado</p>
                <pre className="text-xs text-gray-700 whitespace-pre-wrap break-all">
                  {JSON.stringify(jobStatus.resultado, null, 2)}
                </pre>
              </div>
            )}

            {jobStatus.error && (
              <p className="text-xs text-red-600 bg-red-50 rounded-md px-3 py-2">{jobStatus.error}</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
