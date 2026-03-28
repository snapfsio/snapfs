#!/usr/bin/env python3
#
# Copyright (c) 2025 SnapFS, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import hashlib
from concurrent.futures import Executor
from functools import partial
from typing import Callable, Dict, List, Optional

try:
    import xxhash  # type: ignore
except ImportError:  # optional dependency
    xxhash = None  # type: ignore[assignment]

DEFAULT_CHUNK_SIZE = 1024 * 1024

HasherFactory = Callable[[], object]


def _sha1_factory() -> object:
    """Factory for sha1 hasher."""
    return hashlib.sha1()


def _sha256_factory() -> object:
    """Factory for sha256 hasher."""
    return hashlib.sha256()


def _xxh64_factory() -> object:
    """Factory for xxh64 hasher, requires optional xxhash package."""
    if xxhash is None:
        raise RuntimeError(
            "Algorithm 'xxh64' requires the optional 'xxhash' package to be installed."
        )
    return xxhash.xxh64()


_HASH_FACTORIES: Dict[str, HasherFactory] = {
    "sha1": _sha1_factory,
    "sha256": _sha256_factory,
}
if xxhash is not None:
    _HASH_FACTORIES["xxh64"] = _xxh64_factory

_OPTIONAL_ALGORITHMS = {"xxh64": "pip install snapfs[xxhash]"}


def list_algorithms(*, include_unavailable: bool = False) -> List[str]:
    """List available hash algorithms.

    :param include_unavailable: If True, include algorithms that are not currently
        available but could be supported with optional dependencies.
    :return: A list of available algorithm names.
    """
    names = sorted(_HASH_FACTORIES.keys())
    if include_unavailable:
        for name in sorted(_OPTIONAL_ALGORITHMS.keys()):
            if name not in names:
                names.append(name)
    return names


def is_available(name: str) -> bool:
    return str(name).strip().lower() in _HASH_FACTORIES


def resolve_algorithm(name: Optional[str]) -> str:
    """Resolve a hash algorithm name to a supported algorithm, or raise an error
    if unsupported.

    :param name: The name of the hash algorithm to resolve. If None or empty,
        defaults to "sha1".
    :return: The resolved algorithm name.
    """
    algo = str(name or "sha1").strip().lower()
    if algo in _HASH_FACTORIES:
        return algo
    if algo in _OPTIONAL_ALGORITHMS:
        raise ValueError(
            f"Unsupported hash algorithm '{algo}' in this environment. "
            f"Install support with: {_OPTIONAL_ALGORITHMS[algo]}"
        )
    raise ValueError(
        f"Unsupported hash algorithm '{algo}'. "
        f"Available: {', '.join(list_algorithms(include_unavailable=True))}"
    )


def get_hasher(name: str) -> object:
    """Get a new hasher instance for the specified algorithm.

    :param name: The name of the hash algorithm to use.
    :return: A new hasher instance.
    """
    algo = resolve_algorithm(name)
    return _HASH_FACTORIES[algo]()


def hash_file(
    path: str, algorithm: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> str:
    """Hash a file using the specified algorithm.

    :param path: The path to the file to hash.
    :param algorithm: The name of the hash algorithm to use.
    :param chunk_size: The size of chunks to read from the file (default: 1 MiB).
    :return: The hexadecimal digest of the file hash.
    """
    hasher = get_hasher(algorithm)
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


async def hash_file_async(
    path: str,
    algorithm: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    executor: Optional[Executor] = None,
) -> str:
    """Async wrapper for hash_file to run in an executor.

    :param path: The path to the file to hash.
    :param algorithm: The name of the hash algorithm to use.
    :param chunk_size: The size of chunks to read from the file (default: 1 MiB).
    :param executor: Optional executor used to perform hashing work.
    :return: The hexadecimal digest of the file hash.
    """
    loop = asyncio.get_running_loop()
    func = partial(hash_file, path, algorithm, chunk_size=chunk_size)
    return await loop.run_in_executor(executor, func)
