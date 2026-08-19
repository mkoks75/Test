# Productie-image voor de Hetzner-server.
#
# De app wordt gebouwd als losstaande Node-server (nitro node-server preset)
# en draait naast de PostgreSQL-container uit docker-compose.yml.

FROM oven/bun:1 AS build
WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . .

# Zonder deze preset bouwt nitro voor een edge-runtime; wij draaien Node.
ENV NITRO_PRESET=node-server
RUN bun run build

FROM oven/bun:1-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8000

# Alleen wat de server nodig heeft: build-output, migraties en de runner.
COPY --from=build /app/.output ./.output
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY db ./db
COPY scripts/migrate.mjs ./scripts/migrate.mjs

EXPOSE 8000

# Eerst migreren, dan pas de webserver starten.
CMD ["sh", "-c", "bun scripts/migrate.mjs && bun .output/server/index.mjs"]
