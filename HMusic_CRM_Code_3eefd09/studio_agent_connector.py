"""Read-only H-Music adapter. No CRM import, migrations, or writes on startup.

Production: register_blueprint(app, lambda: sqlite3.connect('hmusic.db'), using_postgres).
Local: python3 connector/studio_connector.py --db '/absolute/path/hmusic.db'
"""
import argparse
import hmac
import json
import os
import sqlite3
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

FIELDS = {
    'schedule': ['id','student_name','teacher','lesson_date','lesson_time','duration','classroom','location','location_id','room_id','status','course_type_name','group_student_names','is_group'],
    'students': ['id','name','teacher','program','status','lessons_left'],
    'inquiries': ['id','student_name','parent_name','instrument','status','trial_date','trial_time','trial_teacher','next_follow_up_at','follow_up_status','converted_student_name'],
    'teacher_open_slots': ['id','teacher','slot_date','slot_time','classroom','source','active'],
    'reschedule_requests': ['id','student_name','status','requested_date','requested_time','original_schedule_id'],
    'teacher_time_off_requests': ['id','teacher_name','start_date','end_date','start_time','end_time','all_day','status'],
}
LIMIT = 20000

def validate_range(start, end):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    if a.isoformat()!=start or b.isoformat()!=end or b<a or (b-a).days>60:
        raise ValueError('Invalid date range; maximum 61 days.')

def columns(conn, table, postgres=False):
    if postgres:
        rows=conn.execute('SELECT column_name FROM information_schema.columns WHERE table_schema = ? AND table_name = ?', ('public',table)).fetchall()
        return {r[0] for r in rows}
    return {r[1] for r in conn.execute('PRAGMA table_info('+table+')').fetchall()}

def serialize(value):
    if isinstance(value,(datetime,date)): return value.isoformat()
    return value

def read_snapshot(connect, start, end, *, postgres=False, source='crm', label='H-Music CRM'):
    validate_range(start,end)
    conn=connect()
    warnings=[]
    try:
        # A consistent, explicitly read-only transaction; never invokes the CRM schema initializers.
        if postgres: conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        else:
            conn.execute('PRAGMA query_only = ON')
            conn.execute('BEGIN')
        result={}
        for table, requested in FIELDS.items():
            available=columns(conn,table,postgres)
            if not available:
                result[table]=[];warnings.append('Missing table: '+table);continue
            selected=[f for f in requested if f in available]
            if not selected:
                result[table]=[];warnings.append('Missing supported columns: '+table);continue
            params=[];where=''
            date_column={'schedule':'lesson_date','teacher_open_slots':'slot_date'}.get(table)
            if date_column:
                if date_column not in available: raise ValueError('Missing date column: '+table)
                where=f' WHERE {date_column} >= ? AND {date_column} <= ?';params=[start,end]
            sql='SELECT '+', '.join(selected)+' FROM '+table+where+' LIMIT '+str(LIMIT+1)
            rows=conn.execute(sql,params).fetchall()
            if len(rows)>LIMIT: raise ValueError('Snapshot too large; narrow date range or add pagination.')
            result[table]=[{k:serialize(v) for k,v in zip(selected,row)} for row in rows]
            missing=set(requested)-available
            if missing: warnings.append(table+': unavailable fields '+', '.join(sorted(missing)))
        return {'source':source,'source_label':label,'timezone':'America/Los_Angeles','fetched_at':datetime.now(timezone.utc).isoformat(),'range':{'start':start,'end':end},'warnings':warnings,'truncated':False,'capabilities':{'write':False},'lessons':result['schedule'],'students':result['students'],'inquiries':result['inquiries'],'open_slots':result['teacher_open_slots'],'reschedules':result['reschedule_requests'],'time_off':result['teacher_time_off_requests']}
    finally:
        conn.close()

def authorized(header, token):
    return len(token)>=32 and hmac.compare_digest(header,'Bearer '+token)

def register_blueprint(app, connect, using_postgres=lambda:False):
    """Install only after the CRM app has been created, before serving requests."""
    from flask import Blueprint, request, jsonify
    bp=Blueprint('studio_agent_readonly',__name__)
    @bp.get('/api/studio-agent/v1/snapshot')
    def snapshot():
        token=os.environ.get('HMUSIC_AGENT_READ_TOKEN','')
        if len(token)<32: return jsonify(error='Connector not configured'),503
        if not authorized(request.headers.get('Authorization',''),token): return jsonify(error='Unauthorized'),401
        try:
            data=read_snapshot(connect,request.args.get('start',''),request.args.get('end',''),postgres=using_postgres())
            response=jsonify(data)
            response.headers['Cache-Control']='private, no-store'
            response.headers['X-Content-Type-Options']='nosniff'
            return response
        except ValueError as exc: return jsonify(error=str(exc)),400
        except Exception:
            app.logger.exception('Studio Agent snapshot failed')
            return jsonify(error='Snapshot unavailable'),503
    app.register_blueprint(bp)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',required=True)
    parser.add_argument('--port',type=int,default=8788)
    args=parser.parse_args()
    db=Path(args.db).expanduser().resolve()
    if not db.is_file(): parser.error('Database file does not exist.')
    token=os.environ.get('HMUSIC_AGENT_READ_TOKEN','')
    if len(token)<32: parser.error('Set HMUSIC_AGENT_READ_TOKEN to at least 32 characters.')
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url=urlsplit(self.path)
            if url.path!='/api/studio-agent/v1/snapshot': self.respond(404,{'error':'Not found'});return
            if not authorized(self.headers.get('Authorization',''),token): self.respond(401,{'error':'Unauthorized'});return
            try:
                q=parse_qs(url.query)
                data=read_snapshot(lambda:sqlite3.connect(db.as_uri()+'?mode=ro',uri=True),q.get('start',[''])[0],q.get('end',[''])[0],source='local_snapshot',label='本机 CRM 数据库 · 非线上实时数据')
                data['database_file_modified_at']=datetime.fromtimestamp(db.stat().st_mtime,timezone.utc).isoformat()
                self.respond(200,data)
            except ValueError as exc: self.respond(400,{'error':str(exc)})
            except Exception: self.respond(503,{'error':'Snapshot unavailable'})
        def respond(self,status,data):
            body=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args): pass
    print(f'Read-only connector: http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()

if __name__=='__main__': main()
