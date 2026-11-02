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

The dependency key must match the package's `name`. YubaPKG resolves an
unpinned Git dependency to a commit ID and stores that immutable revision in
`yuba.lock.json`. Normal installs reuse the locked revision; `yubapkg package
update` resolves a newer revision. Git checkouts are stored in
`.yuba/packages/<name>`.

Path dependencies follow the current contents of their directory and are not
copied into the package cache.

## Lockfile

Check `yuba.lock.json` into version control along with `yuba.json`. Lockfile
format 2 records each dependency's source and resolved path or Git commit,
package identity, and complete nested dependency graph. Each dependency's own
lockfile records the graph relative to its manifest. `yubapkg package check`
compares manifests, nested lockfiles, package identities, and local
installations without contacting Git remotes.

Existing format-1 lockfiles are upgraded to format 2 by
`yubapkg package install`, preserving previously locked Git revisions when
sources are unchanged. Path and Git dependencies may be nested recursively;
registry metadata, semantic-version range solving, and package publishing are
future work.
