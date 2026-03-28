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
import click
import json
from typing import Callable, List, Optional, TypeVar

from snapfs import SnapFS, __prog__, __version__
from snapfs import agent as agent_mod
from snapfs import scanner
from snapfs import hashing
from snapfs.config import settings

F = TypeVar("F", bound=Callable[..., object])


def _require_gateway(gateway_url: str) -> None:
    if not gateway_url:
        raise click.ClickException("Missing --gateway (or SNAPFS_GATEWAY).")


def _scanner_token_scopes() -> List[str]:
    """Parse scanner token scopes from settings."""
    raw = (settings.scanner_token_scopes or "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _auto_auth_scanner_client(client: SnapFS, explicit_token: Optional[str]) -> None:
    """Auto-exchange API key for scanner JWT when no explicit token is provided."""
    if explicit_token:
        return
    if not settings.api_key:
        return

    scopes = _scanner_token_scopes()
    token = asyncio.run(
        client.gateway.exchange_scanner_token_async(
            api_key=settings.api_key,
            scopes=scopes or None,
        )
    )
    client.gateway.token = token


def _validate_hash_algorithm(
    ctx: click.Context, param: click.Parameter, value: Optional[str]
) -> Optional[str]:
    if value is None:
        return value
    try:
        return hashing.resolve_algorithm(value)
    except ValueError as e:
        raise click.BadParameter(str(e), ctx=ctx, param=param) from e


def gateway_options(func: F) -> F:
    """
    Decorator adding standard gateway options to a command.

    Commands using this decorator accept:
      --gateway (or env SNAPFS_GATEWAY)
      --token   (or env SNAPFS_TOKEN)

    Note: options are defined on the *command*, so users can write:
      snapfs scan --gateway https://... /path
      snapfs query --gateway https://... "SELECT ..."
    """
    func = click.option(
        "-t",
        "--token",
        default=None,
        envvar="SNAPFS_TOKEN",
        help="Optional auth token for the SnapFS gateway.",
    )(func)
    func = click.option(
        "-g",
        "--gateway",
        "gateway_url",
        default=settings.gateway,
        envvar="SNAPFS_GATEWAY",
        help=f"SnapFS gateway base URL (default: {settings.gateway}).",
    )(func)
    return func  # type: ignore[return-value]


def verbose_option(func: F) -> F:
    """Standard verbosity option: -v/--verbose repeatable count."""
    return click.option(
        "-v",
        "--verbose",
        count=True,
        help="Increase verbosity (can be used multiple times).",
    )(
        func
    )  # type: ignore[return-value]


@click.group()
@click.version_option(version=__version__, prog_name=__prog__)
def cli() -> None:
    """
    SnapFS command line interface (gateway-based).

    Note: This CLI intentionally keeps gateway/token options on each command
    (not global group options) so you can place them after the command.
    """
    pass


@cli.command()
@click.argument("sql")
@gateway_options
def query(sql: str, gateway_url: str, token: Optional[str]) -> None:
    """
    Run a raw SQL query via the SnapFS gateway.

    Example:
      snapfs query "SELECT COUNT(*) AS n FROM files" --gateway https://tenant.snapfs.com
    """
    _require_gateway(gateway_url)

    client = SnapFS(gateway_url=gateway_url, token=token)
    _auto_auth_scanner_client(client, token)

    try:
        rows = client.sql(sql)
    except Exception as e:
        raise click.ClickException(f"Query failed: {e}") from e

    for row in rows:
        click.echo(json.dumps(row, sort_keys=True))


@cli.command()
@click.argument(
    "path",
    type=click.Path(
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
)
@click.option(
    "--force",
    is_flag=True,
    help="Force re-hashing files even when cache reports a hit.",
)
@click.option(
    "--algo",
    default=settings.hash_algo,
    show_default=True,
    callback=_validate_hash_algorithm,
    help=(
        "Hash algorithm to use "
        f"({', '.join(hashing.list_algorithms(include_unavailable=True))})."
    ),
)
@verbose_option
@gateway_options
def scan(
    path: str,
    force: bool,
    algo: str,
    verbose: int,
    gateway_url: str,
    token: Optional[str],
) -> None:
    """
    Scan a filesystem PATH and publish events to the SnapFS gateway.

    Examples:
      snapfs scan /mnt/data/projects --gateway https://tenant.snapfs.com
      snapfs scan /mnt/data/projects --force --gateway http://localhost:8000
      snapfs scan /mnt/data/projects -vv --gateway https://tenant.snapfs.com
    """
    _require_gateway(gateway_url)

    client = SnapFS(gateway_url=gateway_url, token=token)
    _auto_auth_scanner_client(client, token)

    try:
        summary = asyncio.run(
            scanner.scan_dir(path, client, force=force, verbose=verbose, algo=algo)
        )
    except NotADirectoryError as e:
        raise click.ClickException(f"Not a directory: {path}") from e
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise click.ClickException(f"Scan failed: {e}") from e

    if verbose > 0:
        click.echo(json.dumps(summary, sort_keys=True))


@cli.command()
@click.option(
    "--agent-id",
    default=None,
    envvar="SNAPFS_AGENT_ID",
    help="Agent identifier (default: SNAPFS_AGENT_ID).",
)
@click.option(
    "--root",
    "scan_root",
    default=None,
    envvar="SNAPFS_SCAN_ROOT",
    help="Default scan root if the gateway does not specify one (default: SNAPFS_SCAN_ROOT).",
)
@click.option(
    "--algo",
    default=settings.hash_algo,
    show_default=True,
    callback=_validate_hash_algorithm,
    help=(
        "Hash algorithm to use for agent scans "
        f"({', '.join(hashing.list_algorithms(include_unavailable=True))})."
    ),
)
@verbose_option
@gateway_options
def agent(
    agent_id: Optional[str],
    scan_root: Optional[str],
    algo: str,
    verbose: int,
    gateway_url: str,
    token: Optional[str],
) -> None:
    """
    Run the SnapFS scanner agent.

    Examples:
      snapfs agent --gateway https://<username>.snapfs.com --root /mnt/data
      snapfs agent --gateway http://localhost:8000 --agent-id scanner-01 -v
    """
    _require_gateway(gateway_url)

    client = SnapFS(gateway_url=gateway_url, token=token)
    _auto_auth_scanner_client(client, token)
    settings.hash_algo = algo

    asyncio.run(
        agent_mod.run_agent(
            client=client,
            agent_id=agent_id,
            scan_root=scan_root,
            verbose=verbose,
        )
    )


def entrypoint() -> None:
    """Console script entrypoint declared in pyproject.toml."""
    cli()
