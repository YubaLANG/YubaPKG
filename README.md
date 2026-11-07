# YubaPKG

YubaPKG is the standalone package manager for YubaLANG projects. It is being
built as a separate tool so package resolution, registry access, and publishing
can evolve independently from the language runtime.

## Current status

The CLI supports project initialization and recursive path, Git, and static
registry dependencies. Registry ranges resolve to immutable releases with
SHA-256-verified artifacts; installs are recorded in lockfile format 3.
YubaPKG accepts YubaLANG 1.2 and 1.3 manifests, and YubaLANG 1.3 can import
the installed registry packages offline.

The registry client consumes the static protocol described in
[the registry reference](docs/registry.md). This repository does not operate a
public registry. Search uses the optional static search index; package
publishing, authentication, private registries, signatures, and publisher
provenance are not implemented.

## Run from a checkout

Requires Python 3.10 or later. Git is required for Git dependencies.

```powershell
python -m pip install -e .
yubapkg package init
yubapkg package add helpers --path ..\helpers
yubapkg package install
yubapkg package check
yubapkg package tree
yubapkg package cache list
```

For a registry dependency, configure the trusted HTTPS endpoint first:

```powershell
$env:YUBAPKG_REGISTRY_URL = "https://packages.example.org"
yubapkg package add helpers --registry "^1.2.0"
yubapkg package install --offline
yubapkg package install --frozen
yubapkg package search helpers
yubapkg package info helpers
yubapkg package outdated
```

`--offline` uses locked resolutions and cached artifacts only.
`--frozen` verifies the current lock and install without changing them.
Instead of the environment variable, use
`yubapkg package config registry https://packages.example.org` for
project-local configuration or add `--global` for user-level configuration.

The package can also be run without installing the console command:

```powershell
python -m pkg package --help
```

Use `yubapkg package init` to create a project, then run package commands from
the project directory or one of its subdirectories.

See [the manifest reference](docs/manifest.md) for project and lockfile
formats, and [the registry reference](docs/registry.md) for the static
metadata protocol, trust rules, cache behavior, and current limitations.

## License

YubaPKG is available under the custom [Yuba Non-Commercial Software
License](LICENSE). It permits copying, modification, and redistribution for
non-commercial purposes with attribution. Commercial use requires prior
written permission. This is a source-available license, not an OSI-approved
open-source license.
