# HanClassStudio Design Direction

HanClassStudio is a teacher-facing AI courseware workspace, not a marketing site. The UI should feel calm, structured, trustworthy, and fast to scan during lesson preparation.

This direction is adapted from the VoltAgent `awesome-design-md` collection:

- Linear: restrained product UI, surface ladders, hairline borders, no decorative gradients.
- Mintlify: documentation-grade density, clear sidebars, code/spec surfaces, strong reading rhythm.
- Intercom: warm canvas, white work surfaces, limited accent color, low-shadow depth.
- Notion: approachable workspace language and visible structure without visual noise.

Source: https://github.com/VoltAgent/awesome-design-md

## Design Principles

1. Workbench first. The first screen should expose the workflow and current project state, not a hero or promotional layout.
2. Quiet hierarchy. Use spacing, surface contrast, and type weight before adding color.
3. One primary action per region. Secondary actions stay outlined or low-emphasis.
4. Product UI is the visual asset. Previews, artifact summaries, pipeline state, and editable lesson structure carry the visual weight.
5. Semantic tokens only. Components should use CSS variables from `apps/web/src/styles.css`; avoid one-off hex values in component styles.

## Visual Tone

- Canvas: warm off-white, closer to Intercom than pure gray.
- Surfaces: crisp white cards with warm hairline borders.
- Primary accent: deep teaching teal, used for primary CTAs, selected states, active workflow, and success-adjacent progress.
- Secondary accents: coral for destructive/error states, amber for warnings, blue only for focus or technical emphasis.
- Depth: mostly surface contrast and 1px borders; shadows stay soft and rare.
- Shape: 8px controls, 12px panels, 999px only for true pills.
- Icons: Lucide outline icons only, consistent size and stroke.

## Type

Use the system UI stack with Chinese fallbacks:

```css
Inter, "Noto Sans SC", "Microsoft YaHei", Arial, sans-serif
```

Keep letter spacing at `0`. Use weight and size for hierarchy:

- Page title: 28-40px, 700.
- Panel title: 20-22px, 700.
- Body: 14-16px, 400-500, line-height 1.5-1.6.
- Labels and status chips: 12-13px, 700.
- Code, paths, task text: `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`.

## Layout

- Base rhythm: 4px/8px increments.
- Sidebar: persistent workflow navigation on desktop, sticky horizontal step surface on tablet/mobile.
- Workspace: dense but breathable; default page padding 24px desktop, 16px mobile.
- Panels: use full-width work surfaces, not nested decorative cards.
- Forms: visible labels, 44px minimum controls, two-column desktop and one-column mobile.

## Component Rules

- Buttons: 44px minimum height, icon plus text for commands, visible disabled state.
- Icon buttons: 44x44px with `aria-label`.
- Status chips: compact, bordered, semantic color only when meaningful.
- Pipeline steps: communicate state with icon plus text, never color alone.
- Editors: nested editable regions may use soft tinted surfaces, but keep the same border/radius scale.
- Modals: use a strong enough scrim and the same panel surface/radius.

## Avoid

- Purple/pink AI gradients as the default brand expression.
- Large hero sections in the app shell.
- Decorative blobs, orbs, bokeh, and atmospheric background effects.
- Mixing rounded pill controls with rectangular workflow controls unless the component is truly a tab/pill.
- Raw hex values in React components.
