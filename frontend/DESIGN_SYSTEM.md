# RODDOS Design System — SISMO V2

## Color Tokens

| Token | Hex | Usage |
|-------|-----|-------|
| Primary | #006e2a | CTAs, active states, brand accent |
| Secondary | #006875 | Secondary actions, informational |
| Surface | #fcf9f8 | Page background |
| Surface Container Low | #f6f3f2 | Sidebar, cards background |
| Surface Container Lowest | #ffffff | Elevated cards, chat bubbles |
| On-Surface | #1a1a1a | Primary text |
| On-Surface Variant | #5f5f5f | Secondary text |
| Error | #ba1a1a | Destructive actions, errors |
| Success | #006e2a | Same as primary — confirmations |

## Typography

| Role | Font | Weight | Usage |
|------|------|--------|-------|
| Display | Public Sans | 700 | Headlines, page titles |
| Body | Inter | 400/500 | Paragraph text, labels, inputs |
| Mono | JetBrains Mono | 400 | Code, IDs, tool names |

## Rules

### No-Line Rule
No 1px solid borders anywhere. Use shadow, background contrast, or spacing to separate elements. The only acceptable divider is a subtle background-color shift between adjacent surfaces.

### Glass Rule
Floating elements (modals, dropdowns, toasts) use glassmorphism:
- `background: rgba(255, 255, 255, 0.85)`
- `backdrop-filter: blur(16px)`
- `border: none` (No-Line rule)

### Ambient Shadow
Elevation via soft, diffused shadows instead of borders:
- Level 1 (cards): `0 2px 24px rgba(26, 26, 26, 0.06)`
- Level 2 (modals): `0 8px 40px rgba(26, 26, 26, 0.10)`
- Level 3 (dropdowns): `0 12px 48px rgba(26, 26, 26, 0.14)`

### Spacing
Base unit: 4px. Use multiples: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64.

### Border Radius
- Small (inputs, chips): 8px
- Medium (cards, buttons): 12px
- Large (modals, panels): 16px
