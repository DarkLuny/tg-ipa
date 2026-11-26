# This is the iOS counterpart of the exteraGram plugins SDK.
#
# The generic file helpers keep their Android names and work on the app's
# sandbox directories.  `FilesController` keeps its registration API: a plugin
# claims a file extension and gets a click callback when the user opens a file
# with it.  On iOS the host routes document-open events through the same
# handler.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import itertools
import os
import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional

import extera_ios


def _dir(kind):
    value = extera_ios.host("paths.dir", kind=kind)
    return value if isinstance(value, str) else os.path.expanduser("~")


def get_plugins_dir():
    return _dir("plugins")


def get_cache_dir():
    return _dir("cache")


def get_files_dir():
    return _dir("files")


def get_images_dir():
    return _dir("images")


def get_videos_dir():
    return _dir("videos")


def get_audios_dir():
    return _dir("audios")


def get_documents_dir():
    return _dir("documents")


def read_file(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        return None


def read_file_bytes(file_path):
    try:
        with open(file_path, "rb") as handle:
            return handle.read()
    except Exception:
        return None


def write_file(file_path, content):
    ensure_dir_exists(os.path.dirname(file_path))
    with open(file_path, "w", encoding="utf-8") as handle:
        handle.write(content)


def write_file_bytes(file_path, content):
    ensure_dir_exists(os.path.dirname(file_path))
    with open(file_path, "wb") as handle:
        handle.write(content)


def delete_file(file_path):
    try:
        os.remove(file_path)
        return True
    except Exception:
        return False


def ensure_dir_exists(dir_path):
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)


def list_dir(
    path,
    recursive=False,
    include_files=True,
    include_dirs=False,
    extensions=None,
):
    """Lists a directory with the same arguments and order as Android's SDK.

    `extensions` entries are matched with `str.endswith`, like Android.
    """
    results = []
    if not os.path.isdir(path):
        return results
    if recursive:
        for root, dirs, files in os.walk(path):
            if include_dirs:
                for directory in dirs:
                    results.append(os.path.join(root, directory))
            if include_files:
                for name in files:
                    if not extensions or any(name.endswith(ext) for ext in extensions):
                        results.append(os.path.join(root, name))
    else:
        for item in os.listdir(path):
            full_path = os.path.join(path, item)
            is_dir = os.path.isdir(full_path)
            if (is_dir and include_dirs) or (not is_dir and include_files):
                if not is_dir and extensions and not any(item.endswith(ext) for ext in extensions):
                    continue
                results.append(full_path)
    return results


class staticproperty:
    def __init__(self, fget):
        self.fget = fget

    def __get__(self, obj, owner):
        return self.fget.__get__(obj, owner)()


class FilesController:
    DIRECT_FILE_ICONS = False
    SUPPORT_ICONS = True

    class Place(Enum):
        UNKNOWN = 1
        ChatActivity = 2
        FilteredSearchView = 3
        SharedMediaLayout = 4
        SearchDownloadsContainer = 5
        ChannelAdminLogActivity = 6

    @dataclass
    class FileInfo:
        ext: str
        on_click: Callable[["FilesController.OnClickArgs"], None] = field(
            compare=False, repr=False, default=None
        )
        whitelist_places: List["FilesController.Place"] = field(default_factory=list, kw_only=True)
        blacklist_places: List["FilesController.Place"] = field(default_factory=list, kw_only=True)
        get_icon: Optional[Callable[[], Any]] = field(default=None, compare=False, repr=False, kw_only=True)
        _icid: int = field(default=-1, init=False, repr=False, compare=False)

        def __post_init__(self):
            if self.whitelist_places and self.blacklist_places:
                raise ValueError("Cannot use whitelist_places with blacklist_places together")

    @dataclass
    class OnClickArgs:
        place: "FilesController.Place"
        file: Any = None
        file_name: str = ""
        message: Any = None
        activity: Any = None
        parent_fragment: Any = None

    class ExtensionAlreadyRegistered(Exception):
        def __init__(self, ext):
            super().__init__("The file extension '%s' is already in use." % ext)

    class ExtensionNotRegistered(Exception):
        def __init__(self, ext):
            super().__init__("The file extension '%s' is not registered." % ext)

    class SecretInvalid(Exception):
        def __init__(self, ext, secret):
            super().__init__("Provided secret '%s' for extension '%s' is invalid." % (secret, ext))

    _lock = None
    _config = {}
    _secrets = {}
    _owners = {}
    _icons = itertools.count(start=101)
    _current_plugin = ""

    @classmethod
    def register(cls, file_info):
        extension = (file_info.ext or "").lower().lstrip(".")
        if not extension:
            raise ValueError("FileInfo.ext must not be empty")
        if extension in cls._config:
            raise cls.ExtensionAlreadyRegistered(extension)
        if file_info.whitelist_places and file_info.blacklist_places:
            raise ValueError("Cannot use whitelist_places with blacklist_places together")
        secret = secrets.token_hex(16)
        cls._config[extension] = file_info
        cls._secrets[extension] = secret
        cls._owners[extension] = cls._current_plugin
        handle = extera_ios.retain(cls._make_click_wrapper(file_info))
        icon = None
        if file_info.get_icon is not None:
            try:
                icon = file_info.get_icon()
            except Exception:
                icon = None
        extera_ios.register_file_handler(
            cls._current_plugin, extension, "File", handle, icon
        )
        return secret

    @classmethod
    def _make_click_wrapper(cls, file_info):
        """Adapts the host's payload to the Android `OnClickArgs` object."""

        def on_click(payload):
            if isinstance(payload, cls.OnClickArgs):
                place = payload.place
                args = payload
            else:
                if not isinstance(payload, dict):
                    payload = {"place": payload}
                try:
                    place = cls.Place(int(payload.get("place", 0)))
                except (TypeError, ValueError):
                    place = cls.Place.UNKNOWN
                from extera_utils.classes import NativeFile

                file_value = payload.get("file")
                if isinstance(file_value, str):
                    file_value = NativeFile(file_value)
                args = cls.OnClickArgs(
                    place=place,
                    file=file_value,
                    file_name=payload.get("file_name") or "",
                    message=payload.get("message"),
                    activity=payload.get("activity"),
                    parent_fragment=payload.get("parent_fragment"),
                )
            if file_info.whitelist_places and place not in file_info.whitelist_places:
                return None
            if file_info.blacklist_places and place in file_info.blacklist_places:
                return None
            callback = file_info.on_click
            if callback is None:
                return None
            return callback(args)

        return on_click

    @classmethod
    def unregister(cls, ext, secret):
        extension = (ext or "").lower().lstrip(".")
        if extension not in cls._config:
            raise cls.ExtensionNotRegistered(extension)
        if cls._secrets.get(extension) != secret:
            raise cls.SecretInvalid(extension, secret)
        cls._config.pop(extension, None)
        cls._secrets.pop(extension, None)
        owner = cls._owners.pop(extension, cls._current_plugin)
        extera_ios.unregister_file_handler(owner, extension)

    @classmethod
    def get_file_type(cls, file_name):
        return os.path.splitext(file_name or "")[1].lower().lstrip(".")

    @classmethod
    def _stop(cls):
        for extension in list(cls._config.keys()):
            owner = cls._owners.get(extension, "")
            extera_ios.unregister_file_handler(owner, extension)
        cls._config.clear()
        cls._secrets.clear()
        cls._owners.clear()
