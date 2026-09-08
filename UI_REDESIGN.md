# DecentralChat — UI Redesign Notes

> **Recreated:** 2026-09-04
> **Purpose:** Preserve the design rationale for the "Copper & Graphite" token system so it isn't lost again (the original `UI_REDESIGN.md` was deleted in a cleanup commit).

---

## Design Direction

The app uses a **Copper & Graphite** visual system:

- **Graphite** (`--graphite: #232220`, `--ink: #171615`) — deep warm-neutral surfaces
- **Copper** (`--copper: #BE5B2E`, `--copper-mid: #C97A3D`) — primary accent
- **Amber** (`--amber: #E2A33E`, `--amber-soft: #E6B26E`) — light accent / glow
- **Linen** (`--linen: #EDE9E2`) — primary text
- **Pewter / Ash** — muted / secondary text

## Typography

- **Display:** `Fraunces` (serif) — used for headings, logos, titles
- **Body:** `Inter` (sans-serif) — used for UI text, messages, forms

## Surfaces

- `.glass` — translucent card with restrained blur and soft ambient shadow
- `.glass-strong` — more opaque, stronger blur, used for modals / overlays
- Elevation tokens (`--elev-1` through `--elev-3`, `--elev-glow`) provide layered depth

## Screens

Prioritized high-traffic screens:
1. Chat list (sidebar)
2. Message thread
3. File picker / conversion panel
4. Call UI

## Goals & Guardrails

- Keep the token system; execute with **restraint and distinctiveness** rather than a full rewrite.
- Avoid the generic glass-morphism-gradient-dark-theme pattern many AI page-builders default to.
- Modernization effort should focus on **high-traffic screens first**, not every settings modal equally.
- When rebuilding visuals, use the existing tokens where they are good — faster than a full rewrite.
