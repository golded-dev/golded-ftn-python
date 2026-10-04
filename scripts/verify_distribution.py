"""Inspect archives, rebuild the sdist, and test a wheel outside the checkout."""

import email
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, cwd: Path) -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    subprocess.run(args, cwd=cwd, env=env, check=True)


def main() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    wheels = list((ROOT / "dist").glob("*.whl"))
    sdists = list((ROOT / "dist").glob("*.tar.gz"))
    assert len(wheels) == len(sdists) == 1, "Expected exactly one wheel and sdist"
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        assert "golded_ftn/py.typed" in names
        expected = {
            "golded_ftn/" + path.name
            for path in (ROOT / "src/golded_ftn").glob("*")
            if path.is_file()
        }
        actual = {name for name in names if name.startswith("golded_ftn/")}
        assert actual == expected, (actual, expected)
        metadata = email.message_from_bytes(
            archive.read(next(n for n in names if n.endswith("/METADATA")))
        )
        assert metadata["Name"] == project["name"]
        assert metadata["Version"] == project["version"]
        assert metadata["Requires-Python"] == ">=3.12"
        assert metadata["License-Expression"] == "MIT"
        assert metadata.get_all("Requires-Dist", []) == []
        assert any(n.endswith("/licenses/LICENSE") for n in names)
    with tempfile.TemporaryDirectory(prefix="golded-ftn-check-") as temporary:
        work = Path(temporary)
        with tarfile.open(sdists[0]) as archive:
            assert all(
                "/.venv/" not in n and "/.git/" not in n for n in archive.getnames()
            )
            archive.extractall(work, filter="data")
        (source,) = [p for p in work.iterdir() if p.is_dir()]
        for name in (
            "LICENSE",
            "README.md",
            "tests/test_core.py",
            "uv.lock",
            "src/golded_ftn/py.typed",
        ):
            assert (source / name).is_file(), name
        package_info = email.message_from_bytes((source / "PKG-INFO").read_bytes())
        assert package_info["Name"] == project["name"]
        assert package_info["Version"] == project["version"]
        run("uv", "build", "--wheel", cwd=source)
        (rebuilt,) = (source / "dist").glob("*.whl")
        with zipfile.ZipFile(wheels[0]) as first, zipfile.ZipFile(rebuilt) as second:
            assert set(first.namelist()) == set(second.namelist())
            assert all(first.read(n) == second.read(n) for n in first.namelist())
        env_path = work / "clean-env"
        run("uv", "venv", "--python", sys.executable, str(env_path), cwd=work)
        python = env_path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            str(rebuilt),
            cwd=work,
        )
        run(
            str(python),
            "-c",
            "import golded_ftn; from importlib.metadata import requires; "
            'assert requires("golded-ftn") is None; print(golded_ftn.__file__)',
            cwd=work,
        )
        run("uv", "pip", "install", "--python", str(python), "pytest", "mypy", cwd=work)
        shutil.copytree(source / "tests", work / "tests")
        shutil.copy(source / "README.md", work / "README.md")
        run(str(python), "-m", "pytest", "tests", "-q", cwd=work)
        run(str(python), "-m", "mypy", "--strict", "tests", cwd=work)
    print("Metadata, contents, sdist rebuild, wheel tests and consumer typing passed.")


if __name__ == "__main__":
    main()
