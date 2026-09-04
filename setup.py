from __future__ import annotations

import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path

from setuptools import Distribution, setup
from setuptools.command.build_py import build_py


if sys.platform == "darwin":
    os.environ.setdefault("MACOSX_DEPLOYMENT_TARGET", "12.0")


class BinaryDistribution(Distribution):
    def has_ext_modules(self) -> bool:
        return True


class CMakeBuildPy(build_py):
    def run(self) -> None:
        super().run()

        if sys.platform == "darwin":
            if platform.machine() != "arm64":
                raise RuntimeError(
                    "CadFlow macOS wheels must be built natively on Apple Silicon"
                )
            if sys.version_info[:2] != (3, 13):
                raise RuntimeError("CadFlow macOS wheels require CPython 3.13")

        root = Path(__file__).resolve().parent
        build = Path(self.get_finalized_command("build").build_temp) / "cadflow-native"
        configure = [
            "cmake",
            "-S",
            str(root),
            "-B",
            str(build),
            "-DCMAKE_BUILD_TYPE=Release",
            f"-DPython3_EXECUTABLE={sys.executable}",
        ]
        if sys.platform == "darwin":
            configure.extend(
                [
                    "-DCMAKE_OSX_ARCHITECTURES="
                    + os.environ.get("CMAKE_OSX_ARCHITECTURES", "arm64"),
                    "-DCMAKE_OSX_DEPLOYMENT_TARGET="
                    + os.environ["MACOSX_DEPLOYMENT_TARGET"],
                ]
            )
        configure.extend(shlex.split(os.environ.get("CMAKE_ARGS", "")))
        subprocess.run(configure, check=True)
        subprocess.run(
            ["cmake", "--build", str(build), "--config", "Release", "--parallel", "2"],
            check=True,
        )
        subprocess.run(
            [
                "cmake",
                "--install",
                str(build),
                "--config",
                "Release",
                "--prefix",
                str(Path(self.build_lib).resolve()),
            ],
            check=True,
        )


setup(cmdclass={"build_py": CMakeBuildPy}, distclass=BinaryDistribution)
