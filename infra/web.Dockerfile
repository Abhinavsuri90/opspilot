FROM public.ecr.aws/docker/library/node:22-alpine AS builder
WORKDIR /workspace/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build

FROM public.ecr.aws/docker/library/node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
COPY --from=builder --chown=node:node /workspace/apps/web/.next/standalone ./
COPY --from=builder --chown=node:node /workspace/apps/web/.next/static ./.next/static
COPY --from=builder --chown=node:node /workspace/apps/web/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
