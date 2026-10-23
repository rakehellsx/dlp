"""Update titles and notes of built-in watermark samples without changing user uploads."""
from pg_common import connect
from psycopg2.extras import Json


def main():
    changed = 0
    with connect() as db, db.cursor() as cursor:
        cursor.execute("SELECT id,data FROM dlp_records WHERE kind='watermarkImages' "
                       "AND (strpos(data->>'filename','watermark-demo-v1-')=1 "
                       "OR strpos(data->>'note','[watermark-demo-v1]')=1) FOR UPDATE")
        for ident, item in cursor.fetchall():
            title, note = item.get('title', ''), item.get('note', '')
            clean_title = title.removeprefix('[演示] ')
            clean_note = note.removeprefix('[watermark-demo-v1] ').replace('演示已核验', '已核验').replace('演示待核验', '待核验')
            if (title, note) == (clean_title, clean_note):
                continue
            item['title'], item['note'] = clean_title, clean_note
            cursor.execute("UPDATE dlp_records SET data=%s WHERE kind='watermarkImages' AND id=%s", (Json(item), ident))
            changed += 1
    print(f'Updated built-in watermark titles/notes: {changed}')


if __name__ == '__main__':
    main()
