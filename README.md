# YubaPKG

YubaPKG is the standalone package manager for YubaLANG projects. It is being
built as a separate tool so package resolution, registry access, and publishing
can evolve independently from the language runtime.

## Current status

The first CLI release supports project initialization and direct path or Git
dependencies. Installs are recorded in `yuba.lock.json`; Git dependencies are
checked out at exact commits under `.yuba/packages`. The manifest and lockfile
formats are compatible with the current YubaLANG package importer.

The public registry, semantic-version ranges, transitive dependency solving,
and package publishing are not implemented yet.

## Run from a checkout

Requires Python 3.10 or later. Git is required for Git dependencies.

```powershell
python -m pip install -e .
yubapkg package init
yubapkg package add helpers --path ..\helpers
yubapkg package install
yubapkg package check
```

The module can also be run without installing the console command:

```powershell
python -m yubapkg package --help
```

Use `yubapkg package init` to create a project, then run package commands from
the project directory or one of its subdirectories.

See [the manifest reference](docs/manifest.md) for the project and lockfile
formats.

## License

YubaPKG is available under the custom [Yuba Non-Commercial Software
License](LICENSE). It permits copying, modification, and redistribution for
non-commercial purposes with attribution. Commercial use requires prior
written permission. This is a source-available license, not an OSI-approved
open-source license.
