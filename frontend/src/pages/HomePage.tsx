import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  HERO_COPY,
  IMPACT_NUMBERS,
  VALUES,
  CLIENT_TESTIMONIALS,
  TIMELINE_EVENTS,
  DIFFERENCE_ROWS,
  DIFFERENCE_FOOTER,
  ROADMAP_2027,
  CTA_FINAL,
} from '@/constants/homeContent'

// ═══════════════════════════════════════════
// HomePage — RODDOS cultural home
//
// Diseño: refined minimalism, typography-first.
// Todas las copys viven en constants/homeContent.ts
// ═══════════════════════════════════════════

// ── Reusable section wrapper ──────────────────────────────────────

function Section({
  id,
  eyebrow,
  title,
  children,
  bg = 'bg-white',
}: {
  id?: string
  eyebrow?: string
  title?: string
  children: React.ReactNode
  bg?: string
}) {
  return (
    <section id={id} className={`${bg} py-14 sm:py-20`}>
      <div className="max-w-6xl mx-auto px-5 sm:px-8">
        {eyebrow && (
          <div className="text-[11px] font-semibold text-emerald-700 uppercase tracking-[0.18em] mb-2">
            {eyebrow}
          </div>
        )}
        {title && (
          <h2 className="text-2xl sm:text-3xl font-semibold text-gray-900 tracking-tight mb-8 max-w-2xl">
            {title}
          </h2>
        )}
        {children}
      </div>
    </section>
  )
}

// ═══════════════════════════════════════════
// Section 1 — Hero
// ═══════════════════════════════════════════

function HeroNarrativo() {
  const navigate = useNavigate()
  return (
    <section className="relative bg-gradient-to-br from-white via-emerald-50/30 to-white border-b border-gray-100">
      <div className="max-w-6xl mx-auto px-5 sm:px-8 py-20 sm:py-28">
        <div className="max-w-3xl">
          <div className="text-[11px] font-semibold text-emerald-700 uppercase tracking-[0.18em] mb-4">
            Misión · 2026
          </div>
          <h1 className="text-3xl sm:text-5xl font-semibold text-gray-900 tracking-tight leading-[1.1]">
            {HERO_COPY.title}
          </h1>
          <p className="text-xl sm:text-2xl text-emerald-700 mt-4 font-medium">
            {HERO_COPY.subtitle}
          </p>
          <p className="text-base sm:text-lg text-gray-600 mt-6 leading-relaxed max-w-2xl">
            {HERO_COPY.description}
          </p>
          <div className="flex flex-col sm:flex-row gap-3 mt-8">
            <button
              onClick={() => navigate(HERO_COPY.ctaPrimary.to)}
              className="inline-flex items-center justify-center px-5 py-2.5 rounded-full bg-emerald-700 text-white text-sm font-medium hover:bg-emerald-800 transition-colors"
            >
              {HERO_COPY.ctaPrimary.label}
            </button>
            <a
              href={HERO_COPY.ctaSecondary.to}
              className="inline-flex items-center justify-center px-5 py-2.5 rounded-full bg-white text-gray-700 border border-gray-200 text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              {HERO_COPY.ctaSecondary.label}
            </a>
          </div>
        </div>
      </div>
    </section>
  )
}

// ═══════════════════════════════════════════
// Section 2 — Impact Numbers
// ═══════════════════════════════════════════

function ImpactNumbers() {
  return (
    <Section eyebrow="Hoy" title="Lo que movemos, en números." bg="bg-gray-50/50">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {IMPACT_NUMBERS.map(card => (
          <div
            key={card.label}
            className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 sm:p-6"
          >
            <div className="text-[10px] text-gray-400 uppercase tracking-wider">{card.label}</div>
            <div className="text-3xl sm:text-4xl font-semibold text-gray-900 mt-2 tracking-tight">
              {card.value}
            </div>
            <div className="text-xs text-gray-500 mt-1.5">{card.subtitle}</div>
          </div>
        ))}
      </div>
    </Section>
  )
}

// ═══════════════════════════════════════════
// Section 3 — Values
// ═══════════════════════════════════════════

function Values() {
  return (
    <Section eyebrow="Valores" title="Cómo trabajamos, cómo decidimos." bg="bg-white">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {VALUES.map(v => (
          <div
            key={v.title}
            className="flex items-start gap-4 p-5 sm:p-6 rounded-xl border border-gray-100 bg-gray-50/40"
          >
            <div className="text-2xl shrink-0" aria-hidden>
              {v.icon}
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-900">{v.title}</h3>
              <p className="text-sm text-gray-600 mt-1 leading-relaxed">{v.text}</p>
            </div>
          </div>
        ))}
      </div>
    </Section>
  )
}

// ═══════════════════════════════════════════
// Section 4 — Testimonials (carousel)
// ═══════════════════════════════════════════

function ClientTestimonials() {
  const [idx, setIdx] = useState(0)
  const total = CLIENT_TESTIMONIALS.length
  const t = CLIENT_TESTIMONIALS[idx]
  const prev = () => setIdx(i => (i - 1 + total) % total)
  const next = () => setIdx(i => (i + 1) % total)

  return (
    <Section eyebrow="Ellos confían en RODDOS" title="La gente detrás de cada loanbook." bg="bg-gray-50/50">
      <div className="max-w-3xl">
        <blockquote className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 sm:p-8">
          <svg className="w-6 h-6 text-emerald-600 mb-3" fill="currentColor" viewBox="0 0 24 24">
            <path d="M9 7H5a2 2 0 00-2 2v4a2 2 0 002 2h3v1a2 2 0 01-2 2H5v2h1a4 4 0 004-4V9a2 2 0 00-1-2zm10 0h-4a2 2 0 00-2 2v4a2 2 0 002 2h3v1a2 2 0 01-2 2h-1v2h1a4 4 0 004-4V9a2 2 0 00-1-2z" />
          </svg>
          <p className="text-base sm:text-lg text-gray-800 leading-relaxed">"{t.quote}"</p>
          <footer className="mt-5 flex items-end justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-gray-900">{t.clientName}</div>
              <div className="text-xs text-gray-500 mt-0.5">
                {t.role} · {t.tenure}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={prev}
                aria-label="Testimonio anterior"
                className="w-8 h-8 flex items-center justify-center rounded-full border border-gray-200 text-gray-500 hover:text-gray-900 hover:bg-gray-50 transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
                </svg>
              </button>
              <div className="text-xs text-gray-400 tabular-nums">
                {idx + 1} / {total}
              </div>
              <button
                onClick={next}
                aria-label="Testimonio siguiente"
                className="w-8 h-8 flex items-center justify-center rounded-full border border-gray-200 text-gray-500 hover:text-gray-900 hover:bg-gray-50 transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                </svg>
              </button>
            </div>
          </footer>
        </blockquote>
      </div>
    </Section>
  )
}

// ═══════════════════════════════════════════
// Section 5 — Timeline
// ═══════════════════════════════════════════

function Timeline() {
  return (
    <Section id="timeline" eyebrow="Historia" title="Cuatro años, una misión." bg="bg-white">
      {/* Desktop horizontal */}
      <div className="hidden md:block">
        <div className="relative">
          <div className="absolute left-0 right-0 top-4 h-px bg-gray-200" />
          <div className="relative grid grid-cols-5 gap-4">
            {TIMELINE_EVENTS.map(ev => (
              <div key={ev.year} className="text-center">
                <div className="mx-auto w-3 h-3 rounded-full bg-emerald-700 ring-4 ring-white" />
                <div className="mt-4 text-sm font-semibold text-gray-900">{ev.year}</div>
                <div className="mt-1 text-xs text-gray-600 leading-relaxed">{ev.event}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      {/* Mobile vertical */}
      <div className="md:hidden space-y-4">
        {TIMELINE_EVENTS.map(ev => (
          <div key={ev.year} className="flex items-start gap-4">
            <div className="w-3 h-3 rounded-full bg-emerald-700 mt-1.5 shrink-0" />
            <div>
              <div className="text-sm font-semibold text-gray-900">{ev.year}</div>
              <div className="text-xs text-gray-600 mt-0.5">{ev.event}</div>
            </div>
          </div>
        ))}
      </div>
    </Section>
  )
}

// ═══════════════════════════════════════════
// Section 6 — Difference comparison
// ═══════════════════════════════════════════

function DifferenceComparison() {
  return (
    <Section eyebrow="Diferencia" title="¿Por qué no somos como los demás?" bg="bg-gray-50/50">
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="grid grid-cols-2">
          <div className="bg-red-50/30 px-5 py-4 border-r border-gray-100">
            <div className="text-[10px] text-red-700/80 uppercase tracking-wider font-semibold">Otros</div>
          </div>
          <div className="bg-emerald-50/30 px-5 py-4">
            <div className="text-[10px] text-emerald-700 uppercase tracking-wider font-semibold">RODDOS</div>
          </div>
        </div>
        <div className="divide-y divide-gray-100">
          {DIFFERENCE_ROWS.map((row, i) => (
            <div key={i} className="grid grid-cols-2">
              <div className="px-5 py-3.5 text-sm text-gray-600 border-r border-gray-100 flex items-start gap-2">
                <span className="text-red-400 shrink-0">✕</span>
                {row.otros}
              </div>
              <div className="px-5 py-3.5 text-sm text-gray-900 flex items-start gap-2">
                <span className="text-emerald-600 shrink-0">✓</span>
                {row.roddos}
              </div>
            </div>
          ))}
        </div>
      </div>
      <p className="text-sm text-gray-500 italic mt-4 max-w-2xl">{DIFFERENCE_FOOTER}</p>
    </Section>
  )
}

// ═══════════════════════════════════════════
// Section 7 — Roadmap
// ═══════════════════════════════════════════

function Roadmap() {
  return (
    <Section eyebrow="Roadmap" title="De dónde venimos, a dónde vamos." bg="bg-white">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {ROADMAP_2027.map((block, i) => (
          <div
            key={block.title}
            className={`rounded-xl border p-5 sm:p-6 ${
              i === 0
                ? 'bg-emerald-50/50 border-emerald-100'
                : i === 1
                ? 'bg-amber-50/40 border-amber-100'
                : 'bg-gray-50 border-gray-100'
            }`}
          >
            <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
              {block.title}
            </div>
            <div className="text-sm text-gray-700 mt-1 italic">{block.subtitle}</div>
            <ul className="mt-4 space-y-2">
              {block.items.map(item => (
                <li key={item} className="text-sm text-gray-900 flex items-start gap-2">
                  <span className="text-gray-400 shrink-0">─</span>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Section>
  )
}

// ═══════════════════════════════════════════
// Section 8 — CTA Final
// ═══════════════════════════════════════════

function CTAFinal() {
  const navigate = useNavigate()
  return (
    <section className="bg-gradient-to-br from-emerald-800 via-emerald-700 to-emerald-900 text-white">
      <div className="max-w-6xl mx-auto px-5 sm:px-8 py-16 sm:py-20 text-center">
        <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight">{CTA_FINAL.heading}</h2>
        <p className="text-base sm:text-lg text-emerald-50 mt-4 max-w-2xl mx-auto leading-relaxed">
          {CTA_FINAL.text}
        </p>
        <div className="flex flex-col sm:flex-row gap-3 justify-center mt-8">
          <button
            onClick={() => navigate(CTA_FINAL.primary.to)}
            className="inline-flex items-center justify-center px-5 py-2.5 rounded-full bg-white text-emerald-800 text-sm font-semibold hover:bg-emerald-50 transition-colors"
          >
            {CTA_FINAL.primary.label}
          </button>
          <button
            onClick={() => navigate(CTA_FINAL.secondary.to)}
            className="inline-flex items-center justify-center px-5 py-2.5 rounded-full bg-emerald-900/40 text-white border border-emerald-300/40 text-sm font-medium hover:bg-emerald-900/60 transition-colors"
          >
            {CTA_FINAL.secondary.label}
          </button>
        </div>
      </div>
    </section>
  )
}

// ═══════════════════════════════════════════
// Main page
// ═══════════════════════════════════════════

export default function HomePage() {
  return (
    <div className="h-full overflow-y-auto bg-white">
      <HeroNarrativo />
      <ImpactNumbers />
      <Values />
      <ClientTestimonials />
      <Timeline />
      <DifferenceComparison />
      <Roadmap />
      <CTAFinal />
    </div>
  )
}
