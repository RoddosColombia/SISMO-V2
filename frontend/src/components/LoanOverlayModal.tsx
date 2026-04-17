import { useEffect, useState } from 'react'
import LoanDetailPage from '@/pages/LoanDetailPage'

// ═══════════════════════════════════════════
// LoanOverlayModal — premium refined overlay
//
// Design intent: sobrio, limpio, premium — RODDOS es un concesionario.
// Refined minimalism: mucho whitespace, sombras sutiles, animación discreta.
// ═══════════════════════════════════════════

interface Props {
  loanId: string
  onClose: () => void
}

export default function LoanOverlayModal({ loanId, onClose }: Props) {
  const [entered, setEntered] = useState(false)
  const [closing, setClosing] = useState(false)

  // Trigger enter animation on mount
  useEffect(() => {
    const t = requestAnimationFrame(() => setEntered(true))
    return () => cancelAnimationFrame(t)
  }, [])

  // Close with ESC key + body scroll lock
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose()
    }
    document.addEventListener('keydown', handleKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handleKey)
      document.body.style.overflow = prevOverflow
    }

  }, [])

  function handleClose() {
    setClosing(true)
    // Match CSS transition duration
    window.setTimeout(onClose, 120)
  }

  const backdropOpacity = entered && !closing ? 'opacity-100' : 'opacity-0'
  const panelTransform = entered && !closing ? 'scale-100 opacity-100' : 'scale-[0.97] opacity-0'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-0 sm:p-6"
      role="dialog"
      aria-modal="true"
    >
      {/* Backdrop */}
      <div
        onClick={handleClose}
        className={`absolute inset-0 bg-neutral-950/50 backdrop-blur-[2px] transition-opacity duration-150 ${backdropOpacity}`}
      />

      {/* Panel */}
      <div
        className={`
          relative w-full h-full sm:h-[90vh] sm:max-h-[900px]
          sm:w-[95%] md:w-[90%] lg:w-[85%] xl:max-w-[1200px]
          bg-white sm:rounded-2xl shadow-[0_24px_72px_-12px_rgba(15,23,42,0.25)]
          ring-1 ring-neutral-200/60
          overflow-hidden flex flex-col
          transition-all duration-150 ease-out
          ${panelTransform}
        `}
        onClick={e => e.stopPropagation()}
      >
        {/* Close button — sutil, sin borde, solo hover bg */}
        <button
          onClick={handleClose}
          aria-label="Cerrar"
          className="absolute top-3 right-3 sm:top-4 sm:right-4 z-10 w-8 h-8 flex items-center justify-center rounded-full text-neutral-400 hover:text-neutral-700 hover:bg-neutral-100 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto">
          <LoanDetailPage idProp={loanId} onClose={handleClose} />
        </div>
      </div>
    </div>
  )
}
