# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Pure-Python dependency installer, modelled on the Android `PipController`:
# requirements are resolved against PyPI, only pure-Python wheels
# (`*-none-any.whl`) are accepted, packages are extracted into
# `plugins/libs/<name>-<version>` and shared by plugins through a registry.
# Binary wheels are refused, because a package built for Android or desktop
# cannot be loaded by the iOS CPython.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import hashlib
import importlib
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zipfile


PYTHON_VERSION = platform.python_version()
PYTHON_VERSION_SHORT = ".".join(PYTHON_VERSION.split(".")[:2])

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_WHEEL_BYTES = 250 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 50000
MAX_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024
MAX_SINGLE_FILE = 250 * 1024 * 1024

_REGISTRY_FILE_NAME = "registry.json"
_NORMALIZE_RE = re.compile(r"[-_.]+")
_REQ_NAME_RE = re.compile(r"^([a-zA-Z0-9_.-]+)(.*)")
_REQ_SPEC_RE = re.compile(r"^(===|==|>=|<=|>|<|~=|!=)\s*(.*)")
_REQ_EXTRA_RE = re.compile(r"\[.*?]")
_VERSION_SPLIT_RE = re.compile(r"([0-9]+)|([a-zA-Z]+)")
_WILDCARD_RE = re.compile(r"(?i)(?:^|[.\-_])\*$")
_MARKER_TOKEN_RE = re.compile(
    r"""("[^"]*"|'[^']*'|===|==|!=|>=|<=|~=|>|<|\(|\)|\b(?:and|or|in|not)\b|[A-Za-z_][A-Za-z0-9_]*|\S+)"""
)

_VERSION_WEIGHTS = {
    "post": 110,
    "": 100,
    "rc": 80,
    "c": 80,
    "beta": 70,
    "b": 70,
    "alpha": 60,
    "a": 60,
    "dev": 50,
}

_libs_dir = None
_registry_file = None
_registry = {}
_lock = threading.RLock()


# ---------------------------------------------------------------------------
# Versions


def _parse_version(version):
    normalized = str(version).strip().lower()
    if normalized.startswith("v"):
        normalized = normalized[1:]
    without_local = normalized.split("+", 1)[0]
    split = without_local.split("!", 1)
    if len(split) == 2 and split[0].isdigit():
        epoch = int(split[0])
        public = split[1]
    else:
        epoch = 0
        public = split[0]
    parts = [match.group(0) for match in _VERSION_SPLIT_RE.finditer(public)]
    return epoch, public, parts


def _compare_versions(left, right):
    left_epoch, _, left_parts = _parse_version(left)
    right_epoch, _, right_parts = _parse_version(right)
    if left_epoch != right_epoch:
        return -1 if left_epoch < right_epoch else 1

    length = max(len(left_parts), len(right_parts))
    for index in range(length):
        a = left_parts[index] if index < len(left_parts) else None
        b = right_parts[index] if index < len(right_parts) else None

        if a is None and b is not None and b.isdigit():
            a = "0"
        if b is None and a is not None and a.isdigit():
            b = "0"
        a = a or ""
        b = b or ""
        if a == b:
            continue

        a_number = int(a) if a.isdigit() else None
        b_number = int(b) if b.isdigit() else None
        if a_number is not None and b_number is not None:
            if a_number != b_number:
                return -1 if a_number < b_number else 1
        elif a_number is not None:
            return 1
        elif b_number is not None:
            return -1
        else:
            a_weight = _VERSION_WEIGHTS.get(a, 0)
            b_weight = _VERSION_WEIGHTS.get(b, 0)
            if a_weight != b_weight:
                return -1 if a_weight < b_weight else 1
            if a != b:
                return -1 if a < b else 1
    return 0


def _sort_versions(versions):
    import functools

    return sorted(versions, key=functools.cmp_to_key(_compare_versions), reverse=True)


def _is_pre_release(version):
    _, _, parts = _parse_version(version)
    return any(part in ("dev", "alpha", "a", "beta", "b", "rc", "c") for part in parts)


def _version_satisfies(version, specs):
    if not specs:
        return True
    for operator, spec in specs:
        comparison = _compare_versions(version, spec)
        if operator == "===":
            satisfied = version == spec
        elif operator == "==":
            satisfied = _matches_wildcard(version, spec) if _WILDCARD_RE.search(spec.strip()) else comparison == 0
        elif operator == ">=":
            satisfied = comparison >= 0
        elif operator == "<=":
            satisfied = comparison <= 0
        elif operator == ">":
            satisfied = comparison > 0
        elif operator == "<":
            satisfied = comparison < 0
        elif operator == "~=":
            satisfied = _compatible_spec(version, spec)
        elif operator == "!=":
            satisfied = (not _matches_wildcard(version, spec)) if _WILDCARD_RE.search(spec.strip()) else comparison != 0
        else:
            satisfied = True
        if not satisfied:
            return False
    return True


def _compatible_spec(version, spec):
    comparison = _compare_versions(version, spec)
    if comparison < 0:
        return False
    parts = str(spec).split(".")
    if len(parts) < 2:
        return True
    parts = parts[:-1]
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].isdigit():
            parts[index] = str(int(parts[index]) + 1)
            return _compare_versions(version, ".".join(parts)) < 0
    return True


def _matches_wildcard(version, spec):
    prefix = str(spec).strip().split("+", 1)[0]
    for suffix in (".*", "-*", "_*"):
        if prefix.endswith(suffix):
            prefix = prefix[:-len(suffix)]
            break
    prefix = prefix.rstrip(".-_")
    prefix_parts = [part for part in re.split(r"[.\-_]", _parse_version(prefix)[1]) if part.isdigit()]
    if not prefix_parts:
        return True
    version_parts = [part for part in re.split(r"[.\-_]", _parse_version(version)[1]) if part.isdigit()]
    if len(version_parts) < len(prefix_parts):
        return False
    return version_parts[:len(prefix_parts)] == prefix_parts


def _filter_pre_releases(versions, specs):
    if not versions:
        return versions
    if any(_is_pre_release(spec) for _, spec in specs):
        return versions
    stable = [version for version in versions if not _is_pre_release(version)]
    return stable or versions


# ---------------------------------------------------------------------------
# Requirements


def _normalize_name(name):
    return _NORMALIZE_RE.sub("-", str(name).strip().lower())


def _parse_specs(text):
    specs = []
    for part in str(text).split(","):
        part = part.strip()
        match = _REQ_SPEC_RE.match(part)
        if match:
            specs.append((match.group(1), match.group(2).strip()))
    return specs


def _parse_requirement(requirement):
    clean = str(requirement).split(";", 1)[0].strip()
    clean = _REQ_EXTRA_RE.sub("", clean).replace("(", "").replace(")", "").strip()
    match = _REQ_NAME_RE.match(clean)
    if match is None:
        return clean, []
    return match.group(1), _parse_specs(match.group(2))


# ---------------------------------------------------------------------------
# Markers


def _marker_value(name):
    if name == "sys_platform":
        return sys.platform
    if name == "platform_system":
        return platform.system()
    if name == "os_name":
        return os.name
    if name == "python_version":
        return PYTHON_VERSION_SHORT
    if name == "python_full_version":
        return PYTHON_VERSION
    if name == "implementation_name":
        return getattr(sys.implementation, "name", "")
    if name == "platform_python_implementation":
        return platform.python_implementation()
    if name == "extra":
        return ""
    return None


def _marker_compatible(marker):
    if not marker or not str(marker).strip():
        return True
    tokens = _MARKER_TOKEN_RE.findall(str(marker))
    if not tokens:
        return True
    position = [0]

    def peek(offset=0):
        index = position[0] + offset
        return tokens[index] if index < len(tokens) else None

    def advance():
        token = peek()
        if token is not None:
            position[0] += 1
        return token

    def match(token):
        if peek() == token:
            position[0] += 1
            return True
        return False

    def parse_or():
        value = parse_and()
        while (peek() or "").lower() == "or":
            position[0] += 1
            value = value or parse_and()
        return value

    def parse_and():
        value = parse_factor()
        while (peek() or "").lower() == "and":
            position[0] += 1
            value = value and parse_factor()
        return value

    def parse_factor():
        if match("("):
            value = parse_or()
            match(")")
            return value
        return parse_comparison()

    def parse_comparison():
        left = advance()
        if left is None:
            return True
        lower = (peek() or "").lower()
        if lower == "not" and (peek(1) or "").lower() == "in":
            position[0] += 2
            operator = "not in"
        elif lower in ("===", "==", "!=", ">=", "<=", ">", "<", "~=", "in"):
            position[0] += 1
            operator = lower
        else:
            return True

        right = advance()
        if right is None:
            return True

        left_variable = _marker_variable(left)
        right_variable = _marker_variable(right)
        left_value = _marker_value(left_variable) if left_variable else _unquote(left)
        right_value = _marker_value(right_variable) if right_variable else _unquote(right)

        if left_variable and _marker_value(left_variable) is None:
            return True
        if right_variable and _marker_value(right_variable) is None:
            return True

        left_is_version = left_variable in ("python_version", "python_full_version")
        right_is_version = right_variable in ("python_version", "python_full_version")
        if left_is_version and not right_is_version:
            return _version_satisfies(left_value, [(operator, right_value)])
        if right_is_version and not left_is_version:
            return _version_satisfies(right_value, [(_invert_operator(operator), left_value)])

        if operator in ("==", "==="):
            return left_value.lower() == right_value.lower()
        if operator == "!=":
            return left_value.lower() != right_value.lower()
        if operator == "in":
            return left_value.lower() in right_value.lower()
        if operator == "not in":
            return left_value.lower() not in right_value.lower()
        return True

    try:
        return bool(parse_or())
    except Exception:
        return True


def _marker_variable(token):
    if token is None:
        return None
    if token.startswith("'") or token.startswith('"'):
        return None
    value = token.lower()
    return value if re.fullmatch(r"[a-z_][a-z0-9_]*", value) else None


def _unquote(value):
    if value is None:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _invert_operator(operator):
    return {">": "<", ">=": "<=", "<": ">", "<=": ">="}.get(operator, operator)


# ---------------------------------------------------------------------------
# PyPI / wheels


def _http_get(url, limit=MAX_JSON_BYTES, timeout=30, retries=3):
    last_error = None
    for attempt in range(retries):
        try:
            import extera_ios

            result = extera_ios.http_request(url, "GET", {"Accept": "application/json"}, None, timeout)
            if isinstance(result, dict) and result.get("status") == 200 and isinstance(result.get("body"), str):
                return result["body"].encode("utf-8")
        except Exception:
            pass

        try:
            request = urllib.request.Request(url, headers={"User-Agent": "ExteraPlugins-iOS/1.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read(limit + 1)
                if len(data) > limit:
                    raise ValueError("response is too large")
                return data
        except Exception as error:
            last_error = error
            time.sleep(1.0 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError("request failed")


def _download(url, destination, limit=MAX_WHEEL_BYTES, timeout=120):
    try:
        import extera_ios

        result = extera_ios.http_download(url, destination, limit)
        if isinstance(result, dict) and result.get("ok"):
            return
    except Exception:
        pass

    request = urllib.request.Request(url, headers={"User-Agent": "ExteraPlugins-iOS/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        total = 0
        with open(destination, "wb") as handle:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ValueError("wheel is too large")
                handle.write(chunk)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _python_tag_compatible(tag):
    major, minor = sys.version_info[:2]
    tag = str(tag).lower()
    if tag == "py%d" % major:
        return True
    if tag == "cp%d%d" % (major, minor):
        return True
    match = re.fullmatch(r"py%d(\d+)" % major, tag)
    return bool(match and int(match.group(1)) <= minor)


def _is_pure_python_wheel(filename):
    if not filename.endswith(".whl"):
        return False
    parts = filename[:-4].split("-")
    if len(parts) < 5:
        return False
    python_tag, abi_tag, platform_tag = parts[-3], parts[-2], parts[-1]
    if abi_tag != "none" or platform_tag != "any":
        return False
    return any(_python_tag_compatible(tag) for tag in python_tag.split("."))


def _requires_python_ok(value):
    if not value:
        return True
    return _version_satisfies(PYTHON_VERSION, _parse_specs(value))


def _select_wheel(data, specs):
    releases = data.get("releases") or {}
    allow_yanked = any(operator in ("==", "===") for operator, _ in specs)
    versions = [version for version in releases.keys() if _version_satisfies(version, specs)]
    versions = _filter_pre_releases(versions, specs)
    for version in _sort_versions(versions):
        for artifact in releases.get(version) or []:
            if artifact.get("packagetype") != "bdist_wheel":
                continue
            if artifact.get("yanked") and not allow_yanked:
                continue
            filename = artifact.get("filename") or ""
            if not _is_pure_python_wheel(filename):
                continue
            if not _requires_python_ok(artifact.get("requires_python")):
                continue
            digest = (artifact.get("digests") or {}).get("sha256")
            url = artifact.get("url")
            if not url:
                continue
            return version, url, digest
    return None


def _extract_wheel(path, destination):
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_ENTRIES:
            raise ValueError("wheel has too many entries")
        total = 0
        root = os.path.abspath(destination)
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise ValueError("wheel contains an unsafe path: %s" % info.filename)
            target = os.path.abspath(os.path.join(root, name))
            if os.path.commonpath([root, target]) != root:
                raise ValueError("wheel escapes the target directory")
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            if info.file_size > MAX_SINGLE_FILE:
                raise ValueError("wheel contains a file that is too large")
            total += info.file_size
            if total > MAX_TOTAL_UNCOMPRESSED:
                raise ValueError("wheel expands beyond the size limit")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as output:
                shutil.copyfileobj(source, output)


def _top_level_modules(directory):
    names = set()
    try:
        entries = os.listdir(directory)
    except OSError:
        return names
    for name in entries:
        path = os.path.join(directory, name)
        if os.path.isdir(path):
            if name == "__pycache__" or name.endswith(".dist-info") or name.endswith(".data"):
                continue
            names.add(name)
        elif name.endswith(".py") or name.endswith(".pyc") or name.endswith(".so"):
            names.add(name.split(".")[0])
    return names


def _sdk_module_names():
    return _top_level_modules(os.path.dirname(os.path.abspath(__file__)))


def _find_metadata(directory):
    for root, directories, _ in os.walk(directory):
        for name in directories:
            if name.endswith(".dist-info"):
                path = os.path.join(root, name, "METADATA")
                if os.path.isfile(path):
                    return path
    return None


def _metadata_requirements(path):
    requirements = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if len(line) > MAX_METADATA_BYTES:
                    break
                if not line.startswith("Requires-Dist:"):
                    continue
                value = line[len("Requires-Dist:"):].strip()
                if ";" in value:
                    requirement, marker = value.split(";", 1)
                    if not _marker_compatible(marker):
                        continue
                    value = requirement.strip()
                if value:
                    requirements.append(value)
    except Exception:
        pass
    return requirements


# ---------------------------------------------------------------------------
# Registry


def _load_registry():
    global _registry
    if not _registry_file or not os.path.isfile(_registry_file):
        _registry = {}
        return
    try:
        with open(_registry_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        registry = {}
        for package, versions in (data or {}).items():
            normalized = _normalize_name(package)
            registry[normalized] = {}
            for version, plugins in (versions or {}).items():
                registry[normalized][version] = set(plugins or [])
        _registry = registry
    except Exception:
        _registry = {}


def _save_registry():
    if not _registry_file:
        return
    os.makedirs(os.path.dirname(_registry_file), exist_ok=True)
    temporary = _registry_file + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(
            {package: {version: sorted(plugins) for version, plugins in versions.items()}
             for package, versions in _registry.items()},
            handle,
            indent=2,
        )
    os.replace(temporary, _registry_file)


def _snapshot():
    return {package: {version: set(plugins) for version, plugins in versions.items()}
            for package, versions in _registry.items()}


def _restore(snapshot):
    global _registry
    _registry = snapshot


def _lib_path(package, version):
    if "/" in version or "\\" in version or ".." in version:
        raise ValueError("invalid version: %s" % version)
    return os.path.join(_libs_dir, "%s-%s" % (package, version))


def _delete_package(package, version):
    path = _lib_path(package, version)
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def _active_paths():
    paths = set()
    for package, versions in _registry.items():
        for version, plugins in versions.items():
            if plugins:
                paths.add(_lib_path(package, version))
    return paths


def refresh_sys_path():
    if not _libs_dir:
        return
    active = _active_paths()
    libs_root = os.path.abspath(_libs_dir)
    for path in list(sys.path):
        absolute = os.path.abspath(path) if path else ""
        if absolute.startswith(libs_root + os.sep) and absolute not in active:
            try:
                sys.path.remove(path)
            except ValueError:
                pass
    for path in sorted(active, reverse=True):
        if path not in sys.path:
            sys.path.insert(0, path)
    importlib.invalidate_caches()


def initialize(plugins_path):
    global _libs_dir, _registry_file
    _libs_dir = os.path.join(plugins_path, "libs")
    _registry_file = os.path.join(_libs_dir, _REGISTRY_FILE_NAME)
    os.makedirs(_libs_dir, exist_ok=True)
    with _lock:
        _load_registry()
        refresh_sys_path()
    return _libs_dir


# ---------------------------------------------------------------------------
# Install / uninstall


def _remove_orphans():
    if not _libs_dir:
        return
    expected = set(os.path.abspath(path) for path in _active_paths())
    try:
        names = os.listdir(_libs_dir)
    except OSError:
        return
    for name in names:
        path = os.path.abspath(os.path.join(_libs_dir, name))
        if os.path.isdir(path) and path not in expected:
            shutil.rmtree(path, ignore_errors=True)


def _update_registry_for_plugin(plugin_id, installed):
    for package, versions in list(_registry.items()):
        for version, plugins in list(versions.items()):
            if plugin_id in plugins and installed.get(package) != version:
                plugins.discard(plugin_id)
                if not plugins:
                    versions.pop(version, None)
                    _delete_package(package, version)
        if not versions:
            _registry.pop(package, None)


def _find_installed_version(package, specs):
    versions = _registry.get(package) or {}
    candidates = [version for version, plugins in versions.items()
                  if plugins and _version_satisfies(version, specs)]
    candidates = _filter_pre_releases(candidates, specs)
    return _sort_versions(candidates)[0] if candidates else None


def _find_version_on_disk(package, specs):
    if not _libs_dir:
        return None
    prefix = package + "-"
    candidates = []
    try:
        names = os.listdir(_libs_dir)
    except OSError:
        return None
    for name in names:
        if not name.startswith(prefix):
            continue
        version = name[len(prefix):]
        if os.path.isdir(os.path.join(_libs_dir, name)) and _version_satisfies(version, specs):
            candidates.append(version)
    candidates = _filter_pre_releases(candidates, specs)
    return _sort_versions(candidates)[0] if candidates else None


def _install_package(package, specs, progress=None, cancelled=None):
    if progress:
        progress("Resolving %s..." % package)
    data = json.loads(_http_get("https://pypi.org/pypi/%s/json" % urllib.parse.quote(package)).decode("utf-8"))
    candidate = _select_wheel(data, specs)
    if candidate is None:
        requires = (data.get("info") or {}).get("requires_python")
        if requires and not _requires_python_ok(requires):
            raise RuntimeError("Package %s requires Python %s, but this runtime is %s"
                               % (package, requires, PYTHON_VERSION))
        raise RuntimeError("No pure-Python wheel found for %s. Binary packages are not supported." % package)

    version, url, expected_sha = candidate
    if cancelled and cancelled():
        raise RuntimeError("installation cancelled")
    if progress:
        progress("Downloading %s %s..." % (package, version))

    os.makedirs(_libs_dir, exist_ok=True)
    temporary = tempfile.mkdtemp(prefix=".install-", dir=_libs_dir)
    try:
        wheel = os.path.join(temporary, "package.whl")
        _download(url, wheel)
        if expected_sha and _sha256(wheel).lower() != expected_sha.lower():
            raise RuntimeError("checksum mismatch for %s" % package)

        if progress:
            progress("Extracting %s %s..." % (package, version))
        extracted = os.path.join(temporary, "extracted")
        os.makedirs(extracted, exist_ok=True)
        _extract_wheel(wheel, extracted)

        collisions = _top_level_modules(extracted) & _sdk_module_names()
        if collisions:
            raise RuntimeError(
                "Dependency %s %s provides %s, which would replace the plugins SDK module of the same name."
                % (package, version, ", ".join(sorted(collisions)))
            )

        target = _lib_path(package, version)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        os.replace(extracted, target)
        return version
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _active_version(package):
    versions = _registry.get(package) or {}
    for version, plugins in versions.items():
        if plugins:
            return version
    return None


def _resolve(package, specs, installed, plugin_id, progress=None, cancelled=None):
    if cancelled and cancelled():
        raise RuntimeError("installation cancelled")

    if package in installed:
        if _version_satisfies(installed[package], specs):
            return installed[package]

    active = _active_version(package)
    if active is not None and not _version_satisfies(active, specs):
        display = ", ".join("%s%s" % item for item in specs) if specs else "(latest)"
        raise RuntimeError(
            "Dependency conflict for '%s': active version %s does not satisfy '%s'."
            % (package, active, display)
        )

    if active is not None:
        version = active
    else:
        version = _find_installed_version(package, specs)
        if version is None:
            version = _find_version_on_disk(package, specs)
        if version is None:
            version = _install_package(package, specs, progress=progress, cancelled=cancelled)

    _registry.setdefault(package, {}).setdefault(version, set()).add(plugin_id)
    installed[package] = version

    metadata = _find_metadata(_lib_path(package, version))
    if metadata:
        for requirement in _metadata_requirements(metadata):
            dependency, dependency_specs = _parse_requirement(requirement)
            dependency = _normalize_name(dependency)
            if dependency and dependency != package:
                _resolve(dependency, dependency_specs, installed, plugin_id, progress, cancelled)
    return version


def install_dependencies(requirements, plugin_id, progress=None, cancelled=None):
    with _lock:
        snapshot = _snapshot()
        installed = {}
        try:
            for requirement in requirements or []:
                if not str(requirement).strip():
                    continue
                if cancelled and cancelled():
                    raise RuntimeError("installation cancelled")
                package, specs = _parse_requirement(requirement)
                package = _normalize_name(package)
                if package:
                    _resolve(package, specs, installed, plugin_id, progress, cancelled)
            _update_registry_for_plugin(plugin_id, installed)
            _save_registry()
            _remove_orphans()
            refresh_sys_path()
            return [_lib_path(package, version) for package, version in installed.items()]
        except Exception:
            _restore(snapshot)
            _save_registry()
            _remove_orphans()
            refresh_sys_path()
            raise


def uninstall_dependencies(plugin_id):
    with _lock:
        changed = False
        for package, versions in list(_registry.items()):
            for version, plugins in list(versions.items()):
                if plugin_id in plugins:
                    plugins.discard(plugin_id)
                    changed = True
                    if not plugins:
                        versions.pop(version, None)
                        _delete_package(package, version)
            if not versions:
                _registry.pop(package, None)
        if changed:
            _save_registry()
        _remove_orphans()
        refresh_sys_path()


def cleanup():
    with _lock:
        for package, versions in list(_registry.items()):
            for version, plugins in list(versions.items()):
                if not plugins:
                    versions.pop(version, None)
                    _delete_package(package, version)
            if not versions:
                _registry.pop(package, None)
        _save_registry()
        _remove_orphans()
        refresh_sys_path()


def active_library_paths():
    return sorted(_active_paths())
