# Caddy with the production web build (infra/compose.server.yaml).
FROM node:22-slim AS web
RUN npm install -g pnpm@10.33.2 --silent
WORKDIR /app
COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/web/ ./
RUN pnpm build

FROM caddy:2.10-alpine
COPY --from=web /app/dist /srv
COPY infra/caddy/Caddyfile /etc/caddy/Caddyfile
