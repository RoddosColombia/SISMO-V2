import { useState, useRef, useEffect } from 'react'
import { chatSSE, apiPost, popPendingMessage } from '@/lib/api'

interface Message {
  role: 'user' | 'assistant' | 'system'
  content: string
  imageUrl?: string
  toolProposal?: {
    tool_name: string
    tool_input: Record<string, unknown>
    proposal: string
  }
}

const AGENT_LABELS: Record<string, string> = {
  contador: 'Contador',
  loanbook: 'Loanbook',
}

const AGENT_PLACEHOLDERS: Record<string, string> = {
  contador: 'Ej: Registrar arriendo $3.6M, ver balance...',
  loanbook: 'Ej: Ver cartera, consultar mora VIN ABC123...',
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [recoveredToast, setRecoveredToast] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [approving, setApproving] = useState(false)
  const [agentType, setAgentType] = useState<'contador' | 'loanbook'>('contador')
  const [sessionId] = useState(() => crypto.randomUUID())
  const [imagePreview, setImagePreview] = useState<string | null>(null)
  const [imageData, setImageData] = useState<string | null>(null)
  const [attachedPdf, setAttachedPdf] = useState<File | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const controllerRef = useRef<AbortController | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const pdfInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Recover a draft message that was saved on a previous 401/expiry (B7-UX)
  useEffect(() => {
    const pending = popPendingMessage()
    if (pending) {
      setInput(pending)
      setRecoveredToast(true)
      const id = window.setTimeout(() => setRecoveredToast(false), 4000)
      return () => window.clearTimeout(id)
    }
  }, [])

  function handleImageSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    // PDF: route to PDF handler
    if (file.type === 'application/pdf') {
      if (file.size > 20 * 1024 * 1024) {
        setMessages(prev => [...prev, { role: 'system', content: 'Error: PDF muy pesado, máximo 20MB' }])
        e.target.value = ''
        return
      }
      setAttachedPdf(file)
      e.target.value = ''
      return
    }

    if (file.size > 5 * 1024 * 1024) {
      setMessages(prev => [...prev, { role: 'system', content: 'Error: Imagen muy pesada, maximo 5MB' }])
      return
    }
    if (!file.type.startsWith('image/')) {
      setMessages(prev => [...prev, { role: 'system', content: 'Error: Solo se aceptan imágenes (JPEG, PNG, WebP) o documentos PDF' }])
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      const dataUrl = reader.result as string
      setImagePreview(dataUrl)
      setImageData(dataUrl)
    }
    reader.readAsDataURL(file)
    e.target.value = ''  // Reset so same file can be re-selected
  }

  function handlePdfSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > 20 * 1024 * 1024) {
      setMessages(prev => [...prev, { role: 'system', content: 'Error: PDF muy pesado, máximo 20MB' }])
      e.target.value = ''
      return
    }
    setAttachedPdf(file)
    e.target.value = ''
  }

  async function sendMessage() {
    const text = input.trim()
    if ((!text && !imageData && !attachedPdf) || streaming) return

    setInput('')
    const attachedImage = imageData
    const pdfFile = attachedPdf
    setImagePreview(null)
    setImageData(null)
    setAttachedPdf(null)

    // Leer PDF como base64 si hay uno adjunto
    let pdfBase64: string | null = null
    if (pdfFile) {
      const buffer = await pdfFile.arrayBuffer()
      const bytes = new Uint8Array(buffer)
      let binary = ''
      bytes.forEach(b => { binary += String.fromCharCode(b) })
      pdfBase64 = btoa(binary)
    }

    if (attachedImage) {
      setMessages((prev) => [...prev, { role: 'user', content: text || 'Procesar comprobante', imageUrl: attachedImage }])
    } else if (pdfFile) {
      setMessages((prev) => [...prev, { role: 'user', content: text || `📄 ${pdfFile.name}` }])
    } else {
      setMessages((prev) => [...prev, { role: 'user', content: text }])
    }
    setStreaming(true)

    let assistantContent = ''

    controllerRef.current = chatSSE(
      text || (pdfFile ? `Analizar factura ${pdfFile.name}` : 'Procesar este comprobante'),
      sessionId,
      (event) => {
        if (event.type === 'text') {
          assistantContent += event.content as string
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last?.role === 'assistant' && !last.toolProposal) {
              updated[updated.length - 1] = { ...last, content: assistantContent }
            } else {
              updated.push({ role: 'assistant', content: assistantContent })
            }
            return updated
          })
        } else if (event.type === 'tool_proposal') {
          setMessages((prev) => [
            ...prev,
            {
              role: 'assistant',
              content: (event.proposal as string) || `Propuesta: ${event.tool_name}`,
              toolProposal: {
                tool_name: event.tool_name as string,
                tool_input: event.tool_input as Record<string, unknown>,
                proposal: (event.proposal as string) || '',
              },
            },
          ])
        } else if (event.type === 'tool_result') {
          // Fallback for read-only tools that fail the second Claude call
          const result = event.result as Record<string, unknown>
          setMessages((prev) => [
            ...prev,
            {
              role: 'system',
              content: result?.message
                ? String(result.message)
                : JSON.stringify(result, null, 2),
            },
          ])
        } else if (event.type === 'clarification') {
          // Router pide aclaración cuando confidence < THRESHOLD — renderizar
          // como mensaje normal del agente para que el usuario responda.
          const question = (event.question as string) || (event.content as string) || ''
          setMessages((prev) => [
            ...prev,
            { role: 'assistant', content: question },
          ])
        } else if (event.type === 'error') {
          setMessages((prev) => [
            ...prev,
            { role: 'system', content: `Error: ${event.message}` },
          ])
        } else {
          // Unknown SSE event type — log warning, do NOT block UI (P7 additive)
          console.warn('[chat] unhandled SSE event type:', event.type, event)
        }
      },
      () => setStreaming(false),
      (err) => {
        setMessages((prev) => [
          ...prev,
          { role: 'system', content: `Error: ${err.message}` },
        ])
        setStreaming(false)
      },
      attachedImage,
      agentType,
      pdfBase64,
    )
  }

  async function handleApproval(confirmed: boolean) {
    if (approving) return
    setApproving(true)
    try {
      const res = await apiPost<{
        status: string
        final_response?: string
        message?: string
      }>('/chat/approve-plan', {
        session_id: sessionId,
        confirmed,
      })

      // Clear the ExecutionCard buttons from the last proposal message
      setMessages((prev) => {
        const updated = [...prev]
        for (let i = updated.length - 1; i >= 0; i--) {
          if (updated[i].toolProposal) {
            updated[i] = { ...updated[i], toolProposal: undefined }
            break
          }
        }
        return updated
      })

      if (confirmed) {
        const content = res.final_response || res.message || 'Acción ejecutada exitosamente.'
        setMessages((prev) => [...prev, { role: 'assistant', content }])
      } else {
        setMessages((prev) => [...prev, { role: 'system', content: 'Acción cancelada.' }])
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'system', content: `Error: ${err instanceof Error ? err.message : 'Error'}` },
      ])
    } finally {
      setApproving(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center mt-32">
            <div className="text-on-surface-variant text-sm">
              Escribe un mensaje para hablar con el Agente {AGENT_LABELS[agentType]}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[75%] rounded-lg px-4 py-3 text-sm whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-primary text-white shadow-ambient-1'
                  : msg.role === 'system'
                    ? 'bg-secondary-light text-secondary rounded-md'
                    : 'bg-surface-container-lowest text-on-surface shadow-ambient-1'
              }`}
            >
              {msg.imageUrl && (
                <img src={msg.imageUrl} alt="Comprobante" className="max-w-full rounded-md mb-2 max-h-48" />
              )}
              {msg.content}

              {/* ExecutionCard */}
              {msg.toolProposal && (
                <div className="mt-3 pt-3 space-y-3" style={{ borderTop: '1px dashed rgba(0,0,0,0.1)' }}>
                  <div className="text-xs text-on-surface-variant font-mono">
                    {msg.toolProposal.tool_name}
                  </div>
                  <pre className="text-xs bg-surface-container-low p-3 rounded-md overflow-x-auto font-mono">
                    {JSON.stringify(msg.toolProposal.tool_input, null, 2)}
                  </pre>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleApproval(true)}
                      disabled={approving}
                      className="px-4 py-1.5 text-xs bg-primary text-white rounded-md hover:brightness-110 disabled:opacity-50 transition-all"
                    >
                      {approving ? 'Ejecutando...' : 'Confirmar'}
                    </button>
                    <button
                      onClick={() => handleApproval(false)}
                      disabled={approving}
                      className="px-4 py-1.5 text-xs text-on-surface-variant bg-surface-container-low rounded-md hover:bg-surface-container-lowest disabled:opacity-50 transition-colors"
                    >
                      Cancelar
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}

        {streaming && (
          <div className="flex justify-start">
            <div className="bg-surface-container-lowest shadow-ambient-1 rounded-lg px-4 py-3">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 bg-on-surface-variant rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 bg-on-surface-variant rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 bg-on-surface-variant rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-6 py-4">
        {imagePreview && (
          <div className="mb-2 flex items-center gap-2">
            <img src={imagePreview} alt="Preview" className="h-16 rounded-md" />
            <button onClick={() => { setImagePreview(null); setImageData(null) }}
              className="text-xs text-on-surface-variant hover:text-error">
              Quitar
            </button>
          </div>
        )}
        {attachedPdf && (
          <div className="mb-2 flex items-center gap-2 px-3 py-1.5 bg-surface-container-low rounded-md w-fit">
            <span className="text-xs text-on-surface-variant">📄</span>
            <span className="text-xs text-on-surface truncate max-w-xs">{attachedPdf.name}</span>
            <button
              onClick={() => setAttachedPdf(null)}
              className="text-xs text-on-surface-variant hover:text-error ml-1"
            >
              ×
            </button>
          </div>
        )}
        {recoveredToast && (
          <div className="mb-2 p-2 text-xs bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-md">
            Recuperamos tu último mensaje
          </div>
        )}

        {/* Agent selector */}
        <div className="flex gap-1 mb-2">
          {(['contador', 'loanbook'] as const).map((agent) => (
            <button
              key={agent}
              onClick={() => setAgentType(agent)}
              disabled={streaming}
              className={`px-3 py-1 text-xs rounded-full transition-colors disabled:opacity-40 ${
                agentType === agent
                  ? 'bg-primary text-white'
                  : 'text-on-surface-variant bg-surface-container-low hover:bg-surface-container-lowest'
              }`}
            >
              {AGENT_LABELS[agent]}
            </button>
          ))}
        </div>

        <div className="flex gap-3 bg-surface-container-lowest shadow-ambient-1 rounded-lg p-2">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleImageSelect}
            accept="image/jpeg,image/png,image/webp,application/pdf"
            className="hidden"
          />
          <input
            type="file"
            ref={pdfInputRef}
            onChange={handlePdfSelect}
            accept="application/pdf"
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={streaming}
            className="px-3 py-2 text-on-surface-variant hover:text-on-surface disabled:opacity-30 transition-colors"
            title="Adjuntar imagen"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941l-7.81 7.81a1.5 1.5 0 002.112 2.13" />
            </svg>
          </button>
          <button
            onClick={() => pdfInputRef.current?.click()}
            disabled={streaming}
            className="px-3 py-2 text-on-surface-variant hover:text-on-surface disabled:opacity-30 transition-colors"
            title="Adjuntar factura PDF"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
          </button>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage()}
            placeholder={AGENT_PLACEHOLDERS[agentType]}
            disabled={streaming}
            className="flex-1 px-3 py-2 bg-transparent text-sm text-on-surface placeholder:text-on-surface-variant focus:outline-none disabled:opacity-50"
          />
          <button
            onClick={sendMessage}
            disabled={streaming || (!input.trim() && !imageData && !attachedPdf)}
            className="px-5 py-2 bg-primary text-white text-sm font-medium rounded-md hover:brightness-110 disabled:opacity-30 transition-all"
          >
            Enviar
          </button>
        </div>
      </div>
    </div>
  )
}
