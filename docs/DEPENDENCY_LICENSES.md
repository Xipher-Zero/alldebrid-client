# Runtime dependency license inventory

This inventory covers every Python package pinned in
`backend/requirements.txt`. Package names and versions are enforced by
`backend/tests/test_license_policy.py`; a dependency change must update both
the lock file and `licenses/python-runtime.json`.

| Package | Version | License |
|---|---:|---|
| aiohappyeyeballs | 2.6.1 | PSF-2.0 |
| aiohttp | 3.14.3 | Apache-2.0 AND MIT |
| aiosignal | 1.4.0 | Apache-2.0 |
| aiosqlite | 0.22.1 | MIT |
| annotated-doc | 0.0.4 | MIT |
| annotated-types | 0.7.0 | MIT |
| anyio | 4.13.0 | MIT |
| attrs | 26.1.0 | MIT |
| bencode2 | 0.3.33 | MIT ([bundled notice](../licenses/bencode2-MIT.txt)) |
| click | 8.3.3 | BSD-3-Clause |
| fastapi | 0.141.1 | MIT |
| frozenlist | 1.8.0 | Apache-2.0 |
| h11 | 0.16.0 | MIT |
| httptools | 0.8.0 | MIT |
| idna | 3.15 | BSD-3-Clause |
| multidict | 6.7.1 | Apache-2.0 |
| prometheus-client | 0.26.0 | Apache-2.0 AND BSD-2-Clause |
| propcache | 0.5.2 | Apache-2.0 |
| pydantic | 2.13.4 | MIT |
| pydantic-core | 2.46.4 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| starlette | 1.3.1 | BSD-3-Clause |
| typing-extensions | 4.15.0 | PSF-2.0 |
| typing-inspection | 0.4.2 | MIT |
| uvicorn | 0.52.4 | BSD-3-Clause |
| uvloop | 0.22.1 | MIT OR Apache-2.0 |
| yarl | 1.23.0 | Apache-2.0 |

## Container components

The official image is built from `python:3.12.14-slim-trixie`. The base image
contains Python under the Python Software Foundation License and Debian system
components under their package-specific terms. DebridPulse directly installs the
following Debian packages; resolved binary versions and transitive packages are
recorded in the image's SBOM attestation.

| Direct package | License summary |
|---|---|
| aria2 | GPL-2.0-or-later |
| curl | curl |
| gosu | Apache-2.0 |
| 7zip | LGPL-2.1-or-later and package-specific component terms |
| 7zip-rar | Debian non-free RAR codec; UnRAR restricted freeware terms |

Package copyright files and common license texts remain installed in the
image. `SOURCE_OFFER.md` explains how to request corresponding source for
copyleft-covered binaries.

`7zip-rar` is installed from Debian's `non-free` component solely to provide
RAR extraction through the external `7z` process. Because the slim base filters
most package documentation, the Docker build explicitly re-includes the
`7zip-rar` Debian copyright notice and
`/usr/share/doc/7zip-rar/unRarLicense.txt` so those terms remain in the shipped
image.

Python packages retain their installed `.dist-info` license and notice files.
`bencode2` 0.3.33 is the exception: its wheel omits the upstream MIT text, so
DebridPulse explicitly packages that tagged notice at
`licenses/bencode2-MIT.txt`.

## Vendored browser resources

| Resource | Version/source | License |
|---|---|---|
| Chart.js | 4.4.1, vendored at `frontend/static/vendor/chart.umd.min.js` | MIT ([bundled notice](../licenses/Chart.js-MIT.txt)) |

## Browser-loaded resources

These font resources are requested by the browser from third-party CDNs and are not
copied into the repository or container image:

| Resource | Version/source | License |
|---|---|---|
| Outfit | Google Fonts | OFL-1.1 |
| JetBrains Mono | Google Fonts | OFL-1.1 |
| Bricolage Grotesque | Google Fonts (project landing page) | OFL-1.1 |
| DM Mono | Google Fonts (project landing page) | OFL-1.1 |
