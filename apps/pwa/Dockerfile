# syntax=docker/dockerfile:1.25

# Build from the repository root:
# docker build -f apps/pwa/Dockerfile .
FROM node:24-alpine AS build

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable && corepack prepare pnpm@11.9.0 --activate

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

FROM nginx:1.27-alpine

COPY apps/pwa/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/apps/pwa/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
