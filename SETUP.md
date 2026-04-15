# Deployment Guide

Step-by-step instructions for deploying the OpenDocs Document Converter on a VPS using Docker.

## Prerequisites

- A VPS with Docker installed (tested on Ubuntu 22.04+ / Debian 12+)
- At least 4 GB RAM (LibreOffice needs memory for PDF conversions)
- The converter source code on the server

SSH into your fresh Ubuntu instance:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Enable automatic security updates
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh

# Add your user to the docker group (log out and back in after)
sudo usermod -aG docker $USER

# Install Docker Compose plugin
sudo apt install -y docker-compose-plugin

# Verify
docker --version
docker compose version
```

## 1. Get the code onto your server

```bash
# Option A: Clone from your private repo
ssh your-server
git clone git@github.com:your-org/doc-converter.git
cd doc-converter
```

## 2. Configure environment

The service is deployed with Docker Compose. Config comes from a `.env` file in the repo root — Compose auto-loads it.

```bash
cp .env.example .env
```

Open `.env` and set the three values for your box:

| Variable              | Default     | What to set                                                                                                               |
| --------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------- |
| `CONVERT_MAX_WORKERS` | `3`         | Max concurrent conversions. Roughly `1.5 × vCPUs` — see the sizing guide below.                                           |
| `MEMORY_LIMIT`        | `3G`        | Hard cap on the container. Leave ~1 GB for host OS overhead. LibreOffice peaks at 100–300 MB per PDF conversion.          |
| `VPC_BIND_IP`         | `10.8.96.3` | The interface the container publishes `:8080` on. Set to the box's VPC IP (private-only), or `127.0.0.1` for same-host API. |

### Sizing guide

| VPS spec        | `CONVERT_MAX_WORKERS` | `MEMORY_LIMIT` | DOCX/min | PDF/min |
| --------------- | --------------------- | -------------- | -------- | ------- |
| 1 vCPU /  2 GB  | 2                     | `1500M`        | ~30      | ~10     |
| 2 vCPU /  4 GB  | 3                     | `3G`           | ~60      | ~20     |
| 4 vCPU /  8 GB  | 6                     | `7G`           | ~100     | ~40     |
| 8 vCPU / 16 GB  | 12                    | `15G`          | ~200     | ~80     |

PDF is slower than DOCX because each PDF conversion spawns a LibreOffice process to print the Word document. This is the tradeoff for 100% visual consistency between formats.

## 3. Build and start the service

```bash
docker compose up -d --build
```

Compose builds the image (Python 3.12 + LibreOffice + fonts; roughly 800 MB–1 GB) and starts the container detached. The first build takes 3–5 minutes on a typical VPS; subsequent builds hit the cached LibreOffice and `requirements.txt` layers unless `Dockerfile` or `requirements.txt` changes.

## 4. Verify it's running

```bash
# Check container status
docker compose ps

# Check logs
docker compose logs

# Hit the health endpoint on the bound interface (matches VPC_BIND_IP)
curl http://$(grep ^VPC_BIND_IP .env | cut -d= -f2 | tr -d '"'):8080/health

# …or from inside the container (always works regardless of VPC_BIND_IP)
docker compose exec converter wget -qO- http://localhost:8080/health
```

Expected response:

```json
{ "status": "ok", "version": "0.1.0", "max_workers": 6 }
```

## 5. Test a conversion

Run from the converter box. Substitute `$VPC_BIND_IP` with the value you set in `.env` (or use `127.0.0.1` if you bound to loopback).

```bash
# DOCX
curl -X POST http://$VPC_BIND_IP:8080/convert/docx \
  -H "Content-Type: application/json" \
  -d '{"markdown": "# Test Document\n\nThis is a test paragraph.\n\n| Col A | Col B |\n|-------|-------|\n| 1 | 2 |", "filename": "test"}' \
  -o test.docx

# PDF (goes through DOCX first, then LibreOffice prints to PDF)
curl -X POST http://$VPC_BIND_IP:8080/convert/pdf \
  -H "Content-Type: application/json" \
  -d '{"markdown": "# Test Document\n\nThis is a test paragraph.", "filename": "test"}' \
  -o test.pdf
```

Open both files — they should look identical. Purple headings, styled table, "OpenDocs" footer.

## 6. Set up a reverse proxy (optional but recommended)

If you want the converter accessible via a subdomain (e.g., `convert.opendocs.cc`), add it to your Caddy or Nginx config.

### Caddy example

Add to your `Caddyfile`:

```
convert.opendocs.cc {
    reverse_proxy localhost:8080
}
```

Then reload Caddy:

```bash
docker exec caddy caddy reload --config /etc/caddy/Caddyfile
```

### Nginx example

```nginx
server {
    listen 443 ssl;
    server_name convert.opendocs.cc;

    # SSL certs (use certbot or similar)
    ssl_certificate /etc/letsencrypt/live/convert.opendocs.cc/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/convert.opendocs.cc/privkey.pem;

    client_max_body_size 10M;

    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 7. Internal-only access (recommended for production)

In production the converter should only be reachable from your API server — never from the public internet. Two topologies; pick the one that matches your setup.

### The mental model

```
                 Public internet
                       │
                       ▼
           ┌───────────────────────────┐
           │ API server                │  Public IP:  45.x.x.x
           │ api.opendocs.cc           │  Private IP: 10.0.0.10
           │ (Next.js / FastAPI / ...) │
           └──────────┬────────────────┘
                      │ HTTP over private network
                      ▼
           ┌───────────────────────────┐
           │ Converter server          │  No public IP (or firewalled)
           │ (this Dockerfile)         │  Private IP: 10.0.0.20
           │ Port 8080                 │
           └───────────────────────────┘
                      ▲
                      │ Both servers in the same
                      │ Vultr VPC ("VPC 2.0")
```

The converter listens on a **private-only** address. Your API calls it. No TLS, no auth middleware, no public exposure — the network itself is the boundary.

Both options are driven by the same knob — `VPC_BIND_IP` in `.env`. Set it, then `docker compose up -d` to apply.

### Option A — Same VPS (API and converter on one box)

Bind to loopback only. In `.env`:

```
VPC_BIND_IP=127.0.0.1
```

Then:

```bash
docker compose up -d
```

Your API calls `http://localhost:8080/convert/docx` directly. Nothing outside the box can reach the converter — the OS network stack enforces it.

### Option B — Separate VPS on a Vultr VPC (the pattern in the diagram)

There are three moving pieces.

**1. Provision a VPC in the Vultr console.**
A VPC is a private L2 network that only your own servers see. You create one in the Vultr "VPC 2.0" section, then attach each server to it. Each server gets a second NIC with a `10.x.x.x` address that is not routable from the internet.

**2. Bind the container to the private NIC only.**

```bash
# On the converter box, find the VPC IP
ip -4 addr show | grep "inet 10\."
# e.g. inet 10.0.0.20/20  ...
```

Put that IP in `.env`:

```
VPC_BIND_IP=10.0.0.20
```

Then:

```bash
docker compose up -d
```

The compose file publishes port 8080 only on the private NIC (`${VPC_BIND_IP}:8080:8080`). The public NIC has nothing listening on 8080. Add a Vultr firewall rule denying inbound 8080 on the public interface as belt-and-suspenders.

**3. Reach it from your API.** You have two options for the URL the API uses.

| Approach                   | Setup                                                                                                                                  | URL your API calls                         |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| **Private IP directly**    | Nothing — just hardcode the `10.x.x.x` address (or put it in `DOC_CONVERTER_URL` env var).                                             | `http://10.0.0.20:8080`                    |
| **Internal DNS subdomain** | Add an A-record: `convert.internal.opendocs.cc → 10.0.0.20`. DNS resolution is public, but the returned IP only routes inside the VPC. | `http://convert.internal.opendocs.cc:8080` |

The internal-DNS approach is cleaner — you can move the converter to a new box and just update the DNS record, no redeploy. An attacker can `dig` the record and see `10.0.0.20`, but they can't route there from outside the VPC.

### Calling from your API

```ts
const CONVERTER_URL = process.env.DOC_CONVERTER_URL!;
// e.g. "http://convert.internal.opendocs.cc:8080"
//  or  "http://10.0.0.20:8080"

const res = await fetch(`${CONVERTER_URL}/convert/pdf`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    markdown,
    filename: "report",
    branding,
  }),
});
if (!res.ok) throw new Error(`converter ${res.status}: ${await res.text()}`);
const pdf = Buffer.from(await res.arrayBuffer());
```

No TLS, no bearer tokens, no signing — traffic never leaves the VPC.

### If you later want HTTPS

Sometimes compliance or defense-in-depth demands TLS even on private networks. Let's Encrypt's **HTTP-01 challenge won't work** because it can't reach a private IP. Use **DNS-01** instead — Caddy does this with one config block when your DNS is on a supported provider (Cloudflare, Route 53, etc.):

```caddy
convert.internal.opendocs.cc {
    tls {
        dns cloudflare {env.CLOUDFLARE_API_TOKEN}
    }
    reverse_proxy localhost:8080
}
```

Caddy will issue and renew the cert entirely through DNS. Your API then calls `https://convert.internal.opendocs.cc` — fully encrypted, private-only.

Until you actually need this, plain HTTP over the VPC is fine. Vultr's VPC is isolated at the hypervisor level; adding TLS on top has real handshake-latency cost and doesn't change the threat model meaningfully.

## 8. Updating

When you push code changes:

```bash
cd doc-converter
git pull
docker compose up -d --build
```

Compose rebuilds only the layers that changed and recreates the container with the new image in one step. Config from `.env` and the `restart: unless-stopped` policy carry over automatically — no need to re-pass flags.

## 9. Monitoring

### Logs

```bash
# Follow logs in real time
docker compose logs -f

# Last 100 lines
docker compose logs --tail 100
```

### Resource usage

```bash
# CPU and memory
docker stats opendocs-converter
```

### Restart on crash

The `restart: unless-stopped` policy in `docker-compose.yml` handles this. Docker will restart the container automatically if it crashes. It won't restart if you explicitly `docker compose stop`.

## Troubleshooting

### LibreOffice conversion fails or hangs

SSH into the container and test manually:

```bash
docker compose exec converter bash

# Create a test DOCX
python -c "
from docx import Document
doc = Document()
doc.add_heading('Test', level=1)
doc.add_paragraph('Hello world')
doc.save('/tmp/test.docx')
"

# Test LibreOffice conversion
soffice --headless --norestore --convert-to pdf --outdir /tmp /tmp/test.docx
ls -la /tmp/test.pdf
```

If `soffice` hangs, it may be a lock file issue. Kill any stale processes and clean up:

```bash
rm -rf /tmp/.~lock.* /tmp/lu*
killall -9 soffice.bin 2>/dev/null
```

### Out of memory on large documents

LibreOffice uses more memory than the DOCX converter alone. Each PDF conversion can peak at 100-300 MB. Drop `CONVERT_MAX_WORKERS` (and optionally raise `MEMORY_LIMIT`) in `.env`, then redeploy:

```bash
# Edit .env — e.g. CONVERT_MAX_WORKERS=3
docker compose up -d
```

Compose detects the env change and recreates the container with the new limits.

### PDF conversions are slow

This is expected — each PDF conversion spawns a LibreOffice process. Typical conversion time is 1-3 seconds per document. For batch PDF jobs, the semaphore ensures they don't overwhelm the box.

If you need higher PDF throughput, scale horizontally by running multiple converter instances behind a load balancer, or use a larger VPS.

### Connection refused from API server

Check that the converter is bound to the right interface. `docker compose ps` shows the port mapping — the left side should match `VPC_BIND_IP` in `.env`. If using VPC, verify both servers are in the same Vultr VPC and the private IP is reachable (e.g. `ping 10.0.0.20` from the API box).
