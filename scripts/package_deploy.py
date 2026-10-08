#!/usr/bin/env python3
"""Package the current deployment source, including uncommitted source files.

Uses an explicit allowlist rather than Git's tracked files or an unrestricted
workspace archive. It never searches or reads runtime configuration/databases.
Run: python3 scripts/package_deploy.py [--output dist/huhua-deploy.tar.gz]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import tempfile


EXACT_FILES = (
    "Dockerfile",
    ".dockerignore",
    "requirements.txt",
    "compose.yaml",
    "backend/main.py",
    "data/sample_resume.json",
    "data/jargon_dict.csv",
    "deploy/Caddyfile",
    "deploy/compose.host-caddy.yaml",
    "deploy/app.env.example",
    "deploy/compose.env.example",
    "deploy/init_env.py",
    "docs/development/docker-deployment.md",
    "docs/development/2026-10-05-server-deployment.md",
    "docs/development/2026-10-06-web-tools.md",
    "docs/development/security-operations.md",
)
ENV_EXAMPLES = frozenset(("deploy/app.env.example", "deploy/compose.env.example"))
DIRECTORY_SUFFIXES = {
    "backend/app": frozenset((".py", ".md", ".json", ".txt", ".j2", ".jinja2")),
    "backend/scripts": frozenset((".py",)),
    "web": frozenset((
        ".html", ".js", ".css", ".json", ".md", ".txt", ".svg", ".png",
        ".jpg", ".jpeg", ".webp", ".ico", ".gif", ".woff", ".woff2",
        ".ttf", ".otf", ".map",
    )),
    "data/jianlimoban/html-template": frozenset((
        ".j2", ".jinja2", ".html", ".css", ".js", ".json", ".svg", ".woff2",
    )),
}
EXCLUDED_DIRECTORIES = frozenset((
    "__pycache__", "node_modules", "venv", "env", "cache", "caches",
    "dist", "build", "output", "outputs", "backup", "backups", "archive",
    "archives", "runtime", "storage", "database", "databases", "db",
    "checkpoints", "uploads", "downloads", "logs", "log", "tmp", "temp",
    "secrets", "credentials", "private",
))
EXCLUDED_FILE_SUFFIXES = frozenset((
    ".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".sql", ".dump",
    ".bak", ".backup", ".old", ".orig", ".log", ".pem", ".key",
    ".p12", ".pfx", ".zip", ".gz", ".tar", ".7z", ".rar",
))
PRIVATE_FILE_NAMES = re.compile(
    r"^(?:secrets?|credentials?|private|backup|output)(?:[._-]|$)", re.IGNORECASE
)
LICENSE_FILE_NAMES = re.compile(r"(?:^|[-_])(?:LICENSE|LICENCE|NOTICE)(?:[-_.].*)?$", re.IGNORECASE)


class PackageError(Exception):
    """A fail-closed source or output validation error."""


def absolute(path: Path) -> Path:
    """Normalize dot components without silently following a symlink."""
    return Path(os.path.abspath(os.fspath(path)))


def reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise PackageError(f"拒绝符号链接：{current}")


def excluded(relative: Path) -> bool:
    name = relative.name.lower()
    if relative.as_posix() in ENV_EXAMPLES:
        return False
    if any(part.startswith(".") for part in relative.parts):
        return True
    if any(part.lower() in EXCLUDED_DIRECTORIES for part in relative.parts):
        return True
    if name.startswith(".env") or name.endswith(".env") or ".env." in name:
        return True
    if any(suffix.lower() in EXCLUDED_FILE_SUFFIXES for suffix in relative.suffixes):
        return True
    if re.search(r"\.(?:db|sqlite|sqlite3)-(?:wal|shm|journal)$", name):
        return True
    return bool(PRIVATE_FILE_NAMES.match(name))


def collect_sources(root: Path) -> list[Path]:
    """Return permitted relative regular files; never descend into excluded dirs."""
    root = absolute(root)
    reject_symlink_components(root)
    if not root.is_dir():
        raise PackageError(f"源码目录不存在：{root}")
    sources: set[Path] = set()
    missing = []
    for name in EXACT_FILES:
        relative = Path(name)
        path = root / relative
        reject_symlink_components(path)
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            missing.append(name)
            continue
        if not stat.S_ISREG(mode):
            raise PackageError(f"部署源必须是普通文件：{name}")
        if name != ".dockerignore" and excluded(relative):
            raise PackageError(f"白名单文件触发排除规则：{name}")
        sources.add(relative)

    def visit(relative: Path, suffixes: frozenset[str], vendor_licenses: bool) -> None:
        directory = root / relative
        reject_symlink_components(directory)
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            child = path.relative_to(root)
            mode = path.lstat().st_mode
            # A hidden/otherwise excluded link is still a link, not a safe file.
            if stat.S_ISLNK(mode):
                raise PackageError(f"拒绝源码符号链接：{child.as_posix()}")
            if excluded(child):
                continue
            if stat.S_ISDIR(mode):
                visit(child, suffixes, vendor_licenses)
            elif not stat.S_ISREG(mode):
                raise PackageError(f"部署源包含特殊文件：{child.as_posix()}")
            elif path.suffix.lower() in suffixes or (
                vendor_licenses and child.parts[:2] == ("web", "vendor")
                and LICENSE_FILE_NAMES.search(path.name)
            ):
                sources.add(child)

    for name, suffixes in DIRECTORY_SUFFIXES.items():
        relative = Path(name)
        directory = root / relative
        reject_symlink_components(directory)
        if not directory.exists():
            missing.append(name + "/")
        elif not directory.is_dir():
            raise PackageError(f"部署源码目录类型错误：{name}")
        else:
            visit(relative, suffixes, name == "web")
    if missing:
        raise PackageError("部署文件尚未齐备：" + "、".join(missing))
    return sorted(sources, key=lambda path: path.as_posix())


def read_source(root: Path, relative: Path) -> tuple[bytes, int]:
    """Read only a permitted regular file, rejecting swaps and concurrent writes."""
    path = root / relative
    reject_symlink_components(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise PackageError(f"源码不再是普通文件：{relative}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise PackageError(f"读取前源码发生替换：{relative}")
        contents = stream.read()
        after = os.fstat(stream.fileno())
    if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(contents) != after.st_size:
        raise PackageError(f"打包期间源码正在变化，请重试：{relative}")
    return contents, 0o755 if after.st_mode & 0o111 else 0o644


def build_archive(root: Path, output: Path) -> dict:
    root, output = absolute(root), absolute(output)
    if not output.name.endswith(".tar.gz"):
        raise PackageError("输出文件名必须以 .tar.gz 结尾")
    sources = collect_sources(root)
    reject_symlink_components(output)
    if output in (root / relative for relative in sources):
        raise PackageError("输出路径不能覆盖部署源码")
    if output.exists() and not output.is_file():
        raise PackageError("输出路径必须是普通文件")
    output.parent.mkdir(parents=True, exist_ok=True)
    reject_symlink_components(output.parent)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".huhua-deploy-", suffix=".tmp", dir=output.parent, delete=False) as destination:
            temporary = Path(destination.name)
            # No absolute host paths, owner names, or variable timestamps in tar.
            with gzip.GzipFile(fileobj=destination, filename="", mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for relative in sources:
                        contents, mode = read_source(root, relative)
                        member = tarfile.TarInfo(relative.as_posix())
                        member.size = len(contents)
                        member.mode = mode
                        member.mtime = 0
                        member.uid = member.gid = 0
                        member.uname = member.gname = ""
                        archive.addfile(member, io.BytesIO(contents))
            destination.flush()
            os.fsync(destination.fileno())
        # Check the actual finished archive, not only the proposed file list.
        with tarfile.open(temporary, "r:gz") as archive:
            members = archive.getmembers()
            if [member.name for member in members] != [path.as_posix() for path in sources] or any(not member.isfile() for member in members):
                raise PackageError("生成压缩包的条目审核失败")
        reject_symlink_components(output)
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {"output": str(output), "file_count": len(sources), "archive_bytes": output.stat().st_size, "sha256": digest}


def main() -> None:
    parser = argparse.ArgumentParser(description="仅打包部署源码，不包含运行密钥、私人数据库、备份或输出。")
    parser.add_argument("--root", type=Path, default=Path(__file__).absolute().parent.parent, help="项目根目录（默认当前脚本所属项目）")
    parser.add_argument("--output", type=Path, help="输出包路径；相对路径从项目根目录计算（默认 dist/huhua-deploy.tar.gz）")
    parser.add_argument("--list-only", action="store_true", help="校验并列出允许的文件，不创建压缩包")
    args = parser.parse_args()
    root = absolute(args.root)
    output = args.output or Path("dist/huhua-deploy.tar.gz")
    if not output.is_absolute():
        output = root / output
    try:
        if args.list_only:
            sources = collect_sources(root)
            result = {"file_count": len(sources), "files": [path.as_posix() for path in sources]}
        else:
            result = build_archive(root, output)
    except (PackageError, OSError, tarfile.TarError) as error:
        parser.exit(2, f"打包失败：{error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
