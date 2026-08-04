# Runbook: Storybook and the accessibility gate

## Commands

```bash
pnpm storybook                            # workshop on http://localhost:6006
pnpm --filter @airevenueos/web build-storybook   # static build into storybook-static/
pnpm a11y                                 # the gate: build, serve, scan every story
```

`pnpm a11y` is what CI runs (job "Accessibility (axe)"). It builds Storybook
statically, serves it on `127.0.0.1:6006`, and runs `@storybook/test-runner`,
which visits every story in Chromium and scans it with axe. First local run needs
`pnpm exec playwright install --with-deps chromium`.

## What is enforced

Tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, scoped to `#storybook-root` so
Storybook's own chrome cannot mask or manufacture a violation. Colour contrast is
deliberately enabled: it needs computed styles, so the vitest/jsdom tests cannot
see it, and the palette in `globals.css` is written to specific ratios that only
this check defends.

## Fixing a violation

1. `pnpm storybook`, open the failing story, read the **Accessibility** panel -
   it names the rule, the element and the fix.
2. Fix the component, not the story. A story that passes because it avoids the
   real props is worse than a red build.
3. Re-run `pnpm a11y`.

## The escape hatch, and when it is legitimate

```ts
export const SomeStory: Story = {
  // Third-party embed: the violation is in vendor markup we do not control.
  parameters: { a11y: { disable: true } },
};
```

Requires a comment saying why. Two rules of thumb: disabling a rule for the whole
project belongs in `.storybook/preview.ts` and needs review; disabling a scan for
one story because it is inconvenient is not a reason.

## Adding a component to the surface

Co-locate `component-name.stories.tsx` next to the component. Cover the states
review usually skips - empty, error, read-only, degraded - because those are where
unlabelled controls and colour-only status indicators survive.

## What this does not prove

Storybook renders components in isolation. It does not exercise page composition,
focus order across a real route, screen-reader announcement quality, or zoom and
reflow behaviour. Those need the manual screen-reader passes listed in
`docs/GA-ACTIVATION-CHECKLIST.md`, which remain outstanding.
