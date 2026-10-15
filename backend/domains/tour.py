"""Investor demo mode: a guided tour of a demonstration database.

Only on a database marked as a demo (python -m backend.demo):

- /tour walks a visitor through the real pages, each chapter opened at a
  real demo record (one batch from waste to a customer, a failed QC, stock,
  alerts, labels, reports).
- With DEMO_GUEST_ACCESS=1 set by whoever runs the server, "Explore as a
  guest" signs visitors in as the read-only demo viewer without a password.
  Everything they can do is what the viewer role allows: look, never change.

On any other database these routes answer 404, as if they did not exist.
"""
import os

from flask import abort, jsonify, render_template
from flask_login import current_user, login_required

from backend.core.accounts import _start_session, get_user_by_email
from backend.core.audit import audit_event
from backend.core.security import _permissions_for
from backend.core.web import app, db, logger
from backend.demo import GUEST_EMAIL, is_demo_database


def guest_access_enabled():
    return os.getenv('DEMO_GUEST_ACCESS', '').lower() in ('1', 'true', 'yes')


def _require_demo():
    if not is_demo_database(db):
        abort(404)


def _first(sql):
    row = db.fetch_one(sql)
    return row or {}


def _tour_records():
    """References of the demo records the chapters open, found by what they show."""
    sold = _first("""
        SELECT pl.business_id AS lot, o.business_id AS order_ref,
               COALESCE(direct.business_id, (
                   -- Lots made by drying name their batch through the harvest dried.
                   SELECT pb.business_id
                   FROM drying_outputs dout
                   JOIN drying_inputs di ON di.drying_batch_id = dout.drying_batch_id
                   JOIN harvests h ON h.id = di.harvest_id
                   JOIN production_events e ON e.id = h.production_event_id
                   JOIN production_batches pb ON pb.id = e.production_batch_id
                   WHERE dout.id = pl.drying_output_id
                   ORDER BY di.line_no LIMIT 1)) AS batch
        FROM customer_deliveries d
        JOIN customer_delivery_lines l ON l.delivery_id = d.id
        JOIN order_allocations a ON a.id = l.allocation_id
        JOIN product_lots pl ON pl.id = a.product_lot_id
        LEFT JOIN production_batches direct ON direct.id = pl.production_batch_id
        JOIN customer_orders o ON o.id = d.order_id
        WHERE d.status = 'DELIVERED'
        ORDER BY d.delivered_at, d.id LIMIT 1""")
    failed = _first("""
        SELECT db.business_id AS drying
        FROM quality_checks q JOIN drying_batches db ON db.id = q.drying_batch_id
        WHERE q.status = 'failed' ORDER BY q.id LIMIT 1""")
    reserved = _first("""
        SELECT pl.business_id AS lot
        FROM order_allocations a JOIN product_lots pl ON pl.id = a.product_lot_id
        WHERE a.quantity_kg > COALESCE(a.released_kg, 0)
          AND NOT EXISTS (SELECT 1 FROM customer_delivery_lines l WHERE l.allocation_id = a.id)
        ORDER BY a.id LIMIT 1""") or _first(
        "SELECT business_id AS lot FROM product_lots ORDER BY available_quantity_kg DESC, id LIMIT 1")
    health = _first("""
        SELECT pb.business_id AS batch
        FROM production_events e JOIN production_batches pb ON pb.id = e.production_batch_id
        WHERE e.event_type = 'health' AND pb.status NOT IN ('HARVESTED', 'COMPLETED', 'CANCELLED')
        ORDER BY e.occurred_at DESC LIMIT 1""")
    return {'sold': sold, 'failed': failed, 'reserved': reserved, 'health': health}


def _chapters(permissions):
    r = _tour_records()
    sold, failed = r['sold'], r['failed']
    chapters = [
        {'key': 'overview', 'title': 'The whole operation on one screen', 'url': '/operations',
         'text': 'Batches in production, harvests, drying, stock, orders and open problems across two '
                 'farms, updated from the records as staff enter them.',
         'look_for': 'Switch the period between 7, 30 and 90 days, or narrow it to one farm.'},
        {'key': 'batch', 'title': 'One batch, from waste to a customer',
         'url': f"/batch-360?ref={sold.get('batch', '')}" if sold.get('batch') else '/batch-360',
         'text': 'Every feeding, temperature reading, harvest and drying step for a single batch of larvae, '
                 'with who recorded it and when.',
         'look_for': 'The timeline and the yield at each stage.'},
        {'key': 'trace', 'title': 'Trace a sold product back to its waste',
         'url': (f"/traceability?ref={sold['lot']}&type=product_lot" if sold.get('lot') else '/traceability'),
         'text': 'Start from a bag of dried larvae that was delivered and follow it back through drying, '
                 'harvest and production to the waste it was grown on.',
         'look_for': 'Each link is a recorded transfer with its quantity, so the chain always adds up. '
                     'The customer and delivery stay hidden from accounts without sales access.'},
        {'key': 'quality', 'title': 'Quality is a gate, not a note',
         'url': (f"/traceability?ref={failed['drying']}&type=drying_batch" if failed.get('drying')
                 else '/traceability'),
         'text': 'This drying batch failed its moisture check. A failed or undecided batch cannot become '
                 'stock or be sold until a QC officer approves it.',
         'look_for': 'No product lot follows the failed check.'},
        {'key': 'stock', 'title': 'Stock that comes from a ledger',
         'url': f"/product-lot?ref={r['reserved']['lot']}" if r['reserved'].get('lot') else '/product-lot',
         'text': 'Stock is never typed in. It is the sum of recorded receipts, transfers, wastage and '
                 'dispatches, and part of this lot is already reserved for a customer order.',
         'look_for': 'Available, reserved and the movement history.'},
        {'key': 'alerts', 'title': 'Problems raise themselves', 'url': '/alerts',
         'text': 'Overdue harvests, open health issues, failed QC, low stock and late orders become alerts '
                 'from the records - nobody has to remember to report them.',
         'look_for': 'A critical health alert that a manager has already acknowledged.'},
        {'key': 'labels', 'title': 'QR labels in the field', 'url': '/labels?type=product_lot',
         'text': 'Printable labels for lots and batches. Scanning one opens the record for staff '
                 'who are allowed to see it, and nothing for anyone else.',
         'look_for': 'Labels carry an ID and basic facts only - never customers or prices.'},
        {'key': 'reports', 'title': 'Reports for managers and the board', 'url': '/analytics',
         'text': 'Waste received, conversion and yield, QC results, stock and sales, by farm and period, '
                 'with CSV export.',
         'look_for': 'The totals match the dashboard because both read the same records.'},
    ]
    if 'sales.read' in permissions and sold.get('order_ref'):
        chapters.insert(5, {
            'key': 'orders', 'title': 'From order to confirmed delivery',
            'url': f"/orders?ref={sold['order_ref']}",
            'text': 'An order reserved against released stock, dispatched and confirmed by the customer.',
            'look_for': 'Only QC-approved lots can be reserved.'})
    return chapters


@app.route('/api/demo/info', methods=['GET'])
def demo_info():
    """Public: whether this server is a demo and offers guest access (no records)."""
    demo = is_demo_database(db)
    return jsonify({'success': True, 'data': {
        'demo': demo,
        'guest_access': bool(demo and guest_access_enabled() and get_user_by_email(GUEST_EMAIL)),
    }})


@app.route('/api/demo/tour', methods=['GET'])
@login_required
def demo_tour():
    _require_demo()
    return jsonify({'success': True, 'data': {
        'chapters': _chapters(_permissions_for(current_user.role)),
        'read_only': not _permissions_for(current_user.role),
    }})


@app.route('/api/demo/guest', methods=['POST'])
def demo_guest_sign_in():
    _require_demo()
    if not guest_access_enabled():
        abort(404)
    guest = get_user_by_email(GUEST_EMAIL)
    # Only ever the read-only viewer: a changed role closes the door.
    if not guest or not guest.is_active or guest.role != 'viewer':
        return jsonify({'success': False, 'message': 'Guest access is not available'}), 404
    _start_session(guest, remember=False)
    audit_event('auth.demo_guest_sign_in', 'user', guest.id, entity_ref=guest.username, user=guest)
    logger.info('Demo guest signed in')
    return jsonify({'success': True, 'redirect': '/tour'})


@app.route('/tour')
def tour_page():
    _require_demo()
    return render_template('tour.html')
