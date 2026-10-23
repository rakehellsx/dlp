"""Create a PostgreSQL custom-format backup, including BYTEA watermark images."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    path=args.output_dir/('dlpcenter-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.dump')
    env=dict(os.environ)
    for key,default in [('HOST','127.0.0.1'),('PORT','5432'),('NAME','dlpcenter'),('USER','dlpcenter'),('PASSWORD','')]:
        env['PGDATABASE' if key=='NAME' else 'PG'+key]=os.environ.get('DLP_DB_'+key,default)
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,'wb') as output:subprocess.run(['pg_dump','--format=custom','--no-owner','--no-acl'],env=env,stdout=output,check=True)
        subprocess.run(['pg_restore','--list',str(path)],stdout=subprocess.DEVNULL,check=True)
    except Exception:
        path.unlink(missing_ok=True);raise
    print(path.resolve())


if __name__=='__main__':main()
