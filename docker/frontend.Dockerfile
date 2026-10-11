# 前端镜像：构建 + nginx 托管（/api /mcp 反代到 backend:9310）
# 构建: docker build -t ai-system-frontend -f docker/frontend.Dockerfile .
FROM node:20-alpine AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com
COPY web/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
