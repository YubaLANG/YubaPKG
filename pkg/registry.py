"""Static HTTPS registry protocol and verified package archive handling."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

from .core import (
    MANIFEST_NAME,
    PackageError,
    _WINDOWS_RESERVED_NAMES,
    read_manifest,
    resolve_entry,
)
from .semver import Version


REGISTRY_ENV = "YUBAPKG_REGISTRY_URL"
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_FILES = 20_000
HTTP_TIMEOUT = 15
SUPPORTED_YUBALANG = frozenset({"1.2", "1.3"})


def registry_url(value: str | None = None) -> str:
    endpoint = value or os.environ.get(REGISTRY_ENV)
    if not endpoint:
        raise PackageError(
            f"Registry dependencies require {REGISTRY_ENV} to name the trusted "
            "registry HTTPS base URL."
        )
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        parsed.port
    except ValueError as error:
        raise PackageError(f"Registry URL is invalid: {error}") from error
    if (
        parsed.scheme not in ("https", "http")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise PackageError(
            "Registry URL must be an HTTP(S) base URL without credentials, "
            "query, or fragment."
        )
    if parsed.scheme != "https" and parsed.hostname not in (
        "localhost",
        "127.0.0.1",
        "::1",
    ):
        raise PackageError("Registry connections must use HTTPS.")
    return endpoint.rstrip("/")


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme, (parsed.hostname or "").casefold(), parsed.port


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str, int | None]) -> None:
        super().__init__()
        self.origin = origin

    def redirect_request(
        self,
        request: urllib.request.Request,
        response: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        target = urllib.parse.urljoin(request.full_url, new_url)
        try:
            parsed = urllib.parse.urlsplit(target)
            target_origin = _origin(target)
        except ValueError as error:
            raise PackageError(f"Registry redirect URL is invalid: {error}") from error
        if (
            target_origin != self.origin
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (
                parsed.scheme != "https"
                and parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            )
        ):
            raise PackageError(
                "Registry redirects must remain on the configured HTTPS origin."
            )
        return super().redirect_request(
            request, response, code, message, headers, target
        )


def _read_response(url: str, headers: dict[str, str], limit: int) -> tuple[bytes, Any]:
    request = urllib.request.Request(url, headers=headers)
    try:
        opener = urllib.request.build_opener(_SafeRedirectHandler(_origin(url)))
        with opener.open(request, timeout=HTTP_TIMEOUT) as response:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise PackageError(
                    f"Registry response exceeded the {limit}-byte limit."
                )
            return data, response.headers
    except PackageError:
        raise
    except urllib.error.HTTPError as error:
        if error.code == 304:
            response_headers = error.headers
            error.close()
            return b"", response_headers
        detail = error.reason or str(error)
        raise PackageError(f"Registry request failed ({error.code}): {detail}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise PackageError(f"Registry request failed: {error}") from error


def _metadata_path(root: Path, name: str) -> Path:
    return root / ".yuba" / "registry" / f"{name}.json"


def fetch_metadata(
    root: Path,
    name: str,
    endpoint: str,
    offline: bool = False,
) -> dict[str, Any]:
    path = _metadata_path(root, name)
    headers: dict[str, str] = {"Accept": "application/json"}
    cache_headers_path = path.with_suffix(".headers.json")
    try:
        cached = path.read_bytes()
    except FileNotFoundError:
        cached = b""
    except OSError as error:
        raise PackageError(f"Registry metadata cache is unreadable for '{name}': {error}") from error
    try:
        cached_headers = json.loads(cache_headers_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        cached_headers = {}
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PackageError(f"Registry metadata cache is unreadable for '{name}': {error}") from error
    if not isinstance(cached_headers, dict):
        raise PackageError(f"Registry metadata cache headers are invalid for '{name}'.")

    if offline:
        if not cached:
            raise PackageError(
                f"Package '{name}' metadata is not cached for offline resolution."
            )
        return _parse_metadata(cached, name)

    for key, header in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
        value = cached_headers.get(key)
        if value is not None and (
            not isinstance(value, str)
            or len(value) > 8192
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise PackageError(f"Registry metadata cache has an invalid {key} value.")
        if value is not None:
            headers[header] = value
    metadata_url = f"{endpoint}/v1/packages/{urllib.parse.quote(name, safe='')}.json"
    try:
        data, response_headers = _read_response(
            metadata_url, headers, MAX_METADATA_BYTES
        )
    except PackageError as error:
        if cached:
            raise PackageError(
                f"Cannot refresh metadata for '{name}' and cached metadata is "
                f"available; retry with --offline to use it. {error}"
            ) from error
        raise
    if not data:
        if not cached:
            raise PackageError(
                f"Registry returned not-modified for '{name}' without a cached copy."
            )
        return _parse_metadata(cached, name)

    parsed = _parse_metadata(data, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, data)
        _atomic_write(
            cache_headers_path,
            json.dumps(
                {
                    "etag": response_headers.get("ETag"),
                    "last_modified": response_headers.get("Last-Modified"),
                },
                sort_keys=True,
            ).encode("utf-8"),
        )
    except OSError as error:
        raise PackageError(f"Cannot cache registry metadata for '{name}': {error}") from error
    return parsed


def _parse_metadata(data: bytes, expected_name: str) -> dict[str, Any]:
    try:
        metadata = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PackageError(f"Registry metadata for '{expected_name}' is invalid: {error}") from error
    if (
        not isinstance(metadata, dict)
        or isinstance(metadata.get("schema_version"), bool)
        or metadata.get("schema_version") != 1
        or metadata.get("name") != expected_name
        or not isinstance(metadata.get("versions"), dict)
    ):
        raise PackageError(
            f"Registry metadata for '{expected_name}' has an unsupported schema."
        )
    for version, release in metadata["versions"].items():
        try:
            Version.parse(version)
        except ValueError as error:
            raise PackageError(
                f"Registry release '{expected_name}@{version}' has an invalid version: {error}"
            ) from error
        if not isinstance(release, dict):
            raise PackageError(f"Registry release '{expected_name}@{version}' is malformed.")
        if "yanked" in release and not isinstance(release["yanked"], bool):
            raise PackageError(
                f"Registry release '{expected_name}@{version}' has invalid yanked metadata."
            )
        compatible = release.get("yubalang")
        if (
            not isinstance(compatible, list)
            or not compatible
            or any(not isinstance(item, str) for item in compatible)
            or not set(compatible).issubset(SUPPORTED_YUBALANG)
        ):
            raise PackageError(
                f"Registry release '{expected_name}@{version}' has invalid "
                "YubaLANG compatibility metadata."
            )
        artifact = release.get("artifact")
        digest = release.get("sha256")
        if not isinstance(artifact, str) or not artifact:
            raise PackageError(f"Registry release '{expected_name}@{version}' has no artifact.")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise PackageError(f"Registry release '{expected_name}@{version}' has invalid SHA-256.")
    return metadata


def release_for(
    metadata: dict[str, Any],
    version: str,
    runtime_version: str,
) -> dict[str, Any]:
    release = metadata["versions"].get(version)
    if release is None:
        raise PackageError(f"Registry has no release {metadata['name']}@{version}.")
    if runtime_version not in release["yubalang"]:
        raise PackageError(
            f"Package '{metadata['name']}@{version}' does not support "
            f"YubaLANG {runtime_version}."
        )
    return release


def artifact_url(endpoint: str, artifact: str) -> str:
    if not isinstance(artifact, str) or not artifact:
        raise PackageError("Registry artifact URL is invalid.")
    try:
        absolute = urllib.parse.urljoin(endpoint + "/", artifact)
        parsed = urllib.parse.urlsplit(absolute)
        parsed.port
    except ValueError as error:
        raise PackageError(f"Registry artifact URL is invalid: {error}") from error
    if (
        parsed.scheme not in ("https", "http")
        or not parsed.hostname
        or _origin(absolute) != _origin(endpoint)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise PackageError(
            "Registry artifact URL must remain on the configured registry origin "
            "without credentials, query, or fragment."
        )
    if parsed.scheme != "https" and parsed.hostname not in (
        "localhost",
        "127.0.0.1",
        "::1",
    ):
        raise PackageError("Registry artifact downloads must use HTTPS.")
    return absolute


def _atomic_write(path: Path, contents: bytes) -> None:
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as output:
            temporary_path = Path(output.name)
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def ensure_artifact(
    root: Path,
    resolved: dict[str, Any],
    offline: bool = False,
) -> Path:
    digest = resolved.get("sha256")
    endpoint = resolved.get("registry")
    artifact = resolved.get("artifact")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        or not isinstance(endpoint, str)
        or not isinstance(artifact, str)
    ):
        raise PackageError("Registry lock entry has invalid artifact identity.")
    endpoint = registry_url(endpoint)
    archive_path = root / ".yuba" / "artifacts" / f"{digest}.tar.gz"
    if archive_path.is_file():
        if _sha256_file(archive_path) != digest:
            raise PackageError(
                f"Cached registry artifact has an invalid SHA-256: {archive_path}"
            )
        return archive_path
    if offline:
        raise PackageError(
            f"Registry artifact {digest} is not cached for offline installation."
        )
    url = artifact_url(endpoint, artifact)
    data, _ = _read_response(url, {}, MAX_ARTIFACT_BYTES)
    if hashlib.sha256(data).hexdigest() != digest:
        raise PackageError(f"Registry artifact SHA-256 mismatch for {url}.")
    try:
        _atomic_write(archive_path, data)
    except OSError as error:
        raise PackageError(f"Cannot cache registry artifact '{url}': {error}") from error
    return archive_path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise PackageError(f"Cannot read cached artifact '{path}': {error}") from error
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = []
    for path in root.rglob("*"):
        relative_path = path.relative_to(root)
        if ".yuba" in relative_path.parts or ".git" in relative_path.parts:
            continue
        if path.is_symlink():
            raise PackageError(f"Package contains an unsupported symbolic link: {path}")
        if path.is_file() and path.name != "yuba.lock.json":
            files.append(path)
        elif not path.is_dir() and not path.is_file():
            raise PackageError(f"Package contains an unsupported file type: {path}")
    files.sort(
        key=lambda path: path.relative_to(root).as_posix().encode("utf-8")
    )
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        try:
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as error:
            raise PackageError(f"Cannot read package file '{path}': {error}") from error
    return digest.hexdigest()


def install_archive(
    root: Path,
    name: str,
    version: str,
    resolved: dict[str, Any],
    offline: bool = False,
) -> Path:
    archive = ensure_artifact(root, resolved, offline)
    destination = root / ".yuba" / "packages" / name
    expected_tree = resolved.get("tree_sha256")
    if (
        isinstance(expected_tree, str)
        and destination.is_dir()
        and not destination.is_symlink()
    ):
        try:
            if tree_sha256(destination) == expected_tree:
                manifest = read_manifest(destination)
                if manifest["name"] == name and manifest["version"] == version:
                    return destination
        except PackageError:
            pass
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_context = tempfile.TemporaryDirectory(
            prefix=f".{name}.install.", dir=destination.parent
        )
    except OSError as error:
        raise PackageError(f"Cannot create package install directory '{destination}': {error}") from error
    with temporary_context as temporary:
        temporary_root = Path(temporary)
        _extract_archive(archive, temporary_root)
        manifest = read_manifest(temporary_root)
        if manifest["name"] != name or manifest["version"] != version:
            raise PackageError(
                f"Registry artifact identity mismatch: expected '{name}@{version}', "
                f"found '{manifest['name']}@{manifest['version']}'."
            )
        resolve_entry(temporary_root, manifest)
        if manifest["yubalang"] not in SUPPORTED_YUBALANG:
            raise PackageError(
                f"Package '{name}@{version}' requires unsupported YubaLANG "
                f"{manifest['yubalang']}."
            )
        actual_tree = tree_sha256(temporary_root)
        if expected_tree is not None and expected_tree != actual_tree:
            raise PackageError(
                f"Installed package '{name}@{version}' differs from its lockfile."
            )
        if destination.exists():
            backup = destination.with_name(f".{destination.name}.previous")
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(destination, backup)
            try:
                os.replace(temporary_root, destination)
            except OSError:
                os.replace(backup, destination)
                raise
            shutil.rmtree(backup)
        else:
            os.replace(temporary_root, destination)
    return destination


def verify_cached_installation(
    root: Path,
    name: str,
    resolved: dict[str, Any],
) -> Path:
    endpoint = resolved.get("registry")
    digest = resolved.get("sha256")
    artifact = resolved.get("artifact")
    version = resolved.get("version")
    if (
        not isinstance(endpoint, str)
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        or not isinstance(artifact, str)
        or not isinstance(version, str)
    ):
        raise PackageError(f"Registry lock entry for '{name}' has invalid identity.")
    registry_url(endpoint)
    artifact_url(endpoint, artifact)
    archive = root / ".yuba" / "artifacts" / f"{digest}.tar.gz"
    if not archive.is_file():
        raise PackageError(
            f"Registry artifact for '{name}' is not cached; run "
            "'yubapkg package install'."
        )
    if _sha256_file(archive) != digest:
        raise PackageError(
            f"Cached registry artifact for '{name}' failed SHA-256 verification."
        )
    package_root = root / ".yuba" / "packages" / name
    if not package_root.is_dir():
        raise PackageError(
            f"Registry package '{name}' is not installed; run "
            "'yubapkg package install'."
        )
    expected_tree = resolved.get("tree_sha256")
    if not isinstance(expected_tree, str) or tree_sha256(package_root) != expected_tree:
        raise PackageError(
            f"Installed registry package '{name}' was modified; run "
            "'yubapkg package install'."
        )
    manifest = read_manifest(package_root)
    if manifest["version"] != resolved.get("version"):
        raise PackageError(f"Installed registry package '{name}' has the wrong version.")
    resolve_entry(package_root, manifest)
    return package_root


def _extract_archive(archive: Path, destination: Path) -> None:
    seen: set[str] = set()
    total_size = 0
    try:
        with tarfile.open(archive, mode="r:gz") as source:
            members = source.getmembers()
            if len(members) > MAX_ARCHIVE_FILES:
                raise PackageError(
                    f"Registry artifact contains more than {MAX_ARCHIVE_FILES} entries."
                )
            for member in members:
                name = member.name
                path = PurePosixPath(name)
                try:
                    name.encode("utf-8")
                except UnicodeEncodeError as error:
                    raise PackageError(
                        f"Registry artifact contains an invalid path: {name!r}."
                    ) from error
                portable_name = str(path).casefold()
                if (
                    not name
                    or "\\" in name
                    or str(path) != name.rstrip("/")
                    or path.is_absolute()
                    or any(part in ("", ".", "..") for part in path.parts)
                    or any(
                        ":" in part
                        or part.rstrip(" .") != part
                        or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
                        or part.casefold() in (".yuba", ".git")
                        for part in path.parts
                    )
                    or portable_name in seen
                    or not (member.isfile() or member.isdir())
                ):
                    raise PackageError(
                        f"Registry artifact contains an unsafe archive entry: {name!r}."
                    )
                seen.add(portable_name)
                total_size += member.size
                if member.size < 0 or total_size > MAX_EXPANDED_BYTES:
                    raise PackageError(
                        f"Registry artifact expands beyond {MAX_EXPANDED_BYTES} bytes."
                    )
            for member in members:
                target = destination.joinpath(*PurePosixPath(member.name).parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = source.extractfile(member)
                if extracted is None:
                    raise PackageError(
                        f"Cannot read archive entry {member.name!r}."
                    )
                with extracted, target.open("xb") as output:
                    shutil.copyfileobj(extracted, output)
    except PackageError:
        raise
    except (OSError, tarfile.TarError, EOFError) as error:
        raise PackageError(f"Cannot extract registry artifact: {error}") from error
