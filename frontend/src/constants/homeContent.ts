// ═══════════════════════════════════════════
// Home page content — edit aquí para actualizar
// la misión, valores, testimonios y roadmap RODDOS.
// ═══════════════════════════════════════════

export const HERO_COPY = {
  title: 'RODDOS es acceso para la movilidad en LATAM',
  subtitle: 'SISMO es el corazón que lo controla',
  description:
    'No somos un software. Somos el sistema nervioso de un negocio ' +
    'que financia sueños sobre dos ruedas.',
  ctaPrimary: { label: 'Ir al Agente Contador', to: '/chat' },
  ctaSecondary: { label: 'Ver nuestra historia', to: '#timeline' },
}

export interface ImpactCard {
  label: string
  value: string
  subtitle: string
}

export const IMPACT_NUMBERS: ImpactCard[] = [
  { label: 'Clientes', value: '28', subtitle: 'Sueños financiados' },
  { label: 'Cartera', value: '$221M', subtitle: 'Dinero en manos' },
  { label: 'Loanbooks', value: '25 activos', subtitle: 'Vidas en tránsito' },
  { label: 'Cobranza', value: '100% remota', subtitle: 'Humana + ágil' },
]

export interface ValueCard {
  title: string
  icon: string
  text: string
}

export const VALUES: ValueCard[] = [
  { title: 'Velocidad', icon: '🏃', text: 'Respuesta en horas, no semanas.' },
  { title: 'Calidad', icon: '💎', text: 'Cada moto, cada cliente importa.' },
  { title: 'Transparencia', icon: '🔍', text: 'Los números son reales.' },
  { title: 'Humano primero', icon: '🤝', text: 'Detrás de cada número hay gente.' },
]

export interface Testimonial {
  clientName: string
  role: string
  quote: string
  tenure: string
}

export const CLIENT_TESTIMONIALS: Testimonial[] = [
  {
    clientName: 'Chenier Quintero',
    role: 'Repartidor',
    quote: 'En RODDOS me trataron como persona, no como número. Hoy tengo mi moto y mi trabajo.',
    tenure: '18 meses con RODDOS',
  },
  {
    clientName: 'Jose Altamiranda',
    role: 'Domiciliario',
    quote:
      'Pagué mi moto y ahora me financiaron el comparendo. Confían en mí y yo en ellos.',
    tenure: '12 meses con RODDOS',
  },
  {
    clientName: 'Beatriz García',
    role: 'Emprendedora',
    quote:
      'Cada miércoles llega el cobro con respeto. Eso vale tanto como la cuota misma.',
    tenure: '10 meses con RODDOS',
  },
]

export interface TimelineEvent {
  year: number
  event: string
}

export const TIMELINE_EVENTS: TimelineEvent[] = [
  { year: 2023, event: 'Primer loanbook activo' },
  { year: 2024, event: '10 motos en cartera' },
  { year: 2025, event: 'SISMO nace' },
  { year: 2026, event: '28 clientes · $221M cartera' },
  { year: 2027, event: 'Futuro abierto' },
]

export interface DifferenceRow {
  otros: string
  roddos: string
}

export const DIFFERENCE_ROWS: DifferenceRow[] = [
  { otros: 'Cobranza agresiva', roddos: 'Cobranza con relación' },
  { otros: 'Datos opacos', roddos: 'Transparencia real' },
  { otros: 'Manual y lento', roddos: 'Ágil + humano' },
  { otros: 'Acceso limitado al crédito', roddos: 'Acceso radical a movilidad' },
  { otros: 'Procesos rígidos', roddos: 'Flexibilidad con disciplina' },
]

export const DIFFERENCE_FOOTER =
  'SISMO es la herramienta que lo hace posible — cada decisión en el sistema es una decisión humana amplificada.'

export interface RoadmapBlock {
  title: string
  subtitle: string
  items: string[]
}

export const ROADMAP_2027: RoadmapBlock[] = [
  {
    title: 'HOY (2026)',
    subtitle: 'Operación viva',
    items: ['28 clientes', '$221M en cartera', 'SISMO v2.0 en producción'],
  },
  {
    title: 'PRÓXIMOS 12M',
    subtitle: 'Escalamos sin perder el alma',
    items: ['50 clientes', '$500M en cartera', 'Origination automática'],
  },
  {
    title: 'LARGO PLAZO (2027-2028)',
    subtitle: 'RODDOS como referencia LatAm',
    items: ['100+ clientes', '$1B en cartera', 'SISMO: orquestador de agentes LatAm'],
  },
]

export const CTA_FINAL = {
  heading: 'Eres parte de esto',
  text:
    'Cada decisión que tomas en SISMO impacta a 28 familias que creen en RODDOS. ' +
    'Hazlo bien. Hazlo rápido. Hazlo con intención.',
  primary: { label: 'Ir a trabajar', to: '/chat' },
  secondary: { label: 'Ver impacto semanal', to: '/dashboard' },
}
