# Deployment Guide

Step-by-step instructions for deploying the OpenDocs Document Converter on a VPS using Docker.

## Prerequisites

- A VPS with Docker installed (tested on Ubuntu 22.04+ / Debian 12+)
- At least 4 GB RAM (LibreOffice needs memory for PDF conversions)
- The converter source code on the server

## 1. Get the code onto your server

```bash
# Option A: Clone from your private repo
ssh your-server
git clone git@github.com:your-org/doc-converter.git
cd doc-converter

# Option B: Copy from your local machine
scp -r ./doc-converter user@your-server:~/doc-converter
ssh your-server
cd doc-converter
```

## 2. Build the Docker image

```bash
docker build -t opendocs-converter .
```

This installs Python 3.12, LibreOffice Writer (for DOCX → PDF conversion), and all Python packages. The image is roughly 800 MB - 1 GB due to LibreOffice.

The first build takes 3-5 minutes on a typical VPS. Subsequent rebuilds are faster thanks to Docker layer caching — the LibreOffice and `requirements.txt` layers are cached unless you change them.

## 3. Run the container

```bash
docker run -d \
  --name opendocs-converter \
  --restart unless-stopped \
  -p 8080:8080 \
  -e CONVERT_MAX_WORKERS=6 \
  opendocs-converter
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CONVERT_MAX_WORKERS` | `6` | Max concurrent conversions. Set based on your CPU count — roughly 1.5x vCPUs is a good starting point. |

### Sizing guide

| VPS spec | Recommended workers | DOCX throughput | PDF throughput |
|----------|--------------------|-----------------|--------------------|
| 1 vCPU / 2 GB | 2 | ~30/min | ~10/min |
| 2 vCPU / 4 GB | 3 | ~60/min | ~20/min |
| 4 vCPU / 8 GB | 6 | ~100/min | ~40/min |

PDF is slower than DOCX because each PDF conversion spawns a LibreOffice process to print the Word document. This is the tradeoff for 100% visual consistency between formats.

## 4. Verify it's running

```bash
# Check container status
docker ps

# Check logs
docker logs opendocs-converter

# Hit the health endpoint
curl http://localhost:8080/health
```

Expected response:

```json
{"status": "ok", "version": "0.1.0", "max_workers": 6}
```

## 5. Test a conversion

```bash
# DOCX
curl -X POST http://localhost:8080/convert/docx \
  -H "Content-Type: application/json" \
  -d '{"markdown": "# Test Document\n\nThis is a test paragraph.\n\n| Col A | Col B |\n|-------|-------|\n| 1 | 2 |", "filename": "test"}' \
  -o test.docx

# PDF (goes through DOCX first, then LibreOffice prints to PDF)
curl -X POST http://localhost:8080/convert/pdf \
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

In production, the converter should only be accessible from your API server — not from the public internet. If both services are on the same VPS or Vultr VPC:

### Same VPS

Bind to localhost only instead of all interfaces:

```bash
docker run -d \
  --name opendocs-converter \
  --restart unless-stopped \
  -p 127.0.0.1:8080:8080 \
  -e CONVERT_MAX_WORKERS=6 \
  opendocs-converter
```

Your API server calls `http://localhost:8080/convert/docx` directly. No reverse proxy needed.

### Separate VPS on Vultr VPC

Bind to the private network IP:

```bash
# Find your private IP
ip addr show | grep "10\."

# Bind to private IP only
docker run -d \
  --name opendocs-converter \
  --restart unless-stopped \
  -p 10.x.x.x:8080:8080 \
  -e CONVERT_MAX_WORKERS=6 \
  opendocs-converter
```

Your API server calls `http://10.x.x.x:8080/convert/docx` over the private network. Block port 8080 in your Vultr firewall group so it's not exposed publicly.

## 8. Updating

When you push code changes:

```bash
cd doc-converter
git pull

# Rebuild and restart
docker build -t opendocs-converter .
docker stop opendocs-converter
docker rm opendocs-converter
docker run -d \
  --name opendocs-converter \
  --restart unless-stopped \
  -p 8080:8080 \
  -e CONVERT_MAX_WORKERS=6 \
  opendocs-converter
```

Or as a one-liner:

```bash
git pull && docker build -t opendocs-converter . && docker stop opendocs-converter && docker rm opendocs-converter && docker run -d --name opendocs-converter --restart unless-stopped -p 8080:8080 -e CONVERT_MAX_WORKERS=6 opendocs-converter
```

## 9. Monitoring

### Logs

```bash
# Follow logs in real time
docker logs -f opendocs-converter

# Last 100 lines
docker logs --tail 100 opendocs-converter
```

### Resource usage

```bash
# CPU and memory
docker stats opendocs-converter
```

### Restart on crash

The `--restart unless-stopped` flag handles this. Docker will restart the container automatically if it crashes. It won't restart if you explicitly stop it with `docker stop`.

## Troubleshooting

### LibreOffice conversion fails or hangs

SSH into the container and test manually:

```bash
docker exec -it opendocs-converter bash

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

LibreOffice uses more memory than the DOCX converter alone. Each PDF conversion can peak at 100-300 MB. Reduce `CONVERT_MAX_WORKERS` to limit how many run simultaneously:

```bash
# Restart with fewer workers
docker stop opendocs-converter && docker rm opendocs-converter
docker run -d \
  --name opendocs-converter \
  --restart unless-stopped \
  -p 8080:8080 \
  -e CONVERT_MAX_WORKERS=3 \
  opendocs-converter
```

### PDF conversions are slow

This is expected — each PDF conversion spawns a LibreOffice process. Typical conversion time is 1-3 seconds per document. For batch PDF jobs, the semaphore ensures they don't overwhelm the box.

If you need higher PDF throughput, scale horizontally by running multiple converter instances behind a load balancer, or use a larger VPS.

### Connection refused from API server

Check that the converter is bound to the right interface. `docker ps` shows the port mapping. If using VPC, verify both servers are in the same Vultr VPC and the private IP is reachable.
