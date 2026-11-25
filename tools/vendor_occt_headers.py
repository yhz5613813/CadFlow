"""Vendor the OCCT headers a native source file needs into third_party/occt.

third_party/occt holds only the headers CadFlow compiles against. When new
native code includes an OCCT header outside that subset, run:

    python tools/vendor_occt_headers.py native/src/analysis/surface_analysis.cpp \\
        --occt-source /path/to/OCCT-7_9_3/src

The script repeatedly syntax-checks the file with the flags from
build/compile_commands.json (configure with -DCMAKE_EXPORT_COMPILE_COMMANDS=ON)
and copies each missing header from the matching OCCT source tree. Re-run the
CMake configure step afterwards so new package directories are on the include
path. The OCCT tree must be the exact version of the linked cadquery-ocp wheel.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", help="native source file to make compile")
    parser.add_argument("--occt-source", required=True, help="OCCT src/ directory")
    parser.add_argument("--build", default=str(ROOT / "build"))
    args = parser.parse_args()

    target = Path(args.source).resolve()
    commands = json.loads((Path(args.build) / "compile_commands.json").read_text())
    entry = next((item for item in commands if Path(item["file"]).resolve() == target), None)
    if entry is None:
        raise SystemExit(f"{target} is not in compile_commands.json; re-run the CMake configure step")
    command = shlex.split(entry["command"])
    output = command.index("-o")
    command = [part for part in command[:output] + command[output + 2:] if part != "-c"]
    command.append("-fsyntax-only")

    vendored = ROOT / "third_party" / "occt" / "src"
    for package in sorted(vendored.iterdir()):
        command.insert(1, f"-isystem{package}")
    index: dict[str, list[Path]] = {}
    for directory, _, files in os.walk(args.occt_source):
        for name in files:
            index.setdefault(name, []).append(Path(directory) / name)

    added: list[str] = []
    while True:
        result = subprocess.run(command, capture_output=True, text=True, cwd=entry["directory"])
        missing = re.search(r"fatal error: ([\w./]+): No such file", result.stderr)
        if not missing:
            break
        candidates = index.get(missing.group(1), [])
        if len(candidates) != 1:
            raise SystemExit(f"cannot resolve {missing.group(1)}: {candidates}")
        relative = candidates[0].relative_to(args.occt_source)
        destination = vendored / relative
        if not destination.parent.is_dir():
            destination.parent.mkdir(parents=True)
            command.insert(1, f"-isystem{destination.parent}")
        shutil.copy2(candidates[0], destination)
        added.append(str(relative))
    print(f"vendored {len(added)} header(s)")
    for name in sorted(added):
        print(f"  {name}")
    if result.returncode:
        raise SystemExit(result.stderr)


if __name__ == "__main__":
    main()
