"""
Skill installation — mirrors Go: ~/devspace/deepx-code/skill/install.go

- Install target always ~/.deepx/skills/<name>/
- Delete only allowed within ~/.deepx/skills (safe_name guard prevents traversal)
- No code execution: SKILL.md is plain text
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from deepx.skill.source import (
    SOURCE_ID_CLAWHUB,
    CLAWHUB_BASE,
    list_sources,
)

if TYPE_CHECKING:
    pass

# Security limits
MAX_INSTALL_BYTES = 10 * 1024 * 1024   # 10 MB
MAX_INSTALL_FILES = 256

# safe_name: alphanumeric + `_-.`, length 1-64
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")


def safe_name(name: str) -> bool:
    """Return True if name passes safe_name validation."""
    return bool(_SAFE_NAME_RE.match(name.strip()))


def installed_dir() -> str:
    """Return ~/.deepx/skills absolute path (may not exist)."""
    home = os.path.expanduser("~")
    return os.path.join(home, ".deepx", "skills")


def installed_list() -> list["Metadata"]:
    """
    List skills installed under ~/.deepx/skills/ (not global dirs).
    Imports Metadata from loader to avoid circular dep.
    """
    from deepx.skill.loader import Loader, Metadata
    dir_path = installed_dir()
    seen: dict[str, Metadata] = {}

    def scan(d: str) -> None:
        try:
            entries = os.scandir(d)
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir():
                continue
            skill_path = os.path.join(d, entry.name, "SKILL.md")
            from deepx.skill.loader import _parse_meta
            meta = _parse_meta(skill_path)
            if meta is None:
                continue
            if not meta.name:
                meta.name = entry.name
            meta.scope = "global"
            seen[meta.name] = meta

    scan(dir_path)
    result = list(seen.values())
    result.sort(key=lambda m: m.name)
    return result


def delete(name: str) -> None:
    """
    Delete ~/.deepx/skills/<name>/ directory.
    Raises error if name not safe, path outside ~/.deepx/skills, or not a managed skill.
    """
    name = name.strip()
    if not safe_name(name):
        raise ValueError(f"非法 skill 名 {name!r} (仅允许字母数字 . _ -)")

    root = installed_dir()
    target = os.path.join(root, name)

    # Double-check: Clean path must stay under root
    clean = os.path.normpath(target)
    if not clean.startswith(root + os.sep) and clean != root:
        raise ValueError(f"非法路径 (疑似越界): {clean}")

    skill_md = os.path.join(target, "SKILL.md")
    if not os.path.isfile(skill_md):
        raise ValueError(f"skill {name!r} 不在 ~/.deepx/skills/ 下，deepx 不管理它，无法删除")

    shutil.rmtree(target)


def install_from_source(source_id: str, remote_ref: str) -> str:
    """
    Install a skill from a remote source (currently only Clawhub).
    remote_ref is the Clawhub slug.
    Returns the installed skill name.
    """
    if not safe_name(remote_ref):
        raise ValueError(f"非法 skill ref {remote_ref!r} (仅允许字母数字 . _ -)")

    source = None
    for s in list_sources():
        if s.id == source_id and s.enabled:
            source = s
            break
    if not source:
        raise ValueError(f"未找到源 id={source_id}")

    root = installed_dir()
    os.makedirs(root, exist_ok=True)
    target = os.path.join(root, remote_ref)
    if os.path.isdir(target):
        raise FileExistsError(f"skill 目录已存在: {target} (请先 /skill-delete {remote_ref})")

    if source.type != "clawhub":
        raise ValueError(f"未知源类型: {source.type}")

    return _install_from_clawhub(source, remote_ref, root)


def _install_from_clawhub(source, remote_ref: str, root: str) -> str:
    """Download ZIP from Clawhub, extract safely, atomic-rename to target."""
    import time

    base = source.url or CLAWHUB_BASE
    target = os.path.join(root, remote_ref)
    pid = os.getpid()
    ts = int(time.time() * 1_000_000)
    staging = os.path.join(root, f".{remote_ref}.staging-{pid}-{ts}")

    def cleanup() -> None:
        shutil.rmtree(staging, ignore_errors=True)

    # Download
    dl_url = f"{base.rstrip('/')}/api/v1/download?slug={remote_ref}"
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(dl_url)
            resp.raise_for_status()
            raw_bytes = resp.content
    except Exception as e:
        raise RuntimeError(f"Clawhub 下载失败: {e}") from e

    # Check size before parsing
    if len(raw_bytes) > MAX_INSTALL_BYTES:
        raise RuntimeError(f"压缩包超过 {MAX_INSTALL_BYTES // 1024 // 1024}MB 上限 (疑似异常)")

    # Parse ZIP
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw_bytes))
    except zipfile.BadZipFile as e:
        raise RuntimeError(f"ZIP 解析失败: {e}") from e

    all_names = [n for n in zf.namelist() if not n.endswith("/")]

    # Find SKILL.md: at root or one level deep
    has_root = "SKILL.md" in all_names
    strip_prefix = ""
    if not has_root:
        nested = None
        for n in all_names:
            parts = n.split("/")
            if len(parts) == 2 and parts[1] == "SKILL.md":
                nested = n
                break
        if nested:
            strip_prefix = nested.split("/")[0] + "/"
        else:
            raise RuntimeError(f"Clawhub 包里没有 SKILL.md (包含: {all_names[:10]})")

    os.makedirs(staging, exist_ok=True)

    total_bytes = 0
    file_count = 0
    try:
        for zinfo in zf.infolist():
            name = zinfo.filename
            if strip_prefix and not name.startswith(strip_prefix):
                continue
            if strip_prefix:
                name = name[len(strip_prefix):]
            if not name or name.endswith("/"):
                continue
            # Security: reject .. and absolute paths
            if ".." in name or name.startswith("/"):
                raise RuntimeError(f"ZIP 含可疑路径: {zinfo.filename}")
            file_count += 1
            if file_count > MAX_INSTALL_FILES:
                raise RuntimeError(f"ZIP 文件数超 {MAX_INSTALL_FILES}")
            dst = os.path.join(staging, name)
            clean_dst = os.path.normpath(dst)
            if not clean_dst.startswith(staging + os.sep):
                raise RuntimeError(f"ZIP 路径越界: {zinfo.filename}")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            remaining = MAX_INSTALL_BYTES - total_bytes + 1
            with zf.open(zinfo) as src, open(dst, "wb") as out:
                wrote = io.copy(src, out, length=remaining)
            total_bytes += wrote
            if total_bytes > MAX_INSTALL_BYTES:
                raise RuntimeError(f"解压总大小超 {MAX_INSTALL_BYTES // 1024 // 1024}MB 上限")
    finally:
        zf.close()

    try:
        os.rename(staging, target)
    except OSError:
        cleanup()
        raise RuntimeError("rename staging → target 失败")

    return remote_ref


def install(src: str) -> str:
    """
    Install a skill from src.

    Supported src:
      - https://github.com/<owner>/<repo>  → git clone --depth 1
      - https://github.com/<owner>/<repo>/tree/<branch>/<subpath>  → clone + copy subpath
      - Local path: /abs, ./rel, ../rel, ~/...

    Returns the installed skill name.
    """
    src = src.strip()
    if not src:
        raise ValueError("source 不能为空")

    root = installed_dir()
    os.makedirs(root, exist_ok=True)

    if src.startswith("https://github.com/") or src.startswith("http://github.com/"):
        return _install_from_github(src, root)
    elif (
        src.startswith("/")
        or src.startswith("./")
        or src.startswith("../")
        or src.startswith("~")
    ):
        return _install_from_local(src, root)
    else:
        raise ValueError(
            f"无法识别 source (支持 https://github.com/... 或本地路径): {src}"
        )


def _parse_github_url(raw: str) -> tuple[str, str, str, str]:
    """
    Parse GitHub URL into (clone_url, branch, subpath, base_name).
    Supports:
      - https://github.com/<owner>/<repo>           → clone root, base_name=repo
      - https://github.com/<owner>/<repo>/tree/<branch>/<subpath>  → clone subpath
    """
    s = raw.rstrip("/")
    if s.lower().endswith(".git"):
        s = s[:-4]
    idx = s.lower().find("github.com/")
    if idx < 0:
        raise ValueError(f"不是合法 GitHub URL: {raw}")
    head = s[: idx + len("github.com/")]
    rest = s[idx + len("github.com/"):]
    parts = rest.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(f"不是合法 GitHub URL: {raw}")
    clone_url = head + parts[0] + "/" + parts[1]
    base_name = parts[1]
    branch = ""
    subpath = ""
    if len(parts) > 3 and parts[2] == "tree":
        branch = parts[3]
        if len(parts) > 4:
            subpath = "/".join(parts[4:])
            base_name = os.path.basename(subpath)
    elif len(parts) > 2 and parts[2] == "blob":
        raise ValueError("URL 指向文件而非目录，请改成 /tree/<branch>/<dir> 形式")
    return clone_url, branch, subpath, base_name


def _install_from_github(raw_url: str, root: str) -> str:
    """Clone from GitHub, install SKILL.md to ~/.deepx/skills/<name>/."""
    clone_url, branch, subpath, base_name = _parse_github_url(raw_url)

    if not safe_name(base_name):
        raise ValueError(f"从 URL 推出的目录名 {base_name!r} 不合法")

    target = os.path.join(root, base_name)
    if os.path.isdir(target):
        raise FileExistsError(f"skill 目录已存在: {target} (请先 /skill-delete {base_name})")

    import shutil as _sh
    git = _sh.which("git")
    if not git:
        raise RuntimeError("未找到 git 可执行文件，请先安装 (macOS: `brew install git`; Ubuntu: `sudo apt install git`)")

    if not subpath:
        # Single skill repo: clone directly to target
        cmd = ["git", "clone", "--depth", "1"]
        if branch:
            cmd += ["--branch", branch]
        cmd += [clone_url, target]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            import shutil as _sh2
            _sh2.rmtree(target, ignore_errors=True)
            raise RuntimeError(f"git clone 失败: {e.stderr.decode() if e.stderr else str(e)}") from e

        if not os.path.isfile(os.path.join(target, "SKILL.md")):
            _sh2.rmtree(target, ignore_errors=True)
            raise ValueError(
                "仓库根目录没有 SKILL.md。如果是多 skill 仓库 (例 anthropics/skills)，"
                "请改 URL 指定子目录: .../tree/<branch>/<skill-dir>"
            )
        return base_name

    # Multi-skill repo: clone to temp → validate subpath → copy to target
    staging = None
    try:
        import tempfile
        staging = tempfile.mkdtemp(prefix="deepx-clone-")
        clone_dir = os.path.join(staging, "repo")
        cmd = ["git", "clone", "--depth", "1"]
        if branch:
            cmd += ["--branch", branch]
        cmd += [clone_url, clone_dir]
        subprocess.run(cmd, check=True, capture_output=True)

        skill_dir = os.path.normpath(os.path.join(clone_dir, subpath.replace("/", os.sep)))
        if not skill_dir.startswith(os.path.normpath(clone_dir) + os.sep):
            raise ValueError(f"子路径越界: {subpath}")

        if not os.path.isfile(os.path.join(skill_dir, "SKILL.md")):
            raise ValueError(f"仓库子路径 {subpath!r} 下没有 SKILL.md")

        os.makedirs(target, exist_ok=True)
        for item in os.listdir(skill_dir):
            src_item = os.path.join(skill_dir, item)
            dst_item = os.path.join(target, item)
            if os.path.isdir(src_item):
                shutil.copytree(src_item, dst_item)
            else:
                shutil.copy2(src_item, dst_item)
        return base_name
    finally:
        if staging:
            import shutil as _sh3
            _sh3.rmtree(staging, ignore_errors=True)


def _install_from_local(raw_src: str, root: str) -> str:
    """Copy a local directory (must contain SKILL.md) to ~/.deepx/skills/<name>/."""
    src = raw_src
    if src.startswith("~"):
        home = os.path.expanduser("~")
        src = os.path.join(home, src[1:])

    abs_path = os.path.abspath(src)
    try:
        st = os.stat(abs_path)
    except OSError:
        raise ValueError(f"路径不存在或不可访问: {abs_path}") from None

    if not st.is_dir():
        raise ValueError(f"只支持目录拷贝 (目录里要含 SKILL.md): {abs_path}")

    if not os.path.isfile(os.path.join(abs_path, "SKILL.md")):
        raise ValueError(f"源目录里没有 SKILL.md: {abs_path}")

    name = os.path.basename(abs_path)
    if not safe_name(name):
        raise ValueError(f"目录名 {name!r} 不合法 (仅允许字母数字 . _ -)")

    target = os.path.join(root, name)
    if os.path.isdir(target):
        raise FileExistsError(f"skill 目录已存在: {target} (请先 /skill-delete {name})")

    shutil.copytree(abs_path, target)
    return name