FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund --loglevel=error
COPY . .
RUN CI=false GENERATE_SOURCEMAP=false npm run build

FROM nginx:1.27-alpine
COPY nginx-maps.conf /etc/nginx/conf.d/00-maps.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html
EXPOSE 80
