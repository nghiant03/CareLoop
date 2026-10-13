FROM node:24-bookworm-slim AS builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:stable-alpine AS runtime
COPY deploy/frontend/nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /build/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080
# Bypass the image entrypoint scripts; runtime configuration is read-only.
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
