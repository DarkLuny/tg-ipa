# This is the source code of the exteraGram plugins SDK.
#
# We do not and cannot prevent the use of our code,
# but be respectful and credit the original author.
#
# Copyright @exteraGram, 2022-2026
#
# Licensed under the GNU GPL v. 3 or later, with the additional terms
# in ADDITIONAL_TERMS.md at the root of the repository.

import json
import os
import string
import sys
from pathlib import Path
from typing import Optional, Union
from zipfile import ZipInfo, ZipFile

_VENDOR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_vendor"
)
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

import requests
import yaml

from client_utils import get_last_fragment
from file_utils import get_cache_dir
from extera_utils.classes import NativeFile

File = NativeFile


def load_data_file(path: Union[Path, ZipInfo], plzip: Optional[ZipFile] = None) -> dict:
    content = path.decode() if isinstance(path, bytes) else (
        path.read_text()
        if isinstance(path, Path)
        else plzip.read(
            path.filename
            if isinstance(path, ZipInfo)
            else path
        ).decode()
    )

    suffix = (
        path.suffix[1:]
        if isinstance(path, Path)
        else (
            path.filename
            if isinstance(path, ZipInfo)
            else path
        ).split("/")[-1].split(".")[-1]
        if isinstance(path, (ZipInfo, str))
        else ""
    )

    if suffix == 'json':
        return json.loads(content)
    elif suffix in ('yaml', 'yml'):
        return yaml.safe_load(content)

    return {}

############### Assets PART ################

def normalize_name(name: str) -> str:
    return "".join(["_" if not i in string.ascii_letters + string.digits else i for i in name])

class AssetNotFoundException(Exception):
    def __init__(self, name: str, dir_path: Optional[str] = None):
        super().__init__(f"Asset \"{name}\" not found in directory {dir_path}")

class AssetsDirNotFoundException(Exception):
    def __init__(self, dir_path: Optional[str] = None):
        super().__init__(f"Directory {dir_path} does not exist")


class Asset:
    def __init__(self, dir_path: Union[str, Path, File], filename: str, name: str):
        """
        Args:
            dir_path (Union[str, Path, File]) - path of asset root directory
            filename (str) - name of asset file
            name (str) - name of asset

        Raises:
            ValueError - if dir_path is not a directory
            AssetsDirNotFoundException - if dir_path does not exist
            AssetNotFoundException - if dir_path is not a directory
        """
        if not dir_path or not filename or not name:
            raise ValueError("dir_path, filename and name must be provided")

        if isinstance(dir_path, File) or hasattr(dir_path, "getAbsolutePath"):
            dir_path = str(dir_path.getAbsolutePath())

        self.dir_path = dir_path if isinstance(dir_path, Path) else Path(dir_path)
        self.name = normalize_name(name)
        self.filename = filename
        self.ext = filename.split(".")[-1]

        if not self.dir_path.is_dir():
            raise ValueError(f"Path {dir_path} is not a directory")
        if not self.dir_path.exists():
            raise AssetsDirNotFoundException(str(self.dir_path))
        if not self.path.exists():
            raise AssetNotFoundException(name, str(dir_path))

    @classmethod
    def from_path(cls, path: Union[str, Path, File]) -> "Asset":
        if isinstance(path, File):
            path = path.getAbsolutePath()

        if isinstance(path, str):
            path = Path(path)

        if not path.is_file():
            raise IsADirectoryError(f"Path {path} is not a file")
        if not path.exists():
            raise FileNotFoundError(f"Path {path} does not exist")

        return cls(path.parent, path.name, path.name.split(".")[0])

    @classmethod
    def temp_asset_from_url(cls, url: str, filename: str) -> "Asset":
        dir_ = NativeFile(get_cache_dir(), "elyx_assets")
        if not dir_.exists():
            dir_.mkdirs()

        temp_file = NativeFile(dir_, filename)
        temp_file.deleteOnExit()

        with requests.get(url) as resp:
            with open(temp_file.getAbsolutePath(), "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

        return cls(str(dir_), filename, "_".join(filename.split(".")[:-1]))

    @property
    def path_str(self) -> str:
        return str(self.path)

    @property
    def path(self) -> Path:
        return self.dir_path.joinpath(self.filename)

    @property
    def java_file(self) -> File:
        return NativeFile(self.path_str)

    def to_image_location(self):
        return NativeFile(self.path_str)

    def to_drawable(self):
        return NativeFile(self.path_str)

    def to_bitmap_drawable(self, width: int = 32, height: int = 32):
        return NativeFile(self.path_str)

    def to_lottie_drawable(self, width: int = 32, height: int = 32):
        return NativeFile(self.path_str)

    def to_svg_drawable(self, width: Optional[int] = None, height: Optional[int] = None, *args):
        return NativeFile(self.path_str)

    def to_svg_thumb(self, color_key: int, alpha: float):
        path_thumb = self.to_svg_drawable()
        setup = getattr(path_thumb, "setupGradient", None)
        if setup is not None:
            setup(color_key, alpha, False)

        return path_thumb

    def to_svg_bitmap(self, width: int = 32, height: int = 32, white: bool = False):
        return NativeFile(self.path_str)

    def content_bytes(self) -> bytes:
        return self.path.read_bytes()

    def content_string(self) -> str:
        return self.path.read_text()

    def content_json(self) -> dict:
        return load_data_file(self.path)

    def content_yaml(self) -> dict:
        return load_data_file(self.path)

    def content(self) -> dict | str | bytes:
        if self.ext in ["json", "yaml", "yml"]:
            return load_data_file(self.path)

        try:
            return self.content_string()
        except:  # noqa
            return self.content_bytes()

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return f"<Elyx.Asset name={self.name} path={self.path_str} ext={self.ext}>"


class Assets:
    def __init__(self, dir_path: Union[str, Path]):
        if isinstance(dir_path, str):
            dir_path = Path(dir_path)

        if not dir_path.is_dir():
            raise ValueError(f"Path {dir_path} is not a directory")
        if not dir_path.exists():
            raise AssetsDirNotFoundException(str(dir_path))
        if dir_path.parent.name == "ElyxPlugins" or dir_path.name == "plugins" or dir_path.parent.name == "plugins" or dir_path.name == "ElyxPlugins":
            raise ValueError(f"Path {dir_path} is a plugin directory")

        self.dir_path = dir_path
        self.files = {
            f.name: f
            for f in dir_path.iterdir()
        }
        self.names = {
            normalize_name(f.name.split(".")[0]): f.name
            for f in self.files.values()
        }

    @property
    def parent(self) -> "Assets":
        return Assets(self.dir_path.parent)

    def get(self, name: str) -> Union[Asset, "Assets"]:
        # support "folder/file" or "folder/file.ext" path syntax
        if "/" in name:
            parts = name.split("/", 1)
            return self.get(parts[0]).get(parts[1])

        if name not in self.names and name not in self.files:
            raise AssetNotFoundException(name, str(self.dir_path))

        path = self.dir_path.joinpath(name if name not in self.names else self.names[name])

        if path.is_dir():
            return Assets(path)

        return Asset(
            self.dir_path,
            self.names[name] if name in self.names else name,
            name if name in self.names else name.split(".")[0]
        )

    def __getitem__(self, item):
        return self.get(item)

    def __getattr__(self, item):
        return self.get(item)

    def __contains__(self, item):
        return item in self.names or item in self.files

    def __iter__(self):
        return iter(self.files)

    def __len__(self):
        return len(self.files)

    def __repr__(self):
        return f"<Elyx.Assets dir_path={self.dir_path}>"

    def __str__(self):
        return self.__repr__()

############### END Assets PART ################
