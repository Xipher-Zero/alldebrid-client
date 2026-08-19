# Corresponding source offer

The complete source code for DebridPulse is available from the repository identified
by the container image's `org.opencontainers.image.source` label. The exact
revision used to build an image is recorded in its
`org.opencontainers.image.revision` label.

For GPL- or LGPL-covered third-party binaries distributed in an official DebridPulse
container image, Chris Moore offers to provide the complete corresponding
source code, including the material needed to rebuild that software, to any
third party for no more than the reasonable cost of physically providing the
source. This offer is valid for three years after the last distribution of the
applicable image version.

Request source using the repository's dedicated source-request form:
<https://github.com/Xipher-Zero/debridpulse/issues/new?template=source_request.yml>.
Include:

- the full container image name and digest;
- the target architecture;
- the package name, if known; and
- a preferred machine-readable delivery method.

The image preserves Debian package copyright files under `/usr/share/doc` and
common license texts under `/usr/share/common-licenses`. Its published SBOM
attestation records the installed package versions needed to identify the
corresponding source precisely.
