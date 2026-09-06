"""Write client files with exact profile ownership; never glob-delete YAML."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile


def atomic_write(path, text):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_outputs(directory, profile, rendered, *, check=False):
    directory = Path(directory)
    if check:
        if directory.is_symlink():
            return False
        manifest = directory / ".network-node-outputs.json"
        if manifest.is_symlink():
            return False
        if manifest.exists():
            owners = json.loads(manifest.read_text())
            if not isinstance(owners, dict):
                raise ValueError("输出归属清单格式错误")
            if profile in owners and set(owners[profile]) != {path.name for path in rendered}:
                return False
        return all(path.is_file() and not path.is_symlink() and path.read_text() == text
                   for path, text in rendered.items())
    if directory.is_symlink():
        raise ValueError("客户端输出目录不能是符号链接")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    manifest_path = directory / ".network-node-outputs.json"
    lock_path = directory / ".network-node-outputs.lock"
    if manifest_path.is_symlink() or lock_path.is_symlink():
        raise ValueError("输出归属清单/锁不能是符号链接")
    with lock_path.open("a") as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        owners = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        if not isinstance(owners, dict):
            raise ValueError("输出归属清单格式错误")
        for owner, files in owners.items():
            if not isinstance(files, dict) or any(Path(name).name != name or not name.endswith(".yaml") for name in files):
                raise ValueError("输出归属清单包含无效文件名")
            if owner != profile and any(path.name in files for path in rendered):
                raise ValueError("客户端文件名属于另一个 profile，请使用独立 CLIENT_FILE_PREFIX")
        for path in rendered:
            if path.is_symlink():
                raise ValueError("客户端文件不能是符号链接")
            if path.exists():
                header = next((line for line in path.read_text().splitlines()[:5] if line.startswith("# Profile: ")), None)
                if header and header != f"# Profile: {profile}":
                    raise ValueError("客户端文件属于另一个 profile")
        previous = owners.get(profile, {})
        # Stage all files before publishing any of them. Legacy files not recorded in
        # the manifest are deliberately left alone: their ownership is ambiguous.
        staged = []
        try:
            for path, text in rendered.items():
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as handle:
                    tmp = Path(handle.name)
                    staged.append((tmp, path))
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                tmp.chmod(0o600)
            for temporary, path in staged:
                temporary.replace(path)
            owners[profile] = {path.name: hashlib.sha256(text.encode()).hexdigest() for path, text in rendered.items()}
            atomic_write(manifest_path, json.dumps(owners, indent=2, ensure_ascii=False) + "\n")
            for name, digest in previous.items():
                path = directory / name
                if path not in rendered and path.is_file() and not path.is_symlink():
                    # Preserve files edited manually since our last generation.
                    if hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                        path.unlink()
        finally:
            for temporary, _ in staged:
                temporary.unlink(missing_ok=True)
    return True
