# syntax=docker/dockerfile:1

# ---------- Stage 1: build the Vue app ----------
FROM node:24-slim AS build

WORKDIR /app

# Install dependencies first: this layer is cached until package-lock.json changes
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

COPY . .
RUN npm run build-only

# ---------- Stage 2: serve it with nginx as a non-root user ----------
FROM nginxinc/nginx-unprivileged:1.31-alpine AS runtime

COPY nginx/default.conf nginx/proxy-hide-headers.inc /etc/nginx/conf.d/
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q --spider http://127.0.0.1:8080/ || exit 1
