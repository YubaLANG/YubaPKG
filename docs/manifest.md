# Project manifest and lockfile

YubaPKG reads `yuba.json` from the current directory or its parents. A
minimal project manifest is:

```json
{
  "name": "sample",
  "version": "0.1.0",
  "entry": "main.yl",
  "yubalang": "1.3",
  "dependencies": {}
}
```

The `name`, `version`, `entry`, and `yubalang` values are required strings.
Package names start with a letter and may contain letters, digits, underscores,
and hyphens. YubaPKG accepts YubaLANG versions `1.2` and `1.3`. New projects
target `1.3`.

## Dependencies

Direct path dependencies point to another directory containing a `yuba.json`:

```json
{
  "dependencies": {
    "local_math": { "path": "../local_math" }
  }
}
```

Git dependencies may be pinned to a branch, tag, or commit:

```json
{
  "dependencies": {
    "text_utils": {
      "git": "https://github.com/example/text-utils.git",
      "rev": "v1.0.0"
    }
  }
}
```

Registry dependencies declare a semantic-version requirement:

```json
{
  "dependencies": {
    "text_utils": { "registry": "^1.2.0" }
  }
}
```

Set `YUBAPKG_REGISTRY_URL` to the trusted HTTPS registry endpoint before adding
or resolving a registry dependency. Supported requirements include exact
versions, caret and tilde ranges, inequalities, and `x`/`*` wildcards.
Whitespace or commas combine constraints with AND. New resolution selects the
highest compatible, non-yanked release for YubaLANG 1.3. See the
[registry protocol reference](registry.md) for metadata format, HTTPS policy,
limits, and cache behavior.

The dependency key must match the package's `name`. YubaPKG resolves an
unpinned Git dependency to a commit ID and stores that immutable revision in
`yuba.lock.json`. Normal installs reuse the locked revision; `yubapkg package
update` resolves newer versions for all direct Git/registry dependencies, or
for the selected direct dependency and its newly resolved transitive graph.
Registry installs lock the exact semantic
version, registry origin, artifact URL, SHA-256 digest, package-tree digest,
and nested dependency graph. Git checkouts and registry packages are stored
under `.yuba/packages/<name>`.

Path dependencies follow the current contents of their directory and are not
copied into the package cache.

## Lockfile

Check `yuba.lock.json` into version control along with `yuba.json`. Format 2
records path and Git dependency graphs. Format 3 adds exact registry releases,
artifact and tree hashes, and the complete nested graph. Each dependency's
own lockfile records the graph relative to its manifest. `yubapkg package
check` validates the graph and cached registry content without contacting the
registry or Git remotes.

Existing format-1 and format-2 lockfiles are upgraded by
`yubapkg package install`, preserving previously locked Git revisions when
sources are unchanged. Use `yubapkg package install --offline` to use only
existing locks and local caches; use `--frozen` in CI to verify without
resolution or writes. YubaLANG 1.3 imports format-3 registry packages offline,
but registry installation and updates are performed by YubaPKG.

YubaPKG does not currently implement publishing, authentication, package
search, private registries, or package provenance. No public registry is
operated by this project.
