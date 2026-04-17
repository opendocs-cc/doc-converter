# syntax=docker/dockerfile:1.6
FROM python:3.12-slim

# System dependencies:
#   libreoffice-writer / -calc : DOCX → PDF conversion
#   fonts-liberation           : Arial / Helvetica / Times metrics match —
#                                no line-break drift when Arial is absent
#   fonts-dejavu               : broad Unicode fallback coverage
#   fonts-inter, fonts-ibm-plex, : curated Google Fonts exposed via
#   fonts-lato, fonts-vollkorn   BrandingConfig.font_main — mixture of
#                                three sans (geometric / corporate / warm)
#                                and one serif (editorial). Merriweather
#                                (the second serif) is fetched directly from
#                                google/fonts because Debian doesn't ship it.
#                                Keep this list in sync with
#                                packages/shared/src/workspaces/validation.ts
#                                (EXPORT_FONTS) in the main repo.
#   tini                       : proper PID 1, reaps LibreOffice subprocesses
#
# Notes:
#   - fonts-ibm-plex lives in `contrib`, not `main`, on Debian trixie — we
#     enable contrib here so the package resolves.
#   - curl/ca-certificates are needed only to fetch Merriweather; we purge
#     curl at the end of the RUN to keep the image lean.
RUN sed -i 's/^Components: main$/Components: main contrib/' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        libreoffice-calc \
        fonts-liberation \
        fonts-dejavu \
        fonts-inter \
        fonts-ibm-plex \
        fonts-lato \
        fonts-vollkorn \
        fontconfig \
        ca-certificates \
        curl \
        tini \
    && mkdir -p /usr/share/fonts/truetype/merriweather \
    && curl -fsSL -o /usr/share/fonts/truetype/merriweather/Merriweather.ttf \
        "https://github.com/google/fonts/raw/main/ofl/merriweather/Merriweather%5Bopsz%2Cwdth%2Cwght%5D.ttf" \
    && curl -fsSL -o /usr/share/fonts/truetype/merriweather/Merriweather-Italic.ttf \
        "https://github.com/google/fonts/raw/main/ofl/merriweather/Merriweather-Italic%5Bopsz%2Cwdth%2Cwght%5D.ttf" \
    && fc-cache -f \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user in production
RUN useradd --create-home --shell /bin/bash --uid 10001 app

WORKDIR /app

# Python deps first so the layer caches across code changes
COPY --chown=app:app requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY --chown=app:app assets/ assets/
COPY --chown=app:app app/ app/

USER app

# Default concurrency — override with `-e CONVERT_MAX_WORKERS=N`
ENV CONVERT_MAX_WORKERS=6

EXPOSE 8080

# Health probe — orchestrators and `docker inspect` will see container health
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://localhost:8080/healthz', timeout=5).status == 200 else 1)" \
    || exit 1

# tini wraps uvicorn so signals and subprocesses behave.
# One uvicorn worker keeps CONVERT_MAX_WORKERS as the single concurrency knob
# (total concurrency = uvicorn workers × semaphore; we want just the semaphore).
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
