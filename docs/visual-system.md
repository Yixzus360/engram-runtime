# Engram visual system

Engram Runtime inherits the crystalline visual language used by the owner's
Threads Mode product while adapting it to a dense engineering console. It does
not reuse the site's commercial layout, copy, media, or page composition.

## Typography

- Family: Inter Variable, weights 100–900, distributed under the SIL Open Font License.
- Display: Inter Variable 300 for large runtime headings.
- Interface: Inter Variable 400 and 500.
- Emphasis: Inter Variable 600.
- Code and identifiers: a system monospace stack.
- Interface line length: 72 characters maximum for explanatory copy.

## Palette

| Token | Value | Role |
| --- | --- | --- |
| Midnight | `#070b12` | Main canvas. |
| Deep current | `#091424` | Background gradient anchor. |
| Glass | `#0d213bab` | Primary translucent surface. |
| Dense glass | `#10263dd9` | Focused and modal surfaces. |
| Ice | `#f8fafc` | Primary text. |
| Mist | `#b4c3d7` | Secondary text. |
| Electric blue | `#1876f2` | Selection and primary action. |
| Signal cyan | `#38bdf8` | Live runtime activity. |
| Success | `#22c55e` | Verified outcome. |
| Warning | `#fbbf24` | Attention required. |
| Failure | `#fb7185` | Failed or rejected state. |

## Material

- Canvas: layered radial gradients over a near-black blue field.
- Primary glass: `rgba(13, 33, 59, 0.67)` with 18px backdrop blur.
- Strong glass: `rgba(16, 38, 61, 0.85)` with 24px backdrop blur.
- Edge: one-pixel ice-blue border between 12% and 26% opacity.
- Depth: broad dark shadow plus a restrained blue ambient glow.
- Radius: 18px for work surfaces, 999px only for compact status controls.
- Reflection: a narrow top-edge highlight, never a full decorative gradient border.

## Runtime Console layout

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Engram  provider / profile                         run status   settings │
├──────────────┬─────────────────────────────────────┬─────────────────────┤
│ Run journal  │ Active Frame                        │ Focus Packet        │
│              │ conversation + action dispatches    │ selected signals    │
│              │                                     │ and procedures      │
├──────────────┴─────────────────────────────────────┴─────────────────────┤
│ Run Record: time-ordered evidence, usage, checks, and stored outputs     │
└──────────────────────────────────────────────────────────────────────────┘
```

The memorable element is a slowly refracting signal field behind the Active
Frame. It responds to runtime activity and becomes still when the system is
idle. Other surfaces remain quiet so operational information stays legible.

## Interaction

- Motion explains state changes; it is not continuous decoration.
- A dispatch creates one short light pulse from Active Frame to Run Record.
- Focus Packet changes crossfade in place without moving the layout.
- Reduced-motion mode removes refraction and pulse animation.
- Every interactive element has a visible keyboard focus state.

