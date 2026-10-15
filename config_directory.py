from pathlib import Path


def directory_contains_tsv(directory: Path) -> bool:
    try:
        return directory.is_dir() and any(
            path.is_file() and path.suffix.lower() == ".tsv"
            for path in directory.iterdir()
        )
    except OSError:
        return False


def resolve_current_configuration_directory(start: Path | None = None) -> Path:
    """Default config directory: search the parent of the working directory for TSV files."""
    origin = (start or Path.cwd()).resolve()
    parent = origin.parent
    matches: list[Path] = []
    if directory_contains_tsv(parent):
        matches.append(parent)
    try:
        children = sorted(
            (path for path in parent.iterdir() if path.is_dir()),
            key=lambda path: path.name.casefold(),
        )
    except OSError:
        children = []
    matches.extend(path for path in children if directory_contains_tsv(path))
    named = next((path for path in matches if path.name.casefold() == "tsv"), None)
    if named is not None:
        return named
    if matches:
        return matches[0]
    for candidate in (origin, origin / "tsv"):
        if directory_contains_tsv(candidate):
            return candidate
    return parent
