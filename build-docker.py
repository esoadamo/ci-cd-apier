import tomllib
from sys import argv
from pathlib import Path
from subprocess import check_call

FILE_TOML = Path(__file__).parent / "pyproject.toml"


def get_version() -> str:
    """
    Get the current version of the package from pyproject.toml
    :return: Version string
    """
    with FILE_TOML.open("rb") as f:
        data = tomllib.load(f)
        return data["project"]["version"]    


def main() -> None:
    major_version, minor_version, patch_version = get_version().split(".")

    for version_tag in (
        f"v{major_version}",
        f"v{major_version}.{minor_version}",
        f"v{major_version}.{minor_version}.{patch_version}",
    ):
        print(f"[*] Building Docker image with tag: {version_tag}")
        check_call(["podman", "build", "-t", f"docker.io/esoadamo/ci-cd-apier:{version_tag}", "."])

        if len(argv) > 1 and argv[1] == "--push":
            print(f"[*] Pushing Docker image with tag: {version_tag}")
            check_call(["podman", "push", f"docker.io/esoadamo/ci-cd-apier:{version_tag}"])


if __name__ == "__main__":
    main()
