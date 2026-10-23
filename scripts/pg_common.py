"""Shared PostgreSQL connection settings; secrets are read only from the environment."""
import os
from pathlib import Path
import psycopg2

ROOT = Path(__file__).resolve().parents[1]


def connect():
    connection = psycopg2.connect(host=os.environ.get('DLP_DB_HOST','127.0.0.1'),
        port=int(os.environ.get('DLP_DB_PORT','5432')), dbname=os.environ.get('DLP_DB_NAME','dlpcenter'),
        user=os.environ.get('DLP_DB_USER','dlpcenter'), password=os.environ.get('DLP_DB_PASSWORD',''),
        connect_timeout=10, options='-c timezone=Asia/Shanghai')
    return connection


def schema(cursor):
    cursor.execute((ROOT/'dlpcenter'/'sql'/'init.sql').read_text())


def file_root():
    return Path(os.environ.get('DLP_FILE_ROOT', 'data/files' if os.name == 'nt' else '/var/lib/sentinel-dlp/files'))
