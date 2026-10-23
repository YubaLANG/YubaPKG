# Project manifest and lockfile

YubaPKG reads `yuba.json` from the current directory or its parents. A
minimal project manifest is:

```json
{
  "name": "sample",
  "version": "0.1.0",
  "entry": "main.yl",
  "yubalang": "1.2",
  "dependencies": {}
}
```

The `name`, `version`, `entry`, and `yubalang` values are required strings.
Package names start with a letter and may contain letters, digits, underscores,
and hyphens. The current importer supports YubaLANG version `1.2`.

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

Check `yuba.lock.json` into version control along with `yuba.json`. The
lockfile records each direct dependency source and its resolved path or Git
commit. `yubapkg package check` compares the manifest, lockfile, and local
installations without contacting Git remotes.

The current release supports direct path and Git dependencies only. Registry
metadata, semantic-version ranges, transitive dependency solving, and package
publishing are future work.
