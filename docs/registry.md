# Static registry protocol (schema 1)

YubaPKG's initial registry client uses static HTTPS metadata and immutable
`tar.gz` artifacts. No public registry service is deployed by this repository;
operators may host these files on a static HTTPS origin.

## Trust and configuration

Set `YUBAPKG_REGISTRY_URL` to the trusted registry base URL, for example:

```powershell
$env:YUBAPKG_REGISTRY_URL = "https://packages.example.org"
yubapkg package add text_utils --registry "^1.2.0"
```

The URL must not contain credentials, a query, or a fragment. Registry and
artifact requests use HTTPS, verified TLS, a 15-second socket timeout, and
same-origin redirects only. HTTP is accepted only for localhost test fixtures.
Artifact URLs may not contain credentials, queries, or fragments. The client
does not implement authentication, private registries, mirrors, signatures,
publisher identity, or a public-registry hostname.

The resolved registry origin and artifact digest are recorded in lockfile
format 3. Released artifacts must be immutable. A version may be marked
`"yanked": true`; new resolution skips yanked releases, while an existing
lockfile continues to identify its exact artifact.

## Metadata layout

The client requests one metadata document per needed package:

```text
GET /v1/packages/<URL-encoded-package-name>.json
```

Example:

```json
{
  "schema_version": 1,
  "name": "text_utils",
  "versions": {
    "1.2.3": {
      "yubalang": ["1.3"],
      "artifact": "artifacts/text_utils-1.2.3.tar.gz",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "yanked": false
    }
  }
}
```

`name` must match the requested package. Version keys are strict
`MAJOR.MINOR.PATCH` semantic versions, including optional prerelease and build
metadata. Each release has a non-empty `yubalang` compatibility list, a
same-origin artifact URL, and a lowercase SHA-256 digest. `yanked` is optional
and defaults to false. The client currently resolves releases compatible with
YubaLANG 1.3.

Requirements support exact versions, `^` and `~` ranges, `<`, `<=`, `>`, `>=`,
`=`, and `x`/`*` wildcards. Whitespace or commas combine comparators as AND. Prereleases are considered
only when the requirement mentions a prerelease with the candidate's same
major, minor, and patch version. The resolver selects the highest matching
non-yanked version.

## Artifacts and limits

Artifacts are gzip-compressed tar archives whose root contains `yuba.json`
and the package entry. The manifest package name and version must match the
metadata. Archive links, special files, path traversal, absolute paths,
duplicate portable paths, and case-insensitive path collisions are rejected.
Extraction is staged and installed atomically.

Limits are 4 MiB per metadata response, 64 MiB per artifact, 256 MiB expanded
content, and 20,000 archive entries. SHA-256 is verified before extraction.
The lockfile also records a deterministic package-tree digest; `package check`
verifies both cached artifact integrity and installed package contents without
network access.

The project-local cache uses `.yuba/registry` for metadata,
`.yuba/artifacts` for content-addressed archives, and `.yuba/packages` for
installed packages. `yubapkg package install --offline` requires a lockfile
and cached artifacts for every locked registry dependency. Resolving a new
package while offline also requires cached metadata. `--frozen` verifies the
current lock and installation without resolving, downloading, or writing.

Package archives execute with the permissions of the YubaLANG process when
imported; neither YubaPKG nor YubaLANG sandboxes dependencies.

## Not included yet

This protocol does not provide package publishing, upload authentication,
search, package information, dependency-tree or outdated commands, retries,
shared global caches, concurrent-download coordination, signatures, or
publisher provenance. Registry hosting, ownership, moderation, backup, and
incident-response policies must be established before operating a public
service.
