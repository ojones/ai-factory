# syntax=docker/dockerfile:1
#
# Multi-stage build, per STANDARDS-DEPLOYMENT.md:
#   - one container total (backend serves the built frontend itself —
#     no separate frontend container/app)
#   - minimal base image, non-root user, base image pinned by digest
#     (not just a floating tag, so a build is reproducible even if the
#     `22-alpine` tag is later repointed at a different image)
#
# Base image: node:22-alpine, pinned by digest in both FROM lines below. The image is written out in each
# FROM line (not through an ARG) so Dependabot's Docker updater can find it: it opens an update for a new digest
# or Node release, the Orchestrator turns that into an Update Intake, and the normal gate tests it.

# ---- Build stage: install all deps, compile backend + build frontend ----
FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS build
WORKDIR /app

# Install dependencies first, as their own layer, so source-only changes
# don't bust the (slow) npm install cache.
COPY package.json package-lock.json ./
COPY backend/package.json backend/package.json
COPY frontend/package.json frontend/package.json
RUN npm ci

COPY backend backend
COPY frontend frontend

# Root script builds the frontend (Vite -> frontend/dist) then the
# backend (tsc -> backend/dist).
RUN npm run build

# Strip dev-only dependencies (vite, typescript, vitest, tsx, ...) before
# carrying node_modules into the runtime image.
RUN npm prune --omit=dev

# ---- Runtime stage: minimal image, non-root, only what's needed to run ----
FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS runtime
WORKDIR /app
ENV NODE_ENV=production

COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/package.json ./package.json
COPY --from=build --chown=node:node /app/backend/package.json ./backend/package.json
COPY --from=build --chown=node:node /app/backend/dist ./backend/dist
COPY --from=build --chown=node:node /app/frontend/dist ./frontend/dist

# The official node:alpine image already defines an unprivileged `node`
# user (uid/gid 1000) — run as it instead of root.
USER node

EXPOSE 3000
CMD ["node", "backend/dist/index.js"]
