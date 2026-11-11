"""Read-only family segmentation and explicit recipient selection."""
import calendar
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

PAUSED={'inactive','paused','withdrawn','withdrawal','stopped','archived','deleted','停课','退学'}
PRESENT={'present','completed','attended'}
FUTURE={'scheduled','makeup','confirmed'}

def records(conn, table):
    fields={'students':['name','status','active'], 'parent_profiles':['id','parent_name','email','active'],
        'parent_students':['parent_id','student_name','active'], 'schedule':['id','student_name','lesson_date','status','teacher','course_type_name','group_name'],
        'group_schedule_students':['id','schedule_id','student_name','attendance_status']}
    available={c[0] for c in conn.execute('SELECT * FROM '+table+' LIMIT 0').description}
    names=[name for name in fields[table] if name in available]
    cur=conn.execute('SELECT '+','.join(names)+' FROM '+table)
    return [dict(zip(names,row)) for row in cur.fetchall()]

def parse_date(value):
    try:return date.fromisoformat(str(value)[:10])
    except (ValueError,TypeError):return None

def family_catalog(conn, today=None, email_check=None):
    today=today or datetime.now(ZoneInfo('America/Los_Angeles')).date()
    month=today.year*12+today.month-1-4
    year,m=divmod(month,12);m+=1
    cutoff=date(year,m,min(today.day,calendar.monthrange(year,m)[1]))
    students={str(s['name']).strip().casefold():s for s in records(conn,'students')}
    lessons=defaultdict(list)
    group=defaultdict(list)
    for g in records(conn,'group_schedule_students'):
        group[g['schedule_id']].append(g)
    for s in records(conn,'schedule'):
        members=group.get(s.get('id'))
        if members:
            for g in members:
                item=dict(s);item['status']=g.get('attendance_status') or s.get('status');item['parent_status']=s.get('status')
                lessons[str(g['student_name']).strip().casefold()].append(item)
        else:
            lessons[str(s.get('student_name') or '').strip().casefold()].append(s)
    links=defaultdict(set)
    for link in records(conn,'parent_students'):
        if link.get('active',1):links[link['parent_id']].add(str(link['student_name']).strip().casefold())
    families=[]
    for parent in records(conn,'parent_profiles'):
        if not parent.get('active',1):continue
        children=[];teachers=set();courses=set();last=None;upcoming=None
        for key in sorted(links[parent['id']]):
            student=students.get(key)
            name=student['name'] if student else key
            history=lessons[key]
            attended=sorted(d for l in history if (d:=parse_date(l.get('lesson_date'))) and d<=today and str(l.get('status') or '').lower() in PRESENT)
            future=[l for l in history if (d:=parse_date(l.get('lesson_date'))) and d>=today and str(l.get('status') or 'scheduled').lower() in FUTURE and str(l.get('parent_status') or l.get('status') or 'scheduled').lower() in FUTURE]
            last_child=attended[-1] if attended else None
            next_child=min((parse_date(l['lesson_date']) for l in future),default=None)
            paused=student and (str(student.get('status') or '').strip().lower() in PAUSED or str(student.get('active',1)).lower() in ('0','false'))
            if paused:category='past';reason='Marked paused / inactive'
            elif next_child:category='current';reason='Upcoming lesson'
            elif last_child and last_child>=cutoff:category='current';reason='Attended within 4 months'
            elif last_child:category='past';reason='No attendance in 4 months; no upcoming lesson'
            else:category='review';reason='No confirmed attendance or upcoming lesson'
            if category=='current':
                for l in future:
                    if l.get('teacher'):teachers.add(l['teacher'])
                    if l.get('course_type_name'):courses.add(l['course_type_name'])
                    if l.get('group_name'):courses.add('Class: '+str(l['group_name']))
            children.append(dict(name=name,category=category,reason=reason,last=str(last_child or ''),next=str(next_child or '')))
            if last_child:last=max(last,last_child) if last else last_child
            if next_child:upcoming=min(upcoming,next_child) if upcoming else next_child
        categories={c['category'] for c in children}
        category='current' if 'current' in categories else 'review' if not children or 'review' in categories else 'past'
        email=str(parent.get('email') or '').strip()
        eligible=bool(email_check(email)) if email_check else bool('@' in email and not email.lower().endswith(('.invalid','@example.com')))
        families.append(dict(id=parent['id'],name=parent.get('parent_name') or 'Family',students=[c['name'] for c in children],
            category=category,children=children,last=str(last or ''),next=str(upcoming or ''),teachers=sorted(teachers),courses=sorted(courses),email_ok=eligible))
    return sorted(families,key=lambda f:(f['name'].casefold(),f['id']))

def rule_from_form(form):
    mode=form.get('audience','selected')
    if mode not in ('current','past','review','selected','teacher','course'):
        raise ValueError('Choose a valid family audience.')
    def ids(name):
        values=form.getlist(name)
        if any(not str(x).isdigit() for x in values):raise ValueError('Invalid family selection.')
        return sorted({int(x) for x in values})
    return dict(mode=mode,selected=ids('parent_ids'),exclude=ids('exclude_ids'),
        teachers=form.getlist('audience_teachers'),courses=form.getlist('audience_courses'))

def select_ids(catalog,rule):
    result=[]
    for f in catalog:
        mode=rule['mode']
        match=(f['category']==mode if mode in ('current','past','review') else
            f['id'] in rule['selected'] if mode=='selected' else
            bool(set(f['teachers'])&set(rule['teachers'])) if mode=='teacher' else
            bool(set(f['courses'])&set(rule['courses'])))
        if match and f['id'] not in rule['exclude']:result.append(f['id'])
    return sorted(set(result))

def render_controls(catalog,rule=None,message=True,email=False):
    import json
    from html import escape
    rule=rule or dict(mode='selected',selected=[],exclude=[],teachers=[],courses=[])
    payload=json.dumps(dict(families=catalog,rule=rule),ensure_ascii=False).replace('<','\\u003c').replace('&','\\u0026')
    scopes=[('current','Current families','Recent attendance or upcoming lessons'),('past','Inactive / past families','Paused or no attendance in 4 months'),('review','Needs review','Incomplete history; review before selecting'),('selected','Selected families','Search and choose individual families'),('teacher','By teacher','Current families with upcoming lessons'),('course','By course / class','Current families with upcoming lessons')]
    scopes=[(key,label+(f' ({sum(f["category"]==key for f in catalog)})' if key in ('current','past','review') else ''),hint) for key,label,hint in scopes]
    cards=''.join(f'<label class="scope-card"><input type="radio" name="audience" value="{key}" {"checked" if rule["mode"]==key else ""}><span><strong>{label}</strong><small>{hint}</small></span></label>' for key,label,hint in scopes)
    def options(key,name):
        values=sorted({v for f in catalog for v in f[key]})
        return ''.join(f'<label class="filter-item"><input type="checkbox" name="{name}" value="{escape(v,quote=True)}" {"checked" if v in rule[key] else ""}> {escape(v)}</label>' for v in values)
    return f'''<section class="recipient-delivery" data-audience-widget>
    <h2>Recipients &amp; delivery</h2><h3>1. Who should receive this?</h3>
    <p class="muted">Current means at least one child attended within 4 calendar months or has an upcoming lesson. Paused children are excluded from current families. Missing history needs review.</p>
    <div class="audience-layout"><div class="scope-options">{cards}</div><div class="audience-picker">
    <div data-teacher-panel hidden><strong>Choose teachers</strong><div class="filter-options">{options('teachers','audience_teachers')}</div></div>
    <div data-course-panel hidden><strong>Choose courses / classes</strong><div class="filter-options">{options('courses','audience_courses')}</div></div>
    <label>Search parent or student<input type="search" data-family-search placeholder="Search parent or student name"></label>
    <div class="family-list" data-family-list></div>
    <details><summary>Exclude families</summary><label>Search exclusions<input type="search" data-exclude-search placeholder="Search families to exclude"></label><div class="family-list exclusions" data-exclude-list></div></details>
    <p role="status" data-recipient-summary></p><details><summary>View recipient list &amp; reasons</summary><div class="family-list" data-recipient-list></div></details>
    <p class="muted">Each family receives a private copy. Siblings share one family selection. Family accounts without login access are excluded.</p>
    </div></div><hr><h3>2. How should we send it?</h3><input type="hidden" name="channel_format" value="checkbox-v1">
    <div class="channel-options"><label class="channel-card"><input type="checkbox" name="channels" value="message" {"checked" if message else ""}><span><strong>Message</strong><small>App inbox notification</small></span></label>
    <label class="channel-card"><input type="checkbox" name="channels" value="email" {"checked" if email else ""}><span><strong>Email</strong><small>Parent email address</small></span></label></div>
    <p class="muted">Select one or both. Every send keeps an App history record. Email uses your title and uploaded images / PDFs.</p>
    <div class="delivery-summary" data-delivery-summary role="status"></div>
    <p class="audience-error" data-audience-error role="alert"></p>
    <script type="application/json" data-audience-data>{payload}</script><script src="/static/director-audience.js" defer></script></section>'''

STYLE='''
.recipient-delivery h2{margin-top:0}.recipient-delivery h3{font-size:17px}.audience-layout{display:grid;grid-template-columns:minmax(230px,.8fr) minmax(0,1.2fr);gap:22px}.scope-options{display:grid;gap:10px;align-content:start}.scope-card,.channel-card{display:flex;gap:12px;align-items:center;margin:0;padding:14px;border:1px solid #cbd2e3;border-radius:10px;cursor:pointer;background:#fff}.scope-card:has(input:checked),.channel-card:has(input:checked){background:#efedff;border-color:#6155cc}.scope-card small,.channel-card small{display:block;font-size:13px;color:#64748b;margin-top:5px}.recipient-delivery input[type=checkbox],.recipient-delivery input[type=radio]{width:19px;height:19px;flex:0 0 19px;accent-color:#5145c6}.family-list{max-height:290px;overflow:auto;border:1px solid #dce1eb;border-radius:9px}.family-row{display:flex;align-items:flex-start;gap:10px;padding:11px;margin:0;border-bottom:1px solid #e5e7ef}.family-row small{display:block;color:#64748b;font-size:12px;margin:4px 0;line-height:1.5}.family-row input{margin-top:3px}.family-meta{font-size:12px;color:#64748b;padding:9px;border-bottom:1px solid #e5e7ef}.channel-options{display:grid;grid-template-columns:1fr 1fr;gap:14px}.delivery-summary{padding:14px;border-radius:9px;background:#efedff;font-weight:600}.audience-error{color:#a22727}.filter-options{max-height:160px;overflow:auto;display:flex;gap:10px;flex-wrap:wrap}.filter-item{font-size:14px}.recipient-delivery details{margin:12px 0}.recipient-delivery hr{border:0;border-top:1px solid #e0e5ef;margin:24px 0}[hidden]{display:none!important}@media(max-width:700px){.audience-layout{grid-template-columns:1fr}.scope-options{grid-template-columns:1fr 1fr}.scope-card{padding:10px;font-size:14px}.channel-options{grid-template-columns:1fr}main{padding:14px}section{padding:16px}}
'''
