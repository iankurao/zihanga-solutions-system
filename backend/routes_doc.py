"""Write the route reference (docs/api-routes.md) from the running app.

    python -m backend.routes_doc > docs/api-routes.md

tests/test_deployment.py fails when the committed file no longer matches the
routes, so the reference cannot drift from the code.
"""
import sys

# Routes anyone may call without signing in.
PUBLIC = {
    '/', '/login', '/register', '/api/auth/login', '/api/auth/register', '/logout',
    '/healthz', '/readyz', '/api/demo/info', '/tour', '/api/demo/guest',
    '/<path:filename>',  # the frontend's static files
}

HEADER = """# Route reference

Generated from the application by `python -m backend.routes_doc`; do not edit
by hand. **Access** is the permission the server checks (see
`backend/roles.py`); "signed in" means any signed-in user, with records
further limited to the farms, sites and facilities the user may access.
Routes under `/tour` and `/api/demo/*` exist only on demonstration databases.
"""


def _module(view):
    name = getattr(view, '__module__', '') or ''
    return name.rsplit('.', 1)[-1]


def render(app):
    rows = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == 'static':
            continue
        view = app.view_functions[rule.endpoint]
        methods = ', '.join(sorted(set(rule.methods) - {'HEAD', 'OPTIONS'}))
        if rule.rule in PUBLIC:
            access = 'public'
        else:
            access = getattr(view, 'required_permission', None) or 'signed in'
        rows.append((_module(view), rule.rule, methods, access))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    lines = [HEADER]
    current = None
    for module, path, methods, access in rows:
        if module != current:
            current = module
            lines += ['', f'## {module}', '', '| Method | Path | Access |', '|---|---|---|']
        lines.append(f'| {methods} | `{path}` | {access} |')
    return '\n'.join(lines).strip() + '\n'


def main():
    from backend.app import app

    sys.stdout.buffer.write(render(app).encode('utf-8'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
