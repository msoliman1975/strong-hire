FROM node:22-slim

# Trust extra CA certificates from infra/certs/*.crt (networks with TLS inspection).
COPY infra/certs/ /tmp/certs/
RUN cat /tmp/certs/*.crt > /usr/local/share/extra-ca.pem 2>/dev/null || true; rm -rf /tmp/certs
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/extra-ca.pem

RUN npm install -g pnpm@10.33.2 --silent

WORKDIR /app
COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/web/ ./

EXPOSE 5180
CMD ["pnpm", "dev", "--host", "0.0.0.0", "--port", "5180"]
