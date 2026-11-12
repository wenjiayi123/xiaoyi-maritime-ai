"""Resolve recorded Mac paths to the matching preserved local artifact tree."""
from pathlib import Path, PurePosixPath

ROOT=Path(__file__).resolve().parents[2]
ARCHIVE=PurePosixPath("小懿AI/.codex_artifacts")


def artifact_path(value):
    source=PurePosixPath(str(value).replace("\\","/"))
    archive = next((parent for parent in source.parents if parent.parts[-2:] == ARCHIVE.parts), None)
    if source.is_absolute() and archive is not None:
        relative=source.relative_to(archive)
        if any(part==".." or ":" in part for part in relative.parts):
            raise ValueError("Invalid archive path")
        return ROOT/".codex_artifacts"/relative
    return Path(value)
