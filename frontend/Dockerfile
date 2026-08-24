FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm install
COPY packages ./packages
COPY frontend ./frontend
ARG VITE_BASE_PATH=/
RUN cd frontend && npm run build -- --base "$VITE_BASE_PATH"

FROM nginx:1.27-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html
