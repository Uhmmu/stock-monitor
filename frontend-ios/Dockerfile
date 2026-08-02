FROM node:22-alpine AS build
WORKDIR /app
COPY frontend-ios/package*.json ./frontend-ios/
RUN cd frontend-ios && npm install
COPY packages ./packages
COPY frontend-ios ./frontend-ios
RUN cd frontend-ios && npm run build

FROM nginx:1.27-alpine
COPY frontend-ios/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend-ios/dist /usr/share/nginx/html
