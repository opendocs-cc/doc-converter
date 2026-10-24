# syntax=docker/dockerfile:1.6
FROM python:3.12-slim

# System dependencies:
#   libreoffice-writer / -calc : DOCX → PDF conversion
#   fonts-liberation           : Arial / Helvetica / Times metrics match —
#                                no line-break drift when Arial is absent
#   fonts-dejavu               : broad Unicode fallback coverage
#   fonts-inter, fonts-ibm-plex, : curated free fonts exposed via
#   fonts-lato, fonts-vollkorn,  BrandingConfig.font_main: five sans
#   fonts-roboto-unhinted,       (Inter, IBM Plex Sans, Lato, Roboto,
#   fonts-manrope,               Manrope), three serifs (Vollkorn,
#   fonts-jetbrains-mono         Merriweather, EB Garamond) and one mono
#                                (JetBrains Mono). Merriweather and
#                                EB Garamond are downloaded as static TTFs
#                                (OFL, pinned commits) because Debian's are
#                                missing or incomplete; see the notes below.
#                                Keep this list in sync with
#                                packages/shared/src/workspaces/validation.ts
#                                (EXPORT_FONTS) in the main repo.
#   tini                       : proper PID 1, reaps LibreOffice subprocesses
#
# Notes:
#   - fonts-ibm-plex lives in `contrib`, not `main`, on Debian trixie — we
#     enable contrib here so the package resolves.
#   - Static weights, not variable fonts: LibreOffice exports a variable
#     font's default instance and fakes the bold. Debian's fonts-ebgaramond
#     only has a draft bold with partial character coverage, which
#     fontconfig never picks, so it's the same problem.
#   - curl/ca-certificates are needed only to fetch those fonts; we purge
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
        fonts-roboto-unhinted \
        fonts-manrope \
        fonts-jetbrains-mono \
        fontconfig \
        ca-certificates \
        curl \
        tini \
    && mkdir -p /usr/share/fonts/truetype/merriweather /usr/share/fonts/truetype/ebgaramond \
    && for style in Regular Italic Bold BoldItalic; do \
        curl -fsSL -o "/usr/share/fonts/truetype/merriweather/Merriweather-$style.ttf" \
            "https://raw.githubusercontent.com/SorkinType/Merriweather/4481226b336843648b5b2ee64f75737f262ded15/fonts/ttf/Merriweather-$style.ttf" \
        && curl -fsSL -o "/usr/share/fonts/truetype/ebgaramond/EBGaramond-$style.ttf" \
            "https://raw.githubusercontent.com/octaviopardo/EBGaramond12/106a4a6d377987459ae5e68673a4570f13b957fb/fonts/ttf/EBGaramond-$style.ttf" \
        || exit 1; \
    done \
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
