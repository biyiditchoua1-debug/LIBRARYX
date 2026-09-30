#!/bin/sh
set -eu

APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$APP_DIR"
export SQLITE_PATH=${SQLITE_PATH:-"$APP_DIR/db.sqlite3"}

python - "$APP_DIR/db.sqlite3" "$SQLITE_PATH" <<'PY'
import fcntl
import os
import shutil
import sys
import tempfile
from pathlib import Path

source = Path(os.path.abspath(os.path.expanduser(sys.argv[1])))
target = Path(os.path.abspath(os.path.expanduser(sys.argv[2])))
target.parent.mkdir(parents=True, exist_ok=True)

if source != target:
    lock_path = target.with_name(target.name + '.seed.lock')
    with lock_path.open('a+b') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if not target.exists() or target.stat().st_size == 0:
            if not source.is_file():
                raise SystemExit(f'Bundled SQLite seed database is missing: {source}')
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=f'.{target.name}.', suffix='.seed', dir=target.parent
            )
            os.close(file_descriptor)
            try:
                shutil.copyfile(source, temporary_name)
                os.chmod(temporary_name, 0o600)
                os.replace(temporary_name, target)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
PY

python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec gunicorn libraryx.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 2 --timeout 120
