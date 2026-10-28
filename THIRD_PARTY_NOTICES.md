# Third-party notices

The OpenDocs Document Converter is licensed under the MIT license (see [LICENSE](LICENSE)). It uses the third-party components below, which keep their own licenses. None of them is modified; the Python packages are installed from PyPI by `pip install -r requirements.txt` and the system packages from Debian by the [Dockerfile](Dockerfile). Nothing below is copied into this repository.

This list covers the notable components. The full license texts ship with each package: in each Python package's `*.dist-info` directory, and for Debian packages in `/usr/share/doc/<package>/copyright` inside the image.

## Libraries and programs

| Component | License | How it's used |
| --- | --- | --- |
| [CairoSVG](https://github.com/Kozea/CairoSVG) | LGPL-3.0-or-later | Python package, used unmodified as a library to rasterize SVG images. It is installed separately and can be replaced with any compatible version. |
| [cairocffi](https://github.com/Kozea/cairocffi), cssselect2, tinycss2 | BSD-3-Clause | CairoSVG's dependencies |
| cairo (`libcairo2`) | LGPL-2.1 or MPL-1.1 | System library CairoSVG draws with; installed in the image as a LibreOffice dependency |
| [LibreOffice](https://www.libreoffice.org/) (`libreoffice-writer`, `libreoffice-calc`, `libreoffice-math`, `python3-uno`) | MPL-2.0 (some parts under other free licenses, listed in its Debian copyright files) | Installed in the Docker image and run as a separate program to print DOCX to PDF |
| [unoserver](https://github.com/unoconv/unoserver) | MIT | Installed in the Docker image; keeps LibreOffice running between conversions |
| [tini](https://github.com/krallin/tini) | MIT | Installed in the Docker image as PID 1 |
| [certifi](https://github.com/certifi/python-certifi) | MPL-2.0 | CA certificate bundle, a dependency of httpx |
| [Python](https://www.python.org/) (`python:3.12-slim` base image) | PSF-2.0 | Runtime; the base image is Debian, whose packages carry their own licenses |

## Fonts

All fonts are installed into the Docker image at build time; none are in this repository.

| Font | Source | License |
| --- | --- | --- |
| Liberation (Arial, Times, Courier metrics) | Debian `fonts-liberation` | OFL-1.1 |
| DejaVu | Debian `fonts-dejavu` | Bitstream Vera Fonts License, plus public-domain DejaVu changes |
| Noto Color Emoji | Debian `fonts-noto-color-emoji` | OFL-1.1 |
| Noto CJK | Debian `fonts-noto-cjk` | OFL-1.1 |
| STIX | Debian `fonts-stix` | OFL-1.1 |
| Inter | Debian `fonts-inter` | OFL-1.1 |
| IBM Plex | Debian `fonts-ibm-plex` | OFL-1.1 |
| Lato | Debian `fonts-lato` | OFL-1.1 |
| Vollkorn | Debian `fonts-vollkorn` | OFL-1.1 |
| Roboto | Debian `fonts-roboto-unhinted` | Apache-2.0 |
| Manrope | Debian `fonts-manrope` | OFL-1.1 |
| JetBrains Mono | Debian `fonts-jetbrains-mono` | OFL-1.1 |
| Merriweather | Static TTFs downloaded from [SorkinType/Merriweather](https://github.com/SorkinType/Merriweather) at a pinned commit | OFL-1.1 |
| EB Garamond | Static TTFs downloaded from [octaviopardo/EBGaramond12](https://github.com/octaviopardo/EBGaramond12) at a pinned commit | OFL-1.1 |

Fonts are used to lay out and print documents. Fonts embedded in exported PDFs stay under their own licenses, which allow embedding.

## Other Python dependencies

The remaining Python dependencies (from `requirements.txt` and what they pull in) are under permissive licenses: MIT, MIT-0 or MIT-CMU (python-docx, markdown-it-py, mdit-py-plugins, mdurl, latex2mathml, FastAPI, Pydantic, Pillow, cffi, anyio, h11, httptools, watchfiles, PyYAML, typing-inspection, annotated-types, annotated-doc), BSD (Pygments, emoji, httpx, httpcore, idna, lxml, uvicorn, starlette, click, python-dotenv, websockets, pycparser, webencodings), PSF-2.0 (typing_extensions, defusedxml), Apache-2.0 (opentelemetry-api, required by FastAPI) and MIT or Apache-2.0 (uvloop).

This was checked against the installed package metadata. Versions aren't pinned, so check again (for example with `pip-licenses`) when dependencies change.
