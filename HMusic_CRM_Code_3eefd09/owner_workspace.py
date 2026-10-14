"""Persistent owner navigation around existing, same-origin CRM pages."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from flask import render_template

NAV = [("/", "Overview"), ("/calendar", "Calendar"), ("/students", "Students & families"), ("/invoices", "Billing"), ("/teachers", "Teachers"), ("/messages", "Messages"), ("/owner_event_room_bookings", "Events & rooms"), ("/owner_settings", "Settings")]

def apply_owner_workspace(response, request, is_owner):
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
    if in_workspace:
        script = """<script>if(window.parent!==window){
function workspaceURL(raw){const u=new URL(raw,location.href);if(u.origin===location.origin&&!/login|logout|print|export|download/i.test(u.pathname))u.searchParams.set('_workspace','1');return u.href;}
document.querySelectorAll('a[href]').forEach(a=>{if(!a.hasAttribute('download')&&!a.getAttribute('href').startsWith('#')){a.href=workspaceURL(a.href);if(new URL(a.href).origin===location.origin&&a.target==='_blank')a.target='_self';}});
document.addEventListener('click',e=>{const a=e.target.closest('a[href]');if(a&&!a.hasAttribute('download')&&!a.getAttribute('href').startsWith('#'))a.href=workspaceURL(a.href);},true);
document.querySelectorAll('form').forEach(f=>{if(new URL(f.action).origin!==location.origin)return;f.action=workspaceURL(f.action);if((f.method||'get').toLowerCase()==='get'&&!f.querySelector('[name="_workspace"]')){const input=document.createElement('input');input.type='hidden';input.name='_workspace';input.value='1';f.appendChild(input);}});
window.parent.postMessage({type:'hmusic-workspace',url:location.href,title:document.title},location.origin);
}</script>"""
        if request.path == "/":
            script += "<style>body>aside,#menu-toggle{display:none!important}body>main{margin-left:0!important}</style>"
        html = re.sub(r"</body\s*>", lambda m:script+m.group(0),html,count=1,flags=re.I)
    else:
        pairs=[(k,v) for k,v in parse_qsl(request.query_string.decode(),keep_blank_values=True) if k!="_workspace"]
        frame_url=request.path+"?"+urlencode(pairs+[("_workspace","1")])
        html=render_template("owner_workspace.html",nav=NAV,frame_url=frame_url)
    response.set_data(html)
    return response
