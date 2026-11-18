"""Owner-only additive group roster changes using the established roster writer."""
from flask import abort, request


def register_owner_group_roster(app, api):
    @app.post('/api/calendar-group-roster/<int:sid>/add')
    def owner_group_add_student(sid):
        if not api['require_owner']():
            abort(403)
        data=request.get_json(silent=True) or {}
        scope=data.get('scope','once')
        if scope not in ('once','following'):
            return dict(ok=False,error='Choose this lesson or this and following lessons.'),400
        name=api['hmusic_clean_student_picker_value'](data.get('student_name') or '')
        if not name:
            return dict(ok=False,error='Choose an existing student.'),400
        api['ensure_calendar_lesson_panel_schema']()
        conn=api['sqlite3'].connect('hmusic.db')
        try:
            cur=conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            row=api['calendar_lesson_row'](cur,sid)
            if not row:
                abort(404)
            if not int(row[18] or 0):
                return dict(ok=False,error='This is not a group lesson.'),400
            cur.execute('SELECT name FROM students WHERE LOWER(TRIM(name))=LOWER(TRIM(?))',(name,))
            matches=cur.fetchall()
            if len(matches)!=1:
                return dict(ok=False,error='Choose one existing student from the search results.'),400
            name=matches[0][0]
            ids=[sid]
            if scope=='following':
                if str(row[28] or '').strip():
                    # Group membership may differ by date; use the class identity, not its first student.
                    cur.execute('''SELECT id FROM schedule WHERE is_group=1
                        AND COALESCE(group_name,'')=? AND COALESCE(teacher,'')=?
                        AND COALESCE(lesson_time,'')=? AND COALESCE(classroom,'')=?
                        AND COALESCE(course_type_name,'')=? AND COALESCE(schedule_type,'')=?
                        AND COALESCE(package_type,'')=? AND COALESCE(duration,30)=?
                        AND COALESCE(location,'')=? AND lesson_date>=? AND id!=?''',
                        (row[28],row[2] or '',row[4] or '',row[5] or '',row[7] or '',row[8] or '',row[9] or '',int(row[10] or 30),row[27] or '',row[3],sid))
                    ids += [r[0] for r in cur.fetchall()]
                else:
                    ids += api['calendar_following_lesson_ids'](cur,row,sid)
            ids=sorted(set(ids))
            # Lock in a stable order before rereading individual rosters.
            for target in ids:
                cur.execute('UPDATE schedule SET owner_calendar_updated_at=owner_calendar_updated_at WHERE id=?',(target,))
            updated=0
            for target in ids:
                target_row=api['calendar_lesson_row'](cur,target)
                if not target_row or not int(target_row[18] or 0):
                    continue
                # A similarly scheduled class with a different name is not this class.
                if str(target_row[28] or '').strip()!=str(row[28] or '').strip():
                    continue
                roster=api['calendar_group_roster'](cur,target,target_row)
                if any(str(item.get('student_name') or '').strip().casefold()==name.strip().casefold() for item in roster):
                    continue
                if len(roster)>=50:
                    raise ValueError('This lesson already has 50 students. Review its roster first.')
                api['sync_calendar_group_roster'](cur,[target],roster+[dict(student_name=name,attendance_status='scheduled')],attendance_schedule_id=target,apply_existing_attendance=False,minimum_students=1)
                updated+=1
            conn.commit()
            return dict(ok=True,student_name=name,updated=updated,message=f'{name} added to {updated} lesson(s).' if updated else f'{name} is already on the selected lesson roster(s).')
        except ValueError as exc:
            conn.rollback()
            return dict(ok=False,error=str(exc)),400
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
