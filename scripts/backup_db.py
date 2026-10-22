"""Create and check a consistent SQLite backup, including uploaded watermark images."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import sqlite3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    database = args.database.resolve(strict=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    name = 'sentinel-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.db'
    target = args.output_dir / name
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as source:
            with sqlite3.connect(target) as backup:
                source.backup(backup)
                if backup.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Backup failed SQLite integrity check')
    except Exception:
        target.unlink(missing_ok=True)
        raise
    print(target.resolve())


if __name__ == '__main__':
    main()
