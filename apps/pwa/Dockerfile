# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12

# Build from the repository root:
# docker build -f apps/pwa/Dockerfile .
FROM node:24-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43 AS build

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable && corepack prepare pnpm@11.22.0 --activate

WORKDIR /workspace

ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_SENTRY_DSN=
ARG VITE_SENTRY_ENVIRONMENT=local
ARG VITE_SENTRY_RELEASE=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_SENTRY_DSN=${VITE_SENTRY_DSN}
ENV VITE_SENTRY_ENVIRONMENT=${VITE_SENTRY_ENVIRONMENT}
ENV VITE_SENTRY_RELEASE=${VITE_SENTRY_RELEASE}

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY apps/pwa/package.json apps/pwa/package.json
COPY packages/openapi/package.json packages/openapi/package.json
COPY packages/openapi-client/package.json packages/openapi-client/package.json
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --filter @poker-hero/pwa...

COPY apps/pwa apps/pwa
COPY packages/openapi packages/openapi
COPY packages/openapi-client packages/openapi-client
RUN pnpm pwa:build

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10

COPY apps/pwa/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/apps/pwa/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
