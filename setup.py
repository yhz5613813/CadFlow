from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from setuptools import Distribution, setup
from setuptools.command.build_py import build_py


class BinaryDistribution(Distribution):
    def has_ext_modules(self) -> bool:
        return True


class CMakeBuildPy(build_py):
    def run(self) -> None:
        super().run()

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
