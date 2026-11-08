"""Persistent owner navigation around existing, same-origin CRM pages."""
import re
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from flask import render_template

NAV = [("/", "Overview"), ("/calendar", "Calendar"), ("/admissions", "Admissions & enrollment"), ("/students", "Students & families"), ("/invoices", "Billing"), ("/teachers", "Teachers"), ("/messages", "Messages"), ("/owner_event_room_bookings", "Events & rooms"), ("/owner_settings", "Settings")]


# Public family journeys stay independent of the signed-in manager workspace.
PUBLIC_ADMISSIONS = re.compile(r'^/(?:group-classes|group-registration|enrollment-order|trial-enrollment|trial|trial_form|trial_request|registration)(?:/|$)')
ADMISSIONS = re.compile(r'^/(?:admissions|studio-enrollment|admissions-admin|website-admin|inquiries|inquiry|add_inquiry|update_inquiry|convert_inquiry_to_student|new_students|new_student_leads|new_student_intake|add_new_student_lead|trial_leads|add_trial_lead|group-class-admin|group-enrollments)(?:/|$)')

def workspace_section(path):
    if path == '/': return '/'
    if ADMISSIONS.match(path): return '/admissions'
    for pattern, section in (
        (r'^/(?:student|students|parent|parents|enrollment|enrollments|add_student|add_enrollment|edit_student|edit_parent_admin)', '/students'),
        (r'^/(?:invoice|invoices|billing|payroll|family_billing|family_payment|pay_invoice|owner/invoice|owner/quick-pay)', '/invoices'),
        (r'^/(?:teacher|teachers)', '/teachers'),
        (r'^/(?:calendar|add_schedule|edit_schedule)', '/calendar'),
        (r'^/(?:message|messages|message_thread|notifications|notification|owner_message)', '/messages'),
        (r'^/(?:owner_event_room_bookings|locations_rooms|events|event)', '/owner_event_room_bookings'),
        (r'^/(?:owner_settings|settings|billing_settings|notification_templates|teacher_permissions)(?:/|$)', '/owner_settings'),
    ):
        if re.match(pattern, path): return section
    # An unknown page must not misleadingly appear to be a Settings screen.
    return ''

def apply_owner_workspace(response, request, is_owner):
    if PUBLIC_ADMISSIONS.match(request.path):
        return response
    destination = request.headers.get("Sec-Fetch-Dest", "document")
    referrer = urlsplit(request.referrer or "")
    from_workspace = referrer.netloc == request.host and dict(parse_qsl(referrer.query)).get("_workspace") == "1"
    in_workspace = request.args.get("_workspace") == "1" or destination == "iframe" or from_workspace
    if is_owner and in_workspace and response.status_code in (301,302,303,307,308):
        location=response.headers.get("Location", "")
        target=urlsplit(location)
        if location and (not target.netloc or target.netloc == request.host):
            pairs=[(k,v) for k,v in parse_qsl(target.query,keep_blank_values=True) if k!="_workspace"]
            response.headers["Location"]=urlunsplit((target.scheme,target.netloc,target.path,urlencode(pairs+[("_workspace","1")]),target.fragment))
        return response
    if not is_owner or response.status_code != 200 or response.mimetype != "text/html" or response.headers.get("Content-Disposition"):
        return response
    if destination not in ("document", "iframe", "empty", "") or request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", ""):
        return response
    if request.method != "GET" and request.is_json:
        return response
    if any(word in request.path.lower() for word in ("login", "logout", "print", "export", "download")):
        return response
    html = response.get_data(as_text=True)
    # Fragment responses belong to their existing client-side caller.
    if not re.search(r"<(?:html|body)\b", html, re.I):
        return response
    section = workspace_section(request.path)
    if section == '/admissions':
        admissions_nav = render_template('admissions_nav.html', admissions_tab=(
            'classes' if request.path.startswith('/group-class-admin') else
            'applications' if request.path.startswith('/group-enrollments') else 'intake'))
        html = re.sub(r"(<body\b[^>]*>)", lambda m:m.group(0)+admissions_nav,html,count=1,flags=re.I)
    if in_workspace:
        script = r"""<script>if(window.parent!==window){
function publicAdmissions(u){return /^\/(?:group-classes|group-registration|enrollment-order|trial-enrollment|trial|trial_form|trial_request|registration)(?:\/|$)/.test(u.pathname);}
function workspaceURL(raw){const u=new URL(raw,location.href);if(u.origin===location.origin){if(publicAdmissions(u))u.searchParams.delete('_workspace');else if(!/login|logout|print|export|download/i.test(u.pathname))u.searchParams.set('_workspace','1');}return u.href;}
function workspaceLink(a){a.href=workspaceURL(a.href);const u=new URL(a.href);if(u.origin===location.origin&&publicAdmissions(u)){if(a.target!=='_blank')a.target='_top';}else if(u.origin===location.origin&&a.target==='_blank')a.target='_self';}
document.querySelectorAll('a[href]').forEach(a=>{if(!a.hasAttribute('download')&&!a.getAttribute('href').startsWith('#')){workspaceLink(a);}});
document.addEventListener('click',e=>{const a=e.target.closest('a[href]');if(a&&!a.hasAttribute('download')&&!a.getAttribute('href').startsWith('#'))workspaceLink(a);},true);
document.querySelectorAll('form').forEach(f=>{if(new URL(f.action).origin!==location.origin)return;f.action=workspaceURL(f.action);if((f.method||'get').toLowerCase()==='get'&&!f.querySelector('[name="_workspace"]')){const input=document.createElement('input');input.type='hidden';input.name='_workspace';input.value='1';f.appendChild(input);}});
window.parent.postMessage({type:'hmusic-workspace',url:location.href,title:document.title,section:__WORKSPACE_SECTION__},location.origin);
}</script>"""
        script = script.replace("__WORKSPACE_SECTION__", json.dumps(section))
        if request.path == "/":
            script += "<style>body>aside,#menu-toggle{display:none!important}body>main{margin-left:0!important}</style>"
        html = re.sub(r"</body\s*>", lambda m:script+m.group(0),html,count=1,flags=re.I)
    else:
        pairs=[(k,v) for k,v in parse_qsl(request.query_string.decode(),keep_blank_values=True) if k!="_workspace"]
        frame_url=request.path+"?"+urlencode(pairs+[("_workspace","1")])
        html=render_template("owner_workspace.html",nav=NAV,frame_url=frame_url,active_section=section)
    response.set_data(html)
    return response
