"""One local GCP deployment or address operation at a time."""
from contextlib import contextmanager
import fcntl
from pathlib import Path
import subprocess
import sys


@contextmanager
def profile_lock(state):
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = state / '.operation.lock'
    if path.is_symlink():
        raise ValueError('profile 锁不能是符号链接')
    with path.open('a') as handle:
        path.chmod(0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('该 profile 正在部署或更换 IP，请等待操作结束') from None
        yield


if __name__ == '__main__':
    try:
        with profile_lock(sys.argv[1]):
            sys.exit(subprocess.call(sys.argv[2:]))
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
