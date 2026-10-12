FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
RUN caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
EXPOSE 3030
