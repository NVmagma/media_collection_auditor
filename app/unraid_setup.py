"""Protected first-run setup for a template with only appdata/media mounts."""
import hmac
import os
from pathlib import Path
import secrets
import stat
import threading
import fcntl
from werkzeug.security import check_password_hash, generate_password_hash
from config_store import CONFIG_FILE, save_config

_LOCK = threading.Lock()
ACCOUNT = '_local_admin'


def _document():
    from app.json_worker_service import read_saved_settings
    return read_saved_settings()


def _token_path():
    return CONFIG_FILE.parent / 'setup-token'


def _token():
    path = _token_path()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 256:
            raise ValueError('Invalid setup token')
        return os.read(fd, 257).decode().strip()
    finally:
        os.close(fd)


def setup_pending():
    try:
        return ACCOUNT not in _document() and bool(_token())
    except (OSError, ValueError):
        return False


def prepare_installation():
    """Initialize only an empty mounted appdata directory; never repair missing state."""
    root = CONFIG_FILE.parent
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError('Mount a writable appdata directory at /app/logs')
    from app.filesystem_paths import _open_directory
    directory = _open_directory(str(root))
    try:
        fcntl.flock(directory, fcntl.LOCK_EX)
        if not os.listdir(directory):
            from app.json_initialize import initialize
            initialize(root)
            token = secrets.token_urlsafe(32)
            fd = os.open(_token_path(), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as handle:
                handle.write(token + '\n'); handle.flush(); os.fsync(handle.fileno())
            os.fsync(directory)
    finally:
        os.close(directory)
    if setup_pending():
        print('[SETUP] Open the WebUI and enter this one-time setup code: ' + _token(), flush=True)


def _validated_account(username, password):
    username = username.strip()
    if not username or len(username) > 128 or any(ord(c) < 32 for c in username):
        raise ValueError('Enter a username of 1–128 characters')
    if not 12 <= len(password) <= 256:
        raise ValueError('Use a password of 12–256 characters')
    return {'username': username, 'password_hash': generate_password_hash(password),
            'version': secrets.token_hex(16)}


def complete_setup(code, username, password):
    with _LOCK:
        saved = _document()
        if ACCOUNT in saved or not hmac.compare_digest(code, _token()):
            raise ValueError('Invalid or already used setup code')
        saved[ACCOUNT] = _validated_account(username, password)
        # Fresh installs always remain in preview until explicitly configured.
        saved.update(DRY_RUN='true', ALLOW_PERMANENT_DELETE='false',
                     ALLOW_TV_SEASON_DELETE='false', ORPHAN_CLEANUP_ENABLED='false')
        save_config(saved)
        _token_path().unlink()


def authenticate(username, password):
    try:
        saved = _document()
    except ValueError:
        return False
    if ACCOUNT in saved:
        account = saved[ACCOUNT]
        try:
            return (isinstance(account, dict) and isinstance(account.get('password_hash'), str)
                    and hmac.compare_digest(username, account.get('username', ''))
                    and check_password_hash(account['password_hash'], password))
        except (ValueError, TypeError): return False
    # Existing installations can sign in once using their original template login.
    return bool(os.environ.get('WEB_ADMIN_PASSWORD') and
                hmac.compare_digest(username, os.environ.get('WEB_ADMIN_USER', 'admin')) and
                hmac.compare_digest(password, os.environ['WEB_ADMIN_PASSWORD']))


def account_version():
    try:
        saved = _document()
        if ACCOUNT not in saved: return None
        account = saved[ACCOUNT]
        return account.get('version', 'invalid') if isinstance(account, dict) else 'invalid'
    except ValueError:
        return 'invalid'


def change_account(username, password):
    with _LOCK:
        saved = _document()
        saved[ACCOUNT] = _validated_account(username, password)
        save_config(saved)
