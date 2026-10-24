# YubaPKG Roadmap - 1.1.0 and Beyond

YubaPKG owns dependency resolution, registry access, downloads, installation,
and publishing. YubaLANG executes programs and imports packages installed by
YubaPKG. Registry access is for package-management commands only; running a
locked project should work offline.

P0 items form the proposed 1.1.0 release gate. P1 and future items are the
larger package-manager and registry backlog; they are not all implied to ship
in 1.1.0.

## P0 - 1.1.0 registry and package contract

- [ ] Decide whether the first registry uses a static metadata/catalog plus
  immutable object storage or a hosted API, and record expected operating
  cost, availability, lookup latency, and maintenance tradeoffs.
- [ ] Specify registry URLs, package metadata schema, package-name rules,
  version format, YubaLANG compatibility declaration, dependency syntax,
  artifact URLs, and integrity metadata.
- [ ] Define immutable package release semantics, including how yanked,
  deprecated, or compromised versions are represented without silently
  changing an existing package.
- [ ] Define registry identity and trust policy, including whether multiple
  registries and private registries are supported in the initial format.
- [ ] Publish a registry format reference and examples that can be consumed
  by independent clients and mirrors.
- [ ] Keep the project manifest and lockfile readable, deterministic, and
  compatible with the YubaLANG runtime contract.

## P0 - Dependency resolution

- [ ] Implement semantic-version parsing and comparison, including prerelease
  ordering and invalid-version diagnostics.
- [ ] Define and implement supported version requirements such as exact
  versions, compatible ranges, inequalities, and wildcard behavior.
- [ ] Resolve direct and transitive dependencies deterministically and
  report incompatible constraints with the dependency paths that caused the
  conflict.
- [ ] Define behavior for cycles, duplicate package names from different
  sources, package aliases, optional dependencies, and platform-specific
  dependencies.
- [ ] Respect each package's declared YubaLANG compatibility and report
  incompatible runtime requirements before installing it.
- [ ] Make resolution stable across operating systems, registry response
  ordering, and repeated runs.
- [ ] Preserve existing path and Git dependencies during the registry
  transition, and specify how mixed source types participate in the graph.
- [ ] Add a lockfile version that captures the complete dependency graph,
  exact package versions, source registry, immutable artifact location,
  content hashes, and any required compatibility metadata.
- [ ] Define lockfile migration from the current direct path/Git format;
  never silently discard or rewrite a user's locked dependency choices.
- [ ] Make lockfile installs reproduce exact resolved versions without
  re-solving unless the user explicitly requests an update.

## P0 - Fast, reliable registry client

- [ ] Fetch metadata only for packages needed for resolution; avoid
  downloading a full registry catalog during normal install.
- [ ] Add an efficient package search index and document its update and
  consistency guarantees.
- [ ] Cache registry metadata with HTTP validators such as ETag or
  Last-Modified, and make cache expiration and offline behavior explicit.
- [ ] Cache verified immutable package artifacts by content hash and share
  them across projects where safe.
- [ ] Support offline install from a complete lockfile and local artifact
  cache; report exactly which required package is unavailable offline.
- [ ] Use connection/read timeouts, bounded retries, clear cancellation,
  useful progress reporting, and actionable errors for HTTP failures.
- [ ] Make concurrent installs safe when they share a cache; prevent
  corrupted partial downloads and handle interrupted processes.
- [ ] Avoid unnecessary serial network requests; batch independent metadata
  lookups or downloads where the registry permits, with a configurable
  concurrency limit only if needed.
- [ ] Measure cold and warm dependency-restore latency and registry request
  counts in tests or benchmarks; set targets before tuning.
- [ ] Support registry mirrors or alternate endpoints without making
  lockfiles ambiguous about artifact identity.

## P0 - Secure artifacts and installation

- [ ] Require SHA-256 or a stronger agreed content hash for every registry
  artifact, store it in the lockfile, and verify before extraction.
- [ ] Define safe archive extraction rules for traversal entries, absolute
  paths, symlinks, duplicate paths, malformed archives, excessive file
  counts, and oversized expanded content.
- [ ] Extract into a temporary location, validate the package, then install
  atomically; leave no success-shaped partial state after a failure.
- [ ] Ensure the manifest entry and every package file resolve inside the
  package root before reporting a successful install.
- [ ] Protect against cache path collisions, dependency name collisions,
  case-insensitive filesystem collisions, and unsafe package identifiers.
- [ ] Keep authentication secrets out of manifests, lockfiles, logs, and
  error messages; use the operating system's credential store where
  available and document secure fallback behavior.
- [ ] Define package signature or publisher-provenance requirements and
  implement them only with a clearly documented key lifecycle and
  verification model.
- [ ] Document that package installation does not sandbox executable
  package code and that YubaLANG imports can execute package top-level code.

## P0 - CLI and project workflow

- [ ] Keep `init`, `add`, `remove`, `install`, `update`, `list`, and `check`
  consistent across path, Git, and registry dependencies.
- [ ] Add package search and package/version information commands with
  useful output for maintainers and new users.
- [ ] Add a dependency tree command that shows versions, sources, and
  transitive relationships.
- [ ] Add outdated-dependency reporting without changing the lockfile.
- [ ] Clarify update behavior: update all, update one package and its
  necessary dependents, or update only explicitly selected dependencies.
- [ ] Add an explicit locked/frozen install mode for CI that fails if the
  manifest and lockfile disagree and never mutates either.
- [ ] Add cache inspection, verification, and targeted cleanup commands;
  never delete project or user data implicitly.
- [ ] Support global and per-project registry configuration with documented
  precedence and validation.
- [ ] Provide clear exit codes and actionable diagnostics for parse,
  resolution, compatibility, network, authentication, integrity, and
  filesystem errors.
- [ ] Make `--help` cover examples, source forms, offline usage, and
  publishing without requiring network access.

## P0 - Publishing and registry operations

- [ ] Specify package archive contents, exclusions, generated metadata,
  deterministic ordering, timestamps, and reproducible package hashes.
- [ ] Add a package validation command that checks manifest fields, name and
  version validity, entry files, compatibility, dependency declarations,
  archive safety, and license/attribution metadata.
- [ ] Add a dry-run publish command that shows the exact package contents,
  resolved metadata, and artifact hash before upload.
- [ ] Implement publishing to the chosen registry with authentication,
  immutable version enforcement, retry-safe upload behavior, and clear
  success/failure reporting.
- [ ] Define package-name ownership, publisher identity, transfer, and
  dispute procedures before opening public registration.
- [ ] Support deprecating or yanking a version while preserving existing
  lockfile installs; prevent destructive replacement of released artifacts.
- [ ] Define registry backup, restore, moderation, incident response, and
  availability expectations before depending on a public service.
- [ ] Document how a community member can host or mirror a registry and how
  clients choose trusted sources.

## P0 - Testing, compatibility, and release

- [ ] Add unit tests for version parsing, range matching, graph solving,
  conflict explanations, deterministic output, and lockfile migration.
- [ ] Run registry-client tests against a local test server for caching,
  conditional requests, offline mode, timeouts, retries, and HTTP errors.
- [ ] Add tests for corrupt and mismatched hashes, archive path traversal,
  malformed archives, interrupted downloads, and atomic install recovery.
- [ ] Add CLI end-to-end tests for project creation, adding registry
  dependencies, install/update/list/tree/check, and frozen CI installs.
- [ ] Add integration tests that install a transitive registry dependency
  graph and run its imports with the matching YubaLANG runtime offline.
- [ ] Test supported Python versions and Windows, Linux, and macOS path,
  cache, and archive behavior.
- [ ] Document supported manifest and lockfile versions, YubaLANG
  compatibility, registry configuration, cache location, and offline use.
- [ ] Publish YubaPKG 1.1.0 release notes, migration guidance, and known
  registry limitations.

## P1 - Registry ecosystem

- [ ] Add private registries and scoped authentication after the public
  registry contract is stable.
- [ ] Add package ownership teams, access roles, token revocation, and
  auditability for publishers.
- [ ] Add package readme, tags, categories, license metadata, maintainers,
  and compatibility filters to search results.
- [ ] Add vulnerability and malicious-package reporting, moderation queues,
  and a transparent security advisory process.
- [ ] Add registry protocol versioning and backward-compatible client
  negotiation.
- [ ] Add package mirroring/replication and geographic distribution if
  measured demand or latency warrants it.
- [ ] Add garbage collection for unreferenced artifacts with retention and
  recovery policies.
- [ ] Add signed release attestations and provenance verification once the
  identity and key-management model is operational.

## Future package-manager candidates

- [ ] Evaluate optional dependencies, feature flags, platform-specific
  packages, and alternate dependency groups.
- [ ] Evaluate workspace/monorepo support and local multi-package version
  coordination.
- [ ] Evaluate native build scripts and system dependencies only with a
  sandboxing, reproducibility, and consent model; do not execute arbitrary
  build hooks by default.
- [ ] Consider a package compatibility and deprecation bot or registry API
  for maintainers.
- [ ] Revisit hosting and performance choices using measured request volume,
  latency, cache hit rate, bandwidth, and operating cost.
