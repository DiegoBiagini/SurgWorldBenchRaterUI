# HTTPS for the rater UI

The auth image ([`Dockerfile.auth`](Dockerfile.auth)) uses **HTTP Basic Auth**
on port 80. HTTPS does not change that prompt or the rater IDs. It only
encrypts the connection so the shared password is not sent in the clear.

This repo does not ship TLS. Add a certificate on a reverse proxy (or extend
nginx in the auth image). Streamlit stays on `127.0.0.1:8501` inside the
container.

## Certificates in practice

**Let’s Encrypt (public hostname).** The machine must be reachable on 80/443
under a DNS name you control (`rater.example.org`). [Certbot](https://certbot.eff.org/)
or Caddy obtain and renew a public cert automatically. This is the usual
choice for raters on the internet.

**Institution / company certificate.** IT issues a cert for your hostname
(often as `fullchain.pem` + `privkey.pem`). Point nginx or Caddy at those
files. Browsers already trust the campus CA, so there is no browser warning.

**Self-signed (lab / SSH tunnel only).** Fine for a single operator. Browsers
will warn; you must click through. Do not send this URL to a study cohort.

A cert is bound to a **hostname** (and sometimes IP). `https://10.0.0.5`
will not match a cert for `rater.example.org`.

## Recommended: TLS on the host, keep the auth container as HTTP

Leave [`docker-compose.auth.yml`](docker-compose.auth.yml) as it is (Basic Auth
on container port 80). On the host (or a second proxy container), terminate
HTTPS and forward to the published rater port (8501 → nginx 80).

That way the image does not need certs, renewals stay on the host, and
WebSockets still work if the outer proxy upgrades them.

### Caddy (Let’s Encrypt)

Install Caddy on the host. Example `Caddyfile` if the auth compose stack is
already listening on `127.0.0.1:8501`:

```caddy
rater.example.org {
    reverse_proxy 127.0.0.1:8501
}
```

Caddy obtains a Let’s Encrypt cert, serves HTTPS on 443, and upgrades
WebSockets by default. The browser still shows the Basic Auth dialog from
nginx inside the container.

Restrict compose to localhost so the rater is not reachable on plain HTTP
from the network:

```yaml
ports:
  - "127.0.0.1:8501:80"
```

### nginx on the host + Certbot

After `certbot certonly --nginx -d rater.example.org` (or `certbot certonly
--webroot`), a typical site config:

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    server_name rater.example.org;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name rater.example.org;

    ssl_certificate     /etc/letsencrypt/live/rater.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/rater.example.org/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 86400;
    }
}
```

`X-Forwarded-Proto` should be `https` so redirects and cookies see TLS.
`Upgrade` / `Connection` are required or Streamlit hangs on “Please wait…”.

Enable `certbot renew` (timer/cron). Reload nginx after renew if Certbot does
not do it for you.

### Institution cert files

Same nginx `server` block as above, but set `ssl_certificate` and
`ssl_certificate_key` to the paths IT gave you (often a full chain PEM plus
key). Do not commit the key. Mount it read-only if nginx runs in Docker.

## Alternative: TLS inside the auth container

You can extend [`docker/nginx.conf`](docker/nginx.conf) with `listen 443 ssl`,
mount the cert and key, and publish `443:443` instead of `8501:80`. Then the
container must be able to read the files (permissions, `www-data`). Let’s
Encrypt HTTP-01 typically needs port 80 on the **public** host, so renewals
are still easier on the host than inside this image.

This path is more work for little gain unless you cannot run a host proxy.

## What not to expect

- HTTPS does not add user accounts. It only protects the shared Basic Auth
  password in transit.
- Browsers cache Basic Auth credentials for the origin (`https://host`).
  Clearing them is a browser action, not a rater-ID logout.
- `localhost` with a public Let’s Encrypt cert is not useful; use a real DNS
  name, or a self-signed cert for local tests.
