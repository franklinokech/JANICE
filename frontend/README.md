# JANICE frontend

Vue 3 + TypeScript, built with Vite.

## Setup

```bash
nvm use          # Node 24, from .nvmrc
npm install
```

## Develop

```bash
npm run dev        # http://localhost:5173
npm run test:unit  # tests in watch mode while coding
```

## Checks (also run in CI)

```bash
npm test
npm run type-check
npm run lint
npm run format:check
npm run build
```

## Docker

The image builds the app with Node, then serves `dist/` with nginx
(non-root, port 8080). nginx also proxies `/api/` and `/admin/` to the
`backend` service. Configuration: `nginx/default.conf`.
