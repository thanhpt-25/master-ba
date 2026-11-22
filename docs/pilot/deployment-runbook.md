# Deployment runbook: one server with HTTPS

For a pilot team of up to about 20 people on one server. MasterBA runs in its container, bound to
`127.0.0.1`; a reverse proxy on the same host terminates TLS and is the only thing reachable from
the network. Spec: [19-deliverable-fit.md](../../specs/19-deliverable-fit.md) section 19.

## 1. What the application does and does not do

| Topic | As built |
|---|---|
| Accounts | Local accounts in `.masterba/users.json` (PBKDF2), created on the server with `masterba user add`. No SSO, no password reset in the dashboard. |
| Session | Signed cookie, `HttpOnly`, `SameSite=Strict`, 8 hours. It is marked `Secure` when the request arrived over HTTPS, which behind a proxy needs the forwarded headers to be trusted (section 4). |
| CSRF | Every state-changing request needs the header `X-MasterBA: 1`, which a cross-site form cannot send. |
| Headers | CSP without inline script or style, `nosniff`, frame deny, referrer policy. |
| Sign-in throttle | Five failed sign-ins within five minutes lock that name for five minutes. The count is kept in memory, so a restart clears it. |
| Not built in | TLS, request rate limiting, IP allow lists, audit export. The proxy (TLS, request size, rate limits) and the network (firewall, VPN) cover these. |
| Data | Everything is files in the work tree, which is a git repository: projects, documents, reviews, Decision Records. `.masterba/` holds accounts, jobs and uploads. |
| Model key | Read from the server environment (`ANTHROPIC_API_KEY`, or a gateway through `ANTHROPIC_BASE_URL`). The browser never sees it. |

## 2. Server

- Linux with Docker Engine and the compose plugin, 2 vCPU, 4 GB RAM, 20 GB disk (8 GB RAM with the
  `rag` extra for the local knowledge base model).
- A DNS name for the server, for example `masterba.example.co.jp`, and ports 80 and 443 open to the
  pilot team's network only (office range or VPN). Port 8000 stays closed.
- Outbound HTTPS to the model provider or gateway.

## 3. Install

```bash
git clone https://github.com/thanhpt-25/master-ba.git /opt/masterba
cd /opt/masterba
git checkout <release tag or commit agreed for the pilot>
mkdir -p work
cat > .env <<'ENV'
ANTHROPIC_API_KEY=<key>
MASTERBA_MODEL=<writer model>
MASTERBA_QA_MODEL=<stronger reviewer model>
GIT_AUTHOR_NAME=MasterBA Pilot
GIT_AUTHOR_EMAIL=masterba@example.co.jp
# The proxy reaches the container through the Docker bridge; trust its X-Forwarded-Proto.
# Safe only because the port is published on 127.0.0.1 (compose.yaml).
FORWARDED_ALLOW_IPS=*
ENV
chmod 600 .env
docker compose build
docker compose run --rm masterba doctor --init      # git work tree, templates, state
docker compose up -d
curl -s http://127.0.0.1:8000/api/health            # {"status":"ok",...}
```

`.env` is gitignored; keep a copy of it in the team's password manager, not in the repository.

## 4. Reverse proxy with TLS

### Caddy (recommended: it obtains and renews the certificate itself)

`/etc/caddy/Caddyfile`:

```caddyfile
masterba.example.co.jp {
    encode gzip
    request_body {
        max_size 25MB          # knowledge files are up to 20 MB
    }
    reverse_proxy 127.0.0.1:8000 {
        transport http {
            read_timeout 120s
        }
    }
    header Strict-Transport-Security "max-age=31536000"
}
```

Caddy sends `X-Forwarded-Proto: https`; with `FORWARDED_ALLOW_IPS` set, the application sees HTTPS
and marks the session cookie `Secure`.

When the company issues its own certificate, add `tls /etc/ssl/masterba.crt /etc/ssl/masterba.key`
inside the site block.

### nginx (alternative)

```nginx
server {
    listen 443 ssl http2;
    server_name masterba.example.co.jp;
    ssl_certificate     /etc/ssl/masterba.crt;
    ssl_certificate_key /etc/ssl/masterba.key;
    client_max_body_size 25m;
    add_header Strict-Transport-Security "max-age=31536000" always;
    limit_req zone=masterba burst=20 nodelay;   # with limit_req_zone in the http block

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 120s;
    }
}
server {
    listen 80;
    server_name masterba.example.co.jp;
    return 301 https://$host$request_uri;
}
```

Stage runs are background jobs, so no request waits for a model; the timeouts only cover uploads.

## 5. Accounts and roles

```bash
docker compose run --rm masterba user add tanaka --role admin      # prompts for the password
docker compose run --rm masterba user add sato --role approver
docker compose run --rm masterba user add suzuki --role viewer
docker compose run --rm masterba user list
```

| Role | Give it to |
|---|---|
| admin | the pilot lead: creates projects, confirms company templates, sets budgets |
| approver | reviewers who upload intakes, run phases, approve or reject, answer questions, decide DRs |
| viewer | everyone else who reads documents and traceability |

Passwords: at least 12 characters, handed over in person or through the password manager. A
role change takes effect on the next request; remove an account with `user remove <name>`.

## 6. Backups

The work tree is a git repository, so history is the backup format.

```bash
# /etc/cron.daily/masterba-backup
#!/bin/sh
set -eu
cd /opt/masterba/work
stamp=$(date +%F)
git bundle create /backup/masterba-$stamp.bundle --all
tar -czf /backup/masterba-state-$stamp.tar.gz .masterba
find /backup -name 'masterba-*' -mtime +30 -delete
```

Restore: `git clone /backup/masterba-<date>.bundle work`, then extract the state archive into
`work/`, then `docker compose run --rm masterba doctor`. Test a restore once before the pilot
starts.

The knowledge base sources and index (`projects/*/knowledge/sources`, `index`) are not in git; the
state archive does not hold them either. Keep the original files the team uploaded, or add
`projects/*/knowledge/sources` to the tar command.

## 7. Upgrade and rollback

```bash
cd /opt/masterba
docker compose run --rm masterba doctor     # before: clean work tree, no running job
git fetch && git checkout <new tag>
docker compose build && docker compose up -d
docker compose run --rm masterba doctor
```

A running job is shown as `interrupted` after a restart and can be resumed; upgrade when the
Overview shows no running job. Rollback is `git checkout <previous tag>` and the same two commands;
the store format has not changed between pilot releases.

## 8. Before inviting the team

- [ ] `https://masterba.example.co.jp/api/health` answers over HTTPS; `http://` redirects.
- [ ] Port 8000 is not reachable from another machine (`curl http://<server ip>:8000` fails).
- [ ] After signing in, the browser's developer tools show the session cookie with `Secure`,
      `HttpOnly` and `SameSite=Strict`.
- [ ] `doctor` reports the model key and a clean work tree.
- [ ] One test project ran BRD on a sample intake from start to `in_review` and the Excel download
      opens in Excel.
- [ ] A backup was taken and restored once on another folder.
- [ ] Each person has an account with the right role and has signed in once.
