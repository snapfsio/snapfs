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

__doc__ = """Run or list benchmark cases defined in benchmark_matrix.json."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from tqdm import tqdm

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = REPO_ROOT / "scripts" / "benchmark_matrix.json"
BENCH_SCAN = REPO_ROOT / "scripts" / "bench_scan.py"
DEFAULT_OUTPUT = "benchmark-results.json"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments and return as a namespace."""
    parser = argparse.ArgumentParser(
        description="Run or list benchmark cases defined in benchmark_matrix.json.",
    )
    parser.add_argument(
        "-i",
        "--matrix",
        default=str(DEFAULT_MATRIX),
        help="Path to benchmark matrix JSON file",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        default=[],
        help="Filter to one or more dataset names",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        help="Write results as JSON to this file when executing",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List expanded benchmark cases in JSON format",
    )
    parser.add_argument(
        "--display",
        help="Read an existing benchmark results JSON file and print an ASCII table",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print one result line per completed case",
    )
    return parser.parse_args()


def load_matrix(path: str) -> Dict[str, Any]:
    """Load the benchmark matrix from a JSON file and return as a dictionary."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_results(path: str) -> List[Dict[str, Any]]:
    """Load benchmark results from a JSON file and return as a list of result
    dictionaries."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("results JSON must contain a list of benchmark results")
    return data


def matches_filter(value: str, selected: Iterable[str]) -> bool:
    """Check if a value matches any of the selected filters, or return True if no
    filters are selected."""
    selected = list(selected)
    return not selected or value in selected


def expand_cases(
    matrix: Dict[str, Any], args: argparse.Namespace
) -> List[Dict[str, Any]]:
    """Expand the benchmark matrix into a list of individual benchmark cases to run."""
    cases: List[Dict[str, Any]] = []

    for dataset in matrix.get("datasets", []):
        dataset_name = str(dataset["name"])
        if not matches_filter(dataset_name, args.dataset):
            continue

        dataset_path = str(dataset["path"])

        snapfs = matrix.get("snapfs", {})
        if snapfs.get("enabled", True):
            repeats = int(snapfs.get("repeats", 1))
            for algo in snapfs.get("algos", []):
                for workers in snapfs.get("workers", []):
                    for mode in snapfs.get("modes", ["force"]):
                        for repeat in range(1, repeats + 1):
                            force = mode == "force"
                            cache_mode = "miss" if force else "hit"
                            command = [
                                sys.executable,
                                str(BENCH_SCAN),
                                dataset_path,
                                "--workers",
                                str(workers),
                                "--algo",
                                str(algo),
                                "--json",
                            ]
                            if force:
                                command.append("--force")
                            else:
                                command.extend(["--cache-mode", "hit"])
                            cases.append(
                                {
                                    "dataset": dataset_name,
                                    "dataset_path": dataset_path,
                                    "tool": "snapfs",
                                    "mode": mode,
                                    "algo": str(algo),
                                    "workers": int(workers),
                                    "repeat": repeat,
                                    "command": command,
                                }
                            )

    return cases


def run_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """Run a single benchmark case and return the result dictionary."""
    started = time.perf_counter()
    proc = subprocess.run(
        case["command"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter() - started

    result: Dict[str, Any] = {
        **case,
        "status": "ok" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "elapsed_sec": round(elapsed, 3),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }

    if proc.returncode == 0:
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            result["status"] = "failed"
            result["reason"] = "snapfs output was not valid JSON"
        else:
            result["parsed"] = parsed

    return result


def print_case_list(cases: List[Dict[str, Any]]) -> None:
    """Print the list of benchmark cases in JSON format."""
    print(json.dumps(cases, indent=2, sort_keys=True))


def print_execution_summary(results: List[Dict[str, Any]]) -> None:
    """Print a summary line for each benchmark result."""
    for result in results:
        status = result["status"]
        dataset = result["dataset"]
        tool = result["tool"]
        mode = result["mode"]
        algo = result["algo"]
        workers = result["workers"]
        repeat = result["repeat"]
        elapsed = result.get("elapsed_sec")
        suffix = f"{elapsed}s" if elapsed is not None else result.get("reason", "")
        print(
            f"[{status}] dataset={dataset} tool={tool} mode={mode} "
            f"algo={algo} workers={workers} repeat={repeat} {suffix}"
        )


def format_gib(total_bytes: Optional[int]) -> str:
    """Format total bytes as a human-readable GiB string."""
    if total_bytes is None:
        return ""
    return f"{(float(total_bytes) / (1024 ** 3)):.2f} GiB"


def format_mib_per_sec(total_bytes: Optional[int], elapsed_sec: Optional[float]) -> str:
    """Calculate and format MiB/s throughput given total bytes and elapsed seconds."""
    if not total_bytes or not elapsed_sec:
        return ""
    mib_per_sec = (float(total_bytes) / (1024**2)) / float(elapsed_sec)
    return f"{mib_per_sec:.1f}"


def build_result_row(result: Dict[str, Any]) -> Dict[str, str]:
    """Build a dictionary of string values for a single benchmark result row."""
    parsed = result.get("parsed") or {}
    summary = parsed.get("summary") or {}

    files_value = summary.get("files")
    total_bytes = parsed.get("total_bytes")
    elapsed_sec = parsed.get("elapsed_sec", result.get("elapsed_sec"))
    files_per_sec = parsed.get("files_per_sec")

    notes = ""
    if result["status"] == "failed":
        notes = str(result.get("reason", f"returncode={result.get('returncode', 1)}"))
    else:
        notes = "full scan path"

    return {
        "Dataset": str(result["dataset"]),
        "Tool": str(result["tool"]),
        "Mode": str(result["mode"]),
        "Algo": str(result["algo"]),
        "Workers": str(result["workers"]),
        "Files": "" if files_value is None else str(files_value),
        "Bytes": format_gib(total_bytes),
        "Elapsed s": "" if elapsed_sec is None else str(elapsed_sec),
        "MiB/s": format_mib_per_sec(total_bytes, elapsed_sec),
        "Files/s": "" if files_per_sec is None else str(files_per_sec),
        "Repeat": str(result["repeat"]),
        "Status": str(result["status"]),
        "Notes": notes,
    }


def render_ascii_table(results: List[Dict[str, Any]]) -> str:
    """Render benchmark results as an ASCII table."""
    headers = [
        "Dataset",
        "Tool",
        "Mode",
        "Algo",
        "Workers",
        "Files",
        "Bytes",
        "Elapsed s",
        "MiB/s",
        "Files/s",
        "Repeat",
        "Status",
        "Notes",
    ]
    rows = [build_result_row(result) for result in results]
    widths = {
        header: max(len(header), *(len(row[header]) for row in rows))
        if rows
        else len(header)
        for header in headers
    }

    def border(sep: str = "+", fill: str = "-") -> str:
        return sep + sep.join(fill * (widths[header] + 2) for header in headers) + sep

    def line(values: Dict[str, str]) -> str:
        return (
            "| "
            + " | ".join(values[header].ljust(widths[header]) for header in headers)
            + " |"
        )

    header_values = {header: header for header in headers}
    lines = [border(), line(header_values), border()]
    for row in rows:
        lines.append(line(row))
    lines.append(border())
    return "\n".join(lines)


def write_results_file(results: List[Dict[str, Any]], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2, sort_keys=True)


class ProgressReporter:
    """Helper class to report progress of benchmark execution using tqdm."""

    def __init__(self, total: int, *, enabled: bool = True) -> None:
        """Initialize the progress reporter.

        :param total: Total number of benchmark cases to run.
        :param enabled: Whether to enable progress reporting (only if total > 0).
        """
        self.total = total
        self.enabled = enabled and total > 0
        self.current = 0
        self.bar = None

        if not self.enabled:
            return

        self.bar = tqdm(
            total=total,
            unit="case",
            dynamic_ncols=True,
            disable=not sys.stderr.isatty(),
        )

    def update(self, result: Dict[str, Any]) -> None:
        if not self.enabled:
            return

        self.current += 1
        status = str(result["status"])
        label = (
            f"{result['dataset']} {result['tool']} {result['mode']} "
            f"{result['algo']} w={result['workers']} r={result['repeat']}"
        )

        self.bar.set_postfix_str(f"{status} {label}")
        self.bar.update(1)

    def close(self) -> None:
        if self.bar is not None:
            self.bar.close()


def print_final_summary(
    results: List[Dict[str, Any]],
    *,
    output_path: Optional[str] = None,
) -> None:
    """Print a final summary of benchmark results to stderr.

    :param results: List of benchmark result dictionaries.
    :param output_path: Optional path to JSON results file for reference in summary.
    """
    total = len(results)
    completed = sum(1 for result in results if result["status"] == "ok")
    failed = sum(1 for result in results if result["status"] == "failed")
    print(
        f"Benchmark run complete: total={total} ok={completed} failed={failed}",
        file=sys.stderr,
    )
    if output_path:
        print(f"JSON results: {output_path}", file=sys.stderr)


def main() -> int:
    """Main entry point for benchmark runner script."""
    args = parse_args()
    if args.display:
        try:
            results = load_results(args.display)
        except Exception as exc:
            print(f"Failed to read benchmark results: {exc}", file=sys.stderr)
            return 1
        print(render_ascii_table(results))
        return 0

    try:
        matrix = load_matrix(args.matrix)
        cases = expand_cases(matrix, args)
    except Exception as exc:
        print(f"Benchmark setup failed: {exc}", file=sys.stderr)
        return 1

    if args.list:
        print_case_list(cases)
        return 0

    results: List[Dict[str, Any]] = []
    progress = ProgressReporter(len(cases))
    try:
        for case in cases:
            try:
                result = run_case(case)
            except Exception as exc:
                result = {
                    **case,
                    "status": "failed",
                    "reason": str(exc),
                }
            results.append(result)
            progress.update(result)
            if args.verbose:
                print_execution_summary([result])
    finally:
        progress.close()

    if args.output:
        write_results_file(results, args.output)

    print(render_ascii_table(results))
    print_final_summary(results, output_path=args.output)

    failed = any(result["status"] == "failed" for result in results)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
