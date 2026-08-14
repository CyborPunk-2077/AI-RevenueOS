# syntax=docker/dockerfile:1.7
#
# The build context is the repository root (see docker-compose.yml), so the root
# .dockerignore governs what is copied in. That file is what keeps the host's
# apps/web/node_modules out of the image; without it, `COPY . .` merged the host
# tree over the installed one and the daemon aborted with
#   cannot copy to non-directory: .../apps/web/node_modules/@playwright/test
#
# pnpm, matching the `packageManager` field in the root package.json. An earlier
# revision used npm because no pnpm-lock.yaml existed; the lockfile is now
# committed, so `--frozen-lockfile` gives a genuinely reproducible install and the
# build fails loudly if package.json and the lockfile ever drift.

FROM node:20-alpine AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1 \
    PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
# Pinned by the root package.json, so the image cannot drift from the developer.
#
# `corepack enable` on its own only installs the *shims*. The pnpm binary itself
# is fetched lazily, the first time `pnpm` is actually invoked - and in the
# development stage below the first invocation is `CMD ["pnpm", "dev"]`, which
# runs when the container starts, not when the image is built.
#
# So the web container was downloading pnpm from registry.npmjs.org on **every
# start**, and a moment of network trouble stopped the whole demo: the launcher
# waited out its full five minutes, timed out on a web app that had never begun
# compiling, and suggested a destructive reset for what was a transient socket
# error. Somebody demonstrating this on a hotel network would have hit it too.
#
# `corepack prepare --activate` reads `packageManager` from the package.json
# copied beside it and downloads that exact version now, at build time, into the
# image. Startup is then offline.
COPY package.json ./package.json
RUN corepack enable && corepack prepare --activate

# --- dependencies -----------------------------------------------------------
FROM base AS deps
# Manifests and the lockfile only, so editing source does not invalidate this layer.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --filter @airevenueos/web...

# --- development (the target docker compose builds) -------------------------
FROM base AS development
ENV NODE_ENV=development
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/web/node_modules ./apps/web/node_modules
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# Source only. node_modules is excluded by the root .dockerignore, so this copy
# cannot overwrite the tree installed above.
COPY apps/web/ ./apps/web/
WORKDIR /app/apps/web
EXPOSE 3000
CMD ["pnpm", "dev"]

# --- production build -------------------------------------------------------
FROM base AS build
ENV NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/web/node_modules ./apps/web/node_modules
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/ ./apps/web/
WORKDIR /app/apps/web
RUN pnpm build

# --- production runtime -----------------------------------------------------
FROM node:20-alpine AS production
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0 NEXT_TELEMETRY_DISABLED=1
RUN addgroup -g 10001 nodejs && adduser -u 10001 -G nodejs -S nextjs
# next.config.mjs sets output: 'standalone', so the server and its minimal
# dependency closure are emitted into .next/standalone.
COPY --from=build --chown=nextjs:nodejs /app/apps/web/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/apps/web/.next/static ./apps/web/.next/static
USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://localhost:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "apps/web/server.js"]
