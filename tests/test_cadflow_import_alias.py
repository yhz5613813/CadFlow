from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (
    ROOT / "python",
    ROOT / "tests",
    ROOT / "examples",
    ROOT / "tools",
    ROOT / "docs",
    ROOT / "scene-contract",
)
TEXT_SUFFIXES = {".py", ".md", ".ts", ".tsx"}


def test_cadflow_package_alias_is_cad_everywhere():
    legacy_import = "import cadflow as " + "scad"
    offenders = []
    for root in SOURCE_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            content = path.read_text(encoding="utf-8")
            if legacy_import in content:
                offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, "legacy cadflow alias found in: " + ", ".join(offenders)
