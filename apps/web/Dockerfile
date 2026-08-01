# syntax=docker/dockerfile:1.7
FROM node:20-alpine AS base
RUN corepack enable && corepack prepare pnpm@9.7.0 --activate
WORKDIR /app

FROM base AS deps
COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml turbo.json ./
COPY apps/web/package.json apps/web/
COPY packages/ packages/
RUN pnpm install --frozen-lockfile || pnpm install

FROM deps AS development
COPY . .
EXPOSE 3000
CMD ["pnpm", "--filter", "@airevenueos/web", "dev"]

FROM deps AS build
COPY . .
# Only allowlisted, non-secret NEXT_PUBLIC_* variables reach the browser bundle.
ARG NEXT_PUBLIC_APP_URL
RUN pnpm --filter @airevenueos/web build

FROM node:20-alpine AS production
WORKDIR /app
RUN addgroup -g 10001 nodejs && adduser -u 10001 -G nodejs -S nextjs
COPY --from=build --chown=nextjs:nodejs /app/apps/web/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=nextjs:nodejs /app/apps/web/public ./apps/web/public
USER nextjs
EXPOSE 3000
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
CMD ["node", "apps/web/server.js"]
