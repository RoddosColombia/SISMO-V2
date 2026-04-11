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

  const [approving, setApproving] = useState(false)

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
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && (
          <div className="text-center text-neutral-400 mt-20">
            Escribe un mensaje para hablar con el Agente Contador
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[80%] rounded-lg px-4 py-2 text-sm whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-neutral-900 text-white'
                  : msg.role === 'system'
                    ? 'bg-neutral-100 text-neutral-600 border border-neutral-200'
                    : 'bg-white text-neutral-800 border border-neutral-200'
              }`}
            >
              {msg.content}

              {msg.toolProposal && (
                <div className="mt-3 pt-3 border-t border-neutral-200 space-y-2">
                  <div className="text-xs text-neutral-500 font-mono">
                    {msg.toolProposal.tool_name}
                  </div>
                  <pre className="text-xs bg-neutral-50 p-2 rounded overflow-x-auto">
                    {JSON.stringify(msg.toolProposal.tool_input, null, 2)}
                  </pre>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleApproval(true)}
                      disabled={approving}
                      className="px-3 py-1 text-xs bg-neutral-900 text-white rounded hover:bg-neutral-800 disabled:opacity-50"
                    >
                      {approving ? 'Ejecutando...' : 'Confirmar'}
                    </button>
                    <button
                      onClick={() => handleApproval(false)}
                      disabled={approving}
                      className="px-3 py-1 text-xs bg-white text-neutral-600 border border-neutral-300 rounded hover:bg-neutral-50 disabled:opacity-50"
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
            <div className="text-sm text-neutral-400 px-4 py-2">...</div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-neutral-200 p-4">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage()}
            placeholder="Escribe un mensaje..."
            disabled={streaming}
            className="flex-1 px-3 py-2 border border-neutral-300 rounded text-sm focus:outline-none focus:border-neutral-500 disabled:opacity-50"
          />
          <button
            onClick={sendMessage}
            disabled={streaming || !input.trim()}
            className="px-4 py-2 bg-neutral-900 text-white text-sm rounded hover:bg-neutral-800 disabled:opacity-50"
          >
            Enviar
          </button>
        </div>
      </div>
    </div>
  )
}
