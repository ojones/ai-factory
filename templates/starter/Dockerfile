# syntax=docker/dockerfile:1
#
# Multi-stage build, per STANDARDS-DEPLOYMENT.md:
#   - one container total (backend serves the built frontend itself —
#     no separate frontend container/app)
#   - minimal base image, non-root user, base image pinned by digest
#     (not just a floating tag, so a build is reproducible even if the
#     `20-alpine` tag is later repointed at a different image)
#
# Base image: node:20-alpine. To refresh the pinned digest (e.g. for a
# later Node LTS or a security patch), resolve the new digest with:
#   docker buildx imagetools inspect node:20-alpine
# and replace the sha256 below — this is the one line that intentionally
# needs a human (or Agent) to revisit periodically.
ARG BASE_IMAGE=node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293

# ---- Build stage: install all deps, compile backend + build frontend ----
FROM ${BASE_IMAGE} AS build
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
FROM ${BASE_IMAGE} AS runtime
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
