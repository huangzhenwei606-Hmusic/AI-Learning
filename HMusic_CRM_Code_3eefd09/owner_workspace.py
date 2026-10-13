"""Persistent owner navigation around existing, same-origin CRM pages."""
import re
from urllib.parse import parse_qsl, urlencode
from flask import render_template

NAV = [("/", "Overview"), ("/calendar", "Calendar"), ("/students", "Students & families"), ("/invoices", "Billing"), ("/teachers", "Teachers"), ("/messages", "Messages"), ("/owner_event_room_bookings", "Events & rooms"), ("/owner_settings", "Settings")]

def apply_owner_workspace(response, request, is_owner):
    if not is_owner or response.status_code != 200 or response.mimetype != "text/html" or response.headers.get("Content-Disposition"):
        return response
    destination = request.headers.get("Sec-Fetch-Dest", "document")
    if destination not in ("document", "iframe") or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return response
    if any(word in request.path.lower() for word in ("login", "logout", "print", "export", "download")):
        return response
    html = response.get_data(as_text=True)
    # Fragment responses belong to their existing client-side caller.
    if not re.search(r"<(?:html|body)\b", html, re.I):
        return response
    if destination == "iframe" or request.args.get("_workspace") == "1":
        script = """<script>if(window.parent!==window){document.addEventListener('click',function(e){const a=e.target.closest('a');if(!a||a.hasAttribute('download'))return;const u=new URL(a.href,location.href);if(u.origin===location.origin&&a.target==='_blank')a.target='_self';});window.parent.postMessage({type:'hmusic-workspace',url:location.href,title:document.title},location.origin);}</script>"""
        if request.path == "/":
            script += "<style>body>aside,#menu-toggle{display:none!important}body>main{margin-left:0!important}</style>"
        html = re.sub(r"</body\s*>", lambda m:script+m.group(0),html,count=1,flags=re.I)
    else:
        pairs=[(k,v) for k,v in parse_qsl(request.query_string.decode(),keep_blank_values=True) if k!="_workspace"]
        frame_url=request.path+"?"+urlencode(pairs+[("_workspace","1")])
        html=render_template("owner_workspace.html",nav=NAV,frame_url=frame_url)
    response.set_data(html)
    return response
