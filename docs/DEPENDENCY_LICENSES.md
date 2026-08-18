# Runtime dependency license inventory

This inventory covers every Python package pinned in
`backend/requirements.txt`. Package names and versions are enforced by
`backend/tests/test_license_policy.py`; a dependency change must update both
the lock file and `licenses/python-runtime.json`.

| Package | Version | License |
|---|---:|---|
| aiofiles | 25.1.0 | Apache-2.0 |
| aiohappyeyeballs | 2.6.1 | PSF-2.0 |
| aiohttp | 3.13.5 | Apache-2.0 AND MIT |
| aiosignal | 1.4.0 | Apache-2.0 |
| aiosqlite | 0.22.1 | MIT |
| annotated-doc | 0.0.4 | MIT |
| annotated-types | 0.7.0 | MIT |
| anyio | 4.13.0 | MIT |
| asyncpg | 0.31.0 | Apache-2.0 |
| attrs | 26.1.0 | MIT |
| bencode2 | 0.3.33 | MIT |
| click | 8.3.3 | BSD-3-Clause |
| fastapi | 0.136.1 | MIT |
| frozenlist | 1.8.0 | Apache-2.0 |
| h11 | 0.16.0 | MIT |
| httptools | 0.7.1 | MIT |
| idna | 3.15 | BSD-3-Clause |
| multidict | 6.7.1 | Apache-2.0 |
| prometheus_client | 0.25.0 | Apache-2.0 AND BSD-2-Clause |
| propcache | 0.5.2 | Apache-2.0 |
| pycryptodome | 3.23.0 | BSD-2-Clause and public-domain components |
| pydantic | 2.13.4 | MIT |
| pydantic_core | 2.46.4 | MIT |
| pydantic-settings | 2.14.1 | MIT |
| python-dotenv | 1.2.2 | BSD-3-Clause |
| python-multipart | 0.0.29 | Apache-2.0 |
| PyYAML | 6.0.3 | MIT |
| starlette | 1.3.1 | BSD-3-Clause |
| typing_extensions | 4.15.0 | PSF-2.0 |
| typing-inspection | 0.4.2 | MIT |
| uvicorn | 0.47.0 | BSD-3-Clause |
| uvloop | 0.22.1 | MIT OR Apache-2.0 |
| watchfiles | 1.1.1 | MIT |
| websockets | 16.0 | BSD-3-Clause |
| yarl | 1.23.0 | Apache-2.0 |

## Container components

The official image is built from `python:3.12.14-slim-bookworm`. The base image
contains Python under the Python Software Foundation License and Debian system
components under their package-specific terms. DebridPulse directly installs the
following Debian packages; resolved binary versions and transitive packages are
recorded in the image's SBOM attestation.

| Direct package | License summary |
|---|---|
| aria2 | GPL-2.0-or-later |
| curl | curl |
| gosu | Apache-2.0 |
| p7zip-full | LGPL-2.1-or-later and package-specific component terms |
| unrar-free | GPL-2.0-or-later |

Package copyright files and common license texts remain installed in the
image. `SOURCE_OFFER.md` explains how to request corresponding source for
copyleft-covered binaries.

## Browser-loaded resources

These resources are requested by the browser from third-party CDNs and are not
copied into the repository or container image:

| Resource | Version/source | License |
|---|---|---|
| Chart.js | 4.4.1 from cdnjs | MIT |
| Outfit | Google Fonts | OFL-1.1 |
| JetBrains Mono | Google Fonts | OFL-1.1 |
| Bricolage Grotesque | Google Fonts (project landing page) | OFL-1.1 |
| DM Mono | Google Fonts (project landing page) | OFL-1.1 |
