# Caddy with the production builds of the web app, the admin app and the marketing site (infra/compose.server.yaml).
# Build context: the repo root.
FROM node:22-slim AS node-base
# Trust extra CA certificates from infra/certs/*.crt (networks with TLS inspection).
COPY infra/certs/ /tmp/certs/
RUN cat /tmp/certs/*.crt > /usr/local/share/extra-ca.pem 2>/dev/null || true; rm -rf /tmp/certs
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/extra-ca.pem
RUN npm install -g pnpm@10.33.2 --silent

FROM node-base AS web
WORKDIR /app
COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/web/ ./
RUN pnpm build

FROM node-base AS admin
WORKDIR /app
COPY apps/admin/package.json apps/admin/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/admin/ ./
RUN pnpm build

# The marketing site (L04). Guides read /profiles at build time, so keep the repo layout.
FROM node-base AS site
WORKDIR /app/apps/site
COPY apps/site/package.json apps/site/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY profiles/ /app/profiles/
COPY apps/site/ ./
RUN pnpm build

FROM caddy:2.10-alpine
COPY --from=web /app/dist /srv
COPY --from=admin /app/dist /srv-admin
COPY --from=site /app/apps/site/dist /srv-site
COPY infra/caddy/Caddyfile /etc/caddy/Caddyfile
