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
import json
import sys

import click

from snapfs import __prog__, __version__
from snapfs import SnapFS, scanner
from snapfs.config import DEFAULT_GATEWAY


@click.group()
@click.version_option(version=__version__, prog_name=__prog__)
@click.option(
    "--gateway",
    "gateway_url",
    default=DEFAULT_GATEWAY,
    envvar="SNAPFS_GATEWAY",
    help=f"SnapFS gateway base URL (default: {DEFAULT_GATEWAY}).",
)
@click.option(
    "--token",
    envvar="SNAPFS_TOKEN",
    help="Optional auth token for the SnapFS gateway.",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (can be used multiple times).",
)
@click.pass_context
def cli(ctx, gateway_url, token, verbose):
    """
    SnapFS command line interface (gateway-based).
    """
    ctx.ensure_object(dict)
    ctx.obj["gateway_url"] = gateway_url
    ctx.obj["token"] = token
    ctx.obj["verbose"] = verbose


@cli.command()
@click.argument("sql")
@click.pass_context
def query(ctx, sql):
    """
    Run a raw SQL query via the SnapFS gateway.

    Example:
      snapfs query "SELECT COUNT(*) AS n FROM files"
    """
    gateway_url = ctx.obj.get("gateway_url")
    token = ctx.obj.get("token")

    if not gateway_url:
        click.echo("Error: --gateway or SNAPFS_GATEWAY is required.", err=True)
        sys.exit(1)

    client = SnapFS(gateway_url=gateway_url, token=token)

    try:
        rows = client.sql(sql)
    except Exception as e:
        click.echo(f"Query failed: {e}", err=True)
        sys.exit(1)

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
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (can be used multiple times).",
)
@click.pass_context
def scan(ctx, path, force: bool = False, verbose: int = 0):
    """
    Scan a filesystem PATH and publish events to the SnapFS gateway.

    Example:
      snapfs scan /mnt/data/projects
      snapfs scan /mnt/data/projects --force
    """
    gateway_url = ctx.obj.get("gateway_url")
    token = ctx.obj.get("token")

    if not gateway_url:
        click.echo("Error: --gateway or SNAPFS_GATEWAY is required.", err=True)
        sys.exit(1)

    snap = SnapFS(gateway_url=gateway_url, token=token)
    gateway = snap.gateway

    try:
        summary = asyncio.run(
            scanner.scan_dir(path, gateway, force=force, verbose=verbose)
        )
    except NotADirectoryError:
        click.echo(f"Error: not a directory: {path}", err=True)
        sys.exit(2)
    except Exception as e:
        click.echo(f"Scan failed: {e}", err=True)
        sys.exit(1)

    if verbose > 0:
        click.echo(json.dumps(summary, sort_keys=True))


def entrypoint():
    """Console script entrypoint declared in pyproject.toml."""
    cli(obj={})
