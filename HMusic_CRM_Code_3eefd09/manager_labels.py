"""Presentation-only management terminology; never rename authorization keys."""
import re
from html.parser import HTMLParser

_OWNER = re.compile(r'(?<![A-Za-z0-9])owner(?![A-Za-z0-9])', re.IGNORECASE)

def manager_text(value):
    return _OWNER.sub(lambda m: 'MANAGER' if m[0].isupper() else 'Manager' if m[0][0].isupper() else 'manager', value)

class ManagerHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []
        self.skip = []
    def handle_starttag(self, tag, attrs):
        # Keep URLs, field names/values, role data, scripts and submitted drafts intact.
        self.parts.append(self.get_starttag_text())
        if tag in ('script', 'style', 'textarea', 'code', 'pre'):
            self.skip.append(tag)
    def handle_startendtag(self, tag, attrs): self.parts.append(self.get_starttag_text())
    def handle_endtag(self, tag):
        self.parts.append(f'</{tag}>')
        if self.skip and self.skip[-1] == tag: self.skip.pop()
    def handle_data(self, data): self.parts.append(data if self.skip else manager_text(data))
    def handle_entityref(self, name): self.parts.append('&' + name + ';')
    def handle_charref(self, name): self.parts.append('&#' + name + ';')
    def handle_comment(self, data): self.parts.append('<!--' + data + '-->')
    def handle_decl(self, decl): self.parts.append('<!' + decl + '>')
    def handle_pi(self, data): self.parts.append('<?' + data + '>')

def manager_json(value):
    """Human-facing labels only. Roles, IDs, URLs, types and user message bodies stay stable."""
    if isinstance(value, list): return [manager_json(item) for item in value]
    if not isinstance(value, dict): return value
    result = {}
    for key, item in value.items():
        if key in {'sender_name', 'author_name', 'display_name', 'error', 'message', 'title', 'status_label', 'role_label', 'type_label'} and isinstance(item, str):
            result[key] = manager_text(item)
        elif isinstance(item, (dict, list)):
            result[key] = manager_json(item)
        else: result[key] = item
    return result

def install_manager_labels(app):
    @app.after_request
    def management_display_labels(response):
        if response.direct_passthrough or 'attachment' in response.headers.get('Content-Disposition', '').lower():
            return response
        if response.mimetype == 'text/html':
            body = response.get_data(as_text=True)
            if _OWNER.search(body):
                parser = ManagerHTML()
                parser.feed(body)
                parser.close()
                response.set_data(''.join(parser.parts))
        elif response.is_json:
            body = response.get_json(silent=True)
            if isinstance(body, (dict, list)):
                updated = manager_json(body)
                if updated != body:
                    response.set_data(app.json.dumps(updated))
        return response
