# Caddy with the production builds of the web app, the admin app and the marketing site (L04)
# (infra/compose.server.yaml).
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

# The marketing site reads profiles/ at build time for the interview guides (Q13).
FROM node-base AS site
WORKDIR /repo/apps/site
COPY apps/site/package.json apps/site/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY profiles/ /repo/profiles/
COPY apps/site/ ./
ARG SITE_URL=https://www.getstronghire.com
ARG PUBLIC_APP_URL=https://app.getstronghire.com
ARG PUBLIC_CTA=waitlist
RUN SITE_URL=$SITE_URL PUBLIC_APP_URL=$PUBLIC_APP_URL PUBLIC_CTA=$PUBLIC_CTA pnpm build

FROM caddy:2.10-alpine
COPY --from=web /app/dist /srv
COPY --from=admin /app/dist /srv-admin
COPY --from=site /repo/apps/site/dist /srv-site
COPY infra/caddy/Caddyfile /etc/caddy/Caddyfile
