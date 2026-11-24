# Recall website

React + Vite product website.

## Development

```sh
npm ci
npm run dev
```

## Production

```sh
npm run build
npm run preview
```

## Vercel

Import the repository using `main`. Set Root Directory to `website` and Framework
Preset to Vite. Build command: `npm run build`. Output directory: `dist`.

Components live in `src/App.jsx`. Scroll-driven product animation and its event
cleanup live in `src/useProductAnimation.js`. Styles use the desktop app's font
stacks and dark palette. Reduced-motion preferences are respected.
