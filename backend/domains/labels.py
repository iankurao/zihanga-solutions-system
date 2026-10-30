"""QR labels and label scanning."""

import os

from flask import jsonify, redirect, render_template, request
from flask_login import login_required

from backend.core.web import app, db, logger
from backend.core.http import _jsonable
from backend.core.scope import _scope_visibility_clause


# ---- QR labels and scanning ----------------------------------------------------
#
# A label's QR code holds only /scan/<type>/<reference>: no quantities, names
# or customers.  Scanning requires sign-in and the usual location access;
# unknown and unauthorised labels get the same "not available" page.

LABEL_TYPES = {
    'waste_lot': {
        'title': 'Waste lots', 'alias': 'wl',
        'sql': """
            SELECT wl.id, wl.business_id AS ref, 'Waste lot' AS kind,
                   wl.source_name || ' · ' || wl.waste_type AS line1,
                   wl.quantity || ' kg · ' || to_char(wl.collection_date, 'DD Mon YYYY') AS line2,
                   f.name AS farm, wl.collection_date AS sort_date
            FROM waste_lots AS wl LEFT JOIN farms AS f ON f.id = wl.farm_id
        """,
    },
    'substrate_batch': {
        'title': 'Substrate batches', 'alias': 'sb',
        'sql': """
            SELECT sb.id, sb.business_id AS ref, 'Substrate batch' AS kind,
                   'Prepared ' || to_char(sb.preparation_date, 'DD Mon YYYY') AS line1,
                   sb.total_input_weight_kg || ' kg input' AS line2,
                   f.name AS farm, sb.preparation_date AS sort_date
            FROM substrate_batches AS sb LEFT JOIN farms AS f ON f.id = sb.farm_id
        """,
    },
    'production_batch': {
        'title': 'Production batches', 'alias': 'pb',
        'sql': """
            SELECT pb.id, pb.business_id AS ref, 'Production batch' AS kind,
                   'Started ' || to_char(pb.start_date, 'DD Mon YYYY') AS line1,
                   fa.name AS line2, f.name AS farm, pb.start_date AS sort_date
            FROM production_batches AS pb
            LEFT JOIN farms AS f ON f.id = pb.farm_id
            LEFT JOIN facilities AS fa ON fa.id = pb.facility_id
        """,
    },
    'harvest': {
        'title': 'Harvests', 'alias': 'pe',
        'sql': """
            SELECT h.id, h.harvest_code AS ref, 'Harvest' AS kind,
                   pb.business_id || ' · ' || h.harvest_stage AS line1,
                   pe.quantity || ' kg wet · ' || to_char(pe.occurred_at, 'DD Mon YYYY') AS line2,
                   f.name AS farm, pe.occurred_at::date AS sort_date
            FROM harvests AS h
            JOIN production_events AS pe ON pe.id = h.production_event_id
            JOIN production_batches AS pb ON pb.id = pe.production_batch_id
            LEFT JOIN farms AS f ON f.id = pe.farm_id
        """,
    },
    'drying_batch': {
        'title': 'Drying batches', 'alias': 'db',
        'sql': """
            SELECT db.id, COALESCE(db.business_id, db.batch_code) AS ref, 'Drying batch' AS kind,
                   db.drying_method AS line1, to_char(db.drying_date, 'DD Mon YYYY') AS line2,
                   f.name AS farm, db.drying_date AS sort_date
            FROM drying_batches AS db LEFT JOIN farms AS f ON f.id = db.farm_id
        """,
    },
    'product_lot': {
        'title': 'Product lots', 'alias': 'batch',
        'sql': """
            SELECT pl.id, pl.business_id AS ref, 'Product lot' AS kind,
                   INITCAP(REPLACE(pl.product_type, '_', ' ')) AS line1,
                   pl.quantity_kg || ' kg · produced ' || to_char(pl.production_date, 'DD Mon YYYY') AS line2,
                   f.name AS farm, pl.production_date AS sort_date
            FROM product_lots AS pl
            JOIN product_lot_origins AS batch ON batch.product_lot_id = pl.id
            LEFT JOIN farms AS f ON f.id = pl.farm_id
        """,
    },
    'production_unit': {
        'title': 'Bio-pods & trays', 'alias': 'u',
        'sql': """
            SELECT u.id, u.unit_code AS ref, 'Bio-pod / tray' AS kind, u.name AS line1,
                   fa.name AS line2, f.name AS farm, u.created_at::date AS sort_date
            FROM production_units AS u
            JOIN facilities AS fa ON fa.id = u.facility_id
            LEFT JOIN farms AS f ON f.id = u.farm_id
        """,
    },
}

# Columns that identify a record from the reference printed on its label.
LABEL_REF_COLUMNS = {
    'waste_lot': ['wl.business_id'],
    'substrate_batch': ['sb.business_id', 'sb.batch_code'],
    'production_batch': ['pb.business_id', 'pb.batch_code'],
    'harvest': ['h.harvest_code'],
    'drying_batch': ['db.business_id', 'db.batch_code'],
    'product_lot': ['pl.business_id', 'pl.lot_code'],
    'production_unit': ['u.unit_code'],
}


def _public_base_url():
    return (os.getenv('PUBLIC_BASE_URL') or request.host_url).rstrip('/')


def _scan_path(kind, ref):
    from urllib.parse import quote

    return f'/scan/{kind}/{quote(str(ref), safe="")}'


def _label_rows(kind, *, ref=None, query=None, limit=200):
    spec = LABEL_TYPES[kind]
    visibility, params = _scope_visibility_clause(spec['alias'])
    clauses = [visibility]
    values = list(params)
    if ref is not None:
        columns = LABEL_REF_COLUMNS[kind]
        clauses.append('(' + ' OR '.join(f'UPPER({c}) = UPPER(%s)' for c in columns) + ')')
        values.extend([ref] * len(columns))
    elif query:
        columns = LABEL_REF_COLUMNS[kind]
        pattern = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        clauses.append('(' + ' OR '.join(f'{c} ILIKE %s' for c in columns) + ')')
        values.extend([pattern] * len(columns))
    rows = db.fetch_all(
        f"{spec['sql']} WHERE {' AND '.join(clauses)} ORDER BY sort_date DESC NULLS LAST, 1 DESC LIMIT %s",
        (*values, limit),
    )
    return [dict(row) for row in rows]


@app.route('/api/labels', methods=['GET'])
@login_required
def label_types():
    return jsonify({'success': True, 'data': [
        {'key': key, 'title': spec['title']} for key, spec in LABEL_TYPES.items()
    ]})


@app.route('/api/labels/<string:kind>', methods=['GET'])
@login_required
def label_data(kind):
    if kind not in LABEL_TYPES:
        return jsonify({'success': False, 'message': 'Unknown label type'}), 404
    query = str(request.args.get('q') or '').strip()[:40] or None
    refs = [r.strip() for r in str(request.args.get('refs') or '').split(',') if r.strip()][:100]
    try:
        if refs:
            rows = []
            for ref in refs:
                rows.extend(_label_rows(kind, ref=ref, limit=1))
        else:
            rows = _label_rows(kind, query=query)
        base = _public_base_url()
        for row in rows:
            row['scan_url'] = base + _scan_path(kind, row['ref'])
        return jsonify({
            'success': True,
            'types': {key: spec['title'] for key, spec in LABEL_TYPES.items()},
            'data': _jsonable(rows),
        }), 200
    except Exception:
        logger.exception('Error loading label data')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


def _scan_unavailable(ref):
    return render_template('scan_unavailable.html', ref=ref), 404


@app.route('/scan/<string:kind>/<path:ref>')
@login_required
def scan_label(kind, ref):
    """Open the right page for a scanned label, if the user may see it."""
    from urllib.parse import quote

    if kind not in LABEL_TYPES or len(ref) > 60:
        return _scan_unavailable(ref)
    rows = _label_rows(kind, ref=ref, limit=1)
    if not rows:
        return _scan_unavailable(ref)
    found = rows[0]['ref']
    q = quote(str(found), safe='')
    if kind == 'production_batch':
        return redirect(f'/batch-360?ref={q}')
    if kind == 'product_lot':
        return redirect(f'/product-lot?ref={q}')
    if kind == 'production_unit':
        unit = db.fetch_one(
            """
            SELECT pb.business_id FROM production_batch_units AS bu
            JOIN production_batches AS pb ON pb.id = bu.production_batch_id
            WHERE bu.production_unit_id = %s AND bu.released_at IS NULL
            """,
            (rows[0]['id'],),
        )
        if unit:
            return redirect(f"/batch-360?ref={quote(unit['business_id'], safe='')}")
        return redirect('/farmer')
    return redirect(f'/traceability?ref={q}&type={kind}')


@app.route('/labels')
@login_required
def labels_page():
    return render_template('labels.html')
