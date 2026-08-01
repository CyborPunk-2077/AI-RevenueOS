# syntax=docker/dockerfile:1.7
#
# The build context is the repository root (see docker-compose.yml), so the root
# .dockerignore governs what is copied in. That file is what keeps the host's
# apps/web/node_modules out of the image; without it, `COPY . .` merged the host
# tree over the installed one and the daemon aborted with
#   cannot copy to non-directory: .../apps/web/node_modules/@playwright/test
#
# npm rather than pnpm: there is no pnpm-lock.yaml in the repository, so
# `pnpm install --frozen-lockfile` can never succeed, and packages/* are empty
# directories with no package.json, so workspace filtering has nothing to resolve.

FROM node:20-alpine AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

# --- dependencies -----------------------------------------------------------
FROM base AS deps
# Manifests first, so editing source does not invalidate the dependency layer.
# The glob keeps this working on a clone that has not generated a lockfile yet.
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; \
    else npm install --no-audit --no-fund; fi

# --- development (this is the target docker compose builds) -----------------
FROM base AS development
ENV NODE_ENV=development
COPY --from=deps /app/node_modules ./node_modules
# Source only. node_modules is excluded by the root .dockerignore, so this copy
# cannot overwrite the tree installed above.
COPY apps/web/ ./
EXPOSE 3000
CMD ["npm", "run", "dev"]

# --- production build -------------------------------------------------------
FROM base AS build
ENV NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ ./
RUN npm run build

# --- production runtime -----------------------------------------------------
FROM node:20-alpine AS production
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0 NEXT_TELEMETRY_DISABLED=1
RUN addgroup -g 10001 nodejs && adduser -u 10001 -G nodejs -S nextjs
# next.config.mjs sets output: 'standalone', so the server and its minimal
# dependency closure are emitted into .next/standalone.
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://localhost:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
