"""Extension -> category map used by `tidy sort --by type`."""

from __future__ import annotations

CATEGORIES: dict[str, tuple[str, ...]] = {
    "Documents": (
        "pdf", "doc", "docx", "odt", "rtf", "txt", "md", "tex", "pages",
        "epub", "mobi", "djvu",
    ),
    "Spreadsheets": ("xls", "xlsx", "xlsm", "ods", "csv", "tsv", "numbers"),
    "Presentations": ("ppt", "pptx", "odp", "key"),
    "Images": (
        "jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp", "heic",
        "heif", "svg", "ico", "raw", "cr2", "nef", "dng", "psd", "ai", "eps",
    ),
    "Video": (
        "mp4", "mkv", "mov", "avi", "wmv", "flv", "webm", "m4v", "mpg",
        "mpeg", "3gp",
    ),
    "Audio": ("mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "aiff", "opus", "mid"),
    "Archives": (
        "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "zst", "tar.gz",
        "tar.bz2", "tar.xz", "tar.zst", "iso", "dmg",
    ),
    "Installers": ("exe", "msi", "deb", "rpm", "pkg", "apk", "appimage"),
    "Code": (
        "py", "js", "jsx", "ts", "tsx", "java", "c", "h", "cpp", "hpp", "cs",
        "go", "rs", "rb", "php", "swift", "kt", "sh", "bash", "ps1", "bat",
        "sql", "r", "ipynb", "lua", "pl",
    ),
    "Data": ("json", "yaml", "yml", "xml", "toml", "ini", "cfg", "parquet", "db", "sqlite", "jsonl"),
    "Fonts": ("ttf", "otf", "woff", "woff2", "eot"),
    "Torrents": ("torrent",),
}

OTHER = "Other"
NO_EXTENSION = "No Extension"

_LOOKUP: dict[str, str] = {
    ext: category for category, extensions in CATEGORIES.items() for ext in extensions
}


def category_for(extension: str) -> str:
    """Map a bare extension ('pdf', 'TAR.GZ') to a category folder name."""
    if not extension:
        return NO_EXTENSION
    return _LOOKUP.get(extension.lower().lstrip("."), OTHER)


def known_categories() -> list[str]:
    return [*CATEGORIES.keys(), OTHER, NO_EXTENSION]
