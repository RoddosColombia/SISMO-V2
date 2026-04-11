import { useState, useRef, useEffect } from 'react'
import { chatSSE, apiPost } from '@/lib/api'

interface Message {
  role: 'user' | 'assistant' | 'system'
  content: string
  toolProposal?: {
    tool_name: string
    tool_input: Record<string, unknown>
    proposal: string
  }
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [approving, setApproving] = useState(false)
  const [sessionId] = useState(() => crypto.randomUUID())
  const bottomRef = useRef<HTMLDivElement>(null)
  const controllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function sendMessage() {
    const text = input.trim()
    if (!text || streaming) return

    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setStreaming(true)

    let assistantContent = ''

    controllerRef.current = chatSSE(
      text,
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
        } else if (event.type === 'error') {
          setMessages((prev) => [
            ...prev,
            { role: 'system', content: `Error: ${event.message}` },
          ])
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
    )
  }

  async function handleApproval(confirmed: boolean) {
    if (approving) return
    setApproving(true)
    try {
      const res = await apiPost<{ status: string; message: string }>('/chat/approve-plan', {
        session_id: sessionId,
        confirmed,
      })
      setMessages((prev) => [
        ...prev,
        { role: 'system', content: res.message },
      ])
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
            <div className="text-on-surface-variant text-sm">Escribe un mensaje para hablar con el Agente Contador</div>
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
        <div className="flex gap-3 bg-surface-container-lowest shadow-ambient-1 rounded-lg p-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage()}
            placeholder="Escribe un mensaje..."
            disabled={streaming}
            className="flex-1 px-3 py-2 bg-transparent text-sm text-on-surface placeholder:text-on-surface-variant focus:outline-none disabled:opacity-50"
          />
          <button
            onClick={sendMessage}
            disabled={streaming || !input.trim()}
            className="px-5 py-2 bg-primary text-white text-sm font-medium rounded-md hover:brightness-110 disabled:opacity-30 transition-all"
          >
            Enviar
          </button>
        </div>
      </div>
    </div>
  )
}
