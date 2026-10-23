"""Move legacy endpoints into a typed table and backfill stable UUID foreign keys.
Run while the application is stopped. Safe to repeat; no business rows are discarded.
"""
from collections import Counter
from psycopg2.extras import Json
from pg_common import ROOT, connect

FIELDS = {'id','endpointUid','name','user','department','ip','os','status','risk','version','policy','lastSeen','isolated'}


def migrate(cursor):
    cursor.execute('SELECT pg_advisory_xact_lock(728112)')
    cursor.execute((ROOT/'dlpcenter/sql/endpoints.sql').read_text())
    cursor.execute("SELECT id,data FROM dlp_records WHERE kind='endpoints' ORDER BY seq FOR UPDATE")
    legacy = cursor.fetchall()
    for code, item in legacy:
        if item.get('id') != code:
            raise ValueError('Endpoint code differs from legacy record ID: '+code)
        cursor.execute('SELECT 1 FROM endpoints WHERE endpoint_code=%s', (code,))
        if cursor.fetchone():
            raise ValueError('Conflicting endpoint code; migration rolled back: '+code)
        cursor.execute('''INSERT INTO endpoints(endpoint_code,name,username,department,ip_address,os,status,risk,
                          agent_version,policy,last_seen,isolated,extra)
                          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                       (code,item.get('name',''),item.get('user',''),item.get('department',''),item.get('ip',''),
                        item.get('os',''),item.get('status','offline'),item.get('risk','low'),item.get('version',''),
                        item.get('policy',''),item.get('lastSeen',''),item.get('isolated',False),
                        Json({k:v for k,v in item.items() if k not in FIELDS})))
    cursor.execute("DELETE FROM dlp_records WHERE kind='endpoints'")
    cursor.execute('SELECT endpoint_uid::text,endpoint_code,name,ip_address FROM endpoints')
    devices = cursor.fetchall()
    codes = {code:uid for uid,code,_,_ in devices}
    cursor.execute("SELECT kind,id,data FROM dlp_records WHERE kind IN ('events','assets','approvals','watermarkImages') AND endpoint_uid IS NULL FOR UPDATE")
    linked = Counter(); unresolved = Counter()
    for kind, ident, item in cursor.fetchall():
        uid = item.get('endpointUid')
        code = item.get('endpointId')
        name, ip = item.get('endpoint',''), item.get('ip','')
        if uid:
            if uid not in codes.values():raise ValueError('Unknown endpointUid: '+ident)
        elif code:
            uid = codes.get(code)
            if not uid:raise ValueError('Unknown legacy endpointId: '+ident)
        elif name or ip:
            # Both pieces of evidence must agree; ambiguous/shared names/IPs stay unbound.
            matches = [u for u,_,n,p in devices if (not name or n==name) and (not ip or p==ip)]
            if len(matches)==1:uid=matches[0]
        if uid:
            item['endpointUid'] = uid
            cursor.execute('UPDATE dlp_records SET endpoint_uid=%s,data=%s WHERE kind=%s AND id=%s', (uid,Json(item),kind,ident))
            linked[kind] += 1
        elif name or ip or code:
            unresolved[kind] += 1
    cursor.execute('DROP TRIGGER IF EXISTS record_endpoint_sync ON dlp_records')
    cursor.execute('''CREATE TRIGGER record_endpoint_sync BEFORE INSERT OR UPDATE ON dlp_records
                      FOR EACH ROW EXECUTE FUNCTION sync_record_endpoint()''')
    cursor.execute("INSERT INTO dlp_migrations(name) VALUES('endpoints-uuid-v1') ON CONFLICT DO NOTHING")
    print(f'Endpoint migration: moved={len(legacy)}, linked={dict(linked)}, unmatched={dict(unresolved)}')


def main():
    with connect() as db, db.cursor() as cursor:
        migrate(cursor)


if __name__ == '__main__':main()
