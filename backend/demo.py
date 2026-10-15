"""Demonstration dataset, kept apart from real data.

    python -m backend.demo status
    python -m backend.demo seed [--accounts-file PATH]
    python -m backend.demo seed --reset          (demo databases only)

Point DATABASE_URL (and the PG* variables) at a database used only for demos.
Seeding refuses any database that already holds records and is not marked as
a demo database, so real farms, customers and orders are never mixed with
demonstration records. The first seed marks the database as a demo
(schema_markers 'demo_database'); the app then shows a "Demo data" badge and
sends no email from it.

Everything is created through the application's own API by the people who
would do it (an operator records production, a QC officer releases lots, a
sales officer takes orders), so every rule, stock movement, alert and audit
entry in the demo is genuine. Dates are spread over the last three months so
dashboards and reports have history.
"""
import argparse
import random
import secrets
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

DEMO_MARKER = 'demo_database'
DEMO_SEEDED = 'demo_dataset_v1'
# The read-only viewer that DEMO_GUEST_ACCESS signs visitors in as.
GUEST_EMAIL = 'investor.guest@demo.example.com'

# Tables that hold real operational or commercial records; any row in a
# database not marked as a demo means it is not safe to seed.
REAL_DATA_TABLES = (
    'organizations', 'waste_lots', 'production_batches', 'drying_batches', 'product_lots',
    'customers', 'customer_orders', 'waste_sourcing', 'sales',
)


class DemoRefused(Exception):
    """The target database is not safe to seed."""


# ---- database state ------------------------------------------------------------------

def _marker(cursor, name):
    cursor.execute("SELECT to_regclass('schema_markers') AS t")
    if cursor.fetchone()['t'] is None:
        return False
    cursor.execute("SELECT 1 FROM schema_markers WHERE name = %s", (name,))
    return cursor.fetchone() is not None


def is_demo_database(db):
    with db.transaction() as cursor:
        return _marker(cursor, DEMO_MARKER)


def database_state(db):
    """'demo-seeded', 'demo-empty', 'empty' or 'real' (has records, not a demo)."""
    with db.transaction() as cursor:
        if _marker(cursor, DEMO_SEEDED):
            return 'demo-seeded'
        if _marker(cursor, DEMO_MARKER):
            return 'demo-empty'
        for table in REAL_DATA_TABLES:
            cursor.execute("SELECT to_regclass(%s) AS t", (table,))
            if cursor.fetchone()['t'] is None:
                continue
            cursor.execute(f"SELECT EXISTS (SELECT 1 FROM {table}) AS any")
            if cursor.fetchone()['any']:
                return 'real'
        return 'empty'


def _mark(db, name):
    db.execute_query(
        "INSERT INTO schema_markers (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,)
    )


def _reset_schema(db):
    """Drop and recreate everything - only ever called on a demo database."""
    with db.transaction() as cursor:
        if not _marker(cursor, DEMO_MARKER):
            raise DemoRefused('Only a demo database can be reset.')
        cursor.execute("DROP SCHEMA public CASCADE")
        cursor.execute("CREATE SCHEMA public")


# ---- API client ----------------------------------------------------------------------

class DemoUser:
    def __init__(self, app, email, password, role, username):
        self.email, self.password, self.role, self.username = email, password, role, username
        self.client = app.test_client()
        response = self.client.post('/api/auth/login', json={'username': email, 'password': password},
                                    base_url='https://localhost')
        if response.status_code != 200:
            raise RuntimeError(f'Demo sign-in failed for {email}: {response.get_json()}')

    def call(self, method, url, body=None, expect=(200, 201)):
        response = getattr(self.client, method)(url, json=body, base_url='https://localhost')
        if response.status_code not in expect:
            raise RuntimeError(f'{self.role} {method.upper()} {url} -> {response.status_code}: '
                               f'{response.get_json()}')
        return response.get_json()

    def post(self, url, body=None, expect=(200, 201)):
        return self.call('post', url, body or {}, expect)

    def put(self, url, body=None, expect=(200, 201)):
        return self.call('put', url, body or {}, expect)

    def get(self, url, expect=(200,)):
        return self.call('get', url, None, expect)


# ---- the dataset -----------------------------------------------------------------------

class DemoBuilder:
    """Builds two farms with about three months of linked history."""

    ROLES = [
        ('manager', 'Grace Wanjiru', 'Farm manager'),
        ('operator', 'Peter Kiprono', 'Farmer, Kericho'),
        ('operator', 'Mary Atieno', 'Farmer, Nakuru'),
        ('qc_officer', 'Daniel Otieno', 'QC officer'),
        ('inventory_officer', 'Esther Chebet', 'Store keeper'),
        ('sales_officer', 'Brian Mwangi', 'Sales officer'),
        ('viewer', 'Investor Guest', 'Read-only visitor'),
    ]

    def __init__(self, app, db, today=None, log=print):
        self.app, self.db, self.log = app, db, log
        self.today = today or date.today()
        self.rng = random.Random(2026)
        self.accounts = []
        self.lots = {}

    # ---- helpers ------------------------------------------------------------------------

    def day(self, offset):
        return (self.today + timedelta(days=offset)).isoformat()

    def at(self, offset, hour=8):
        moment = datetime.combine(self.today + timedelta(days=offset), time(hour), tzinfo=timezone.utc)
        return moment.isoformat()

    def _password(self):
        return 'demo-' + secrets.token_urlsafe(9)

    def _user(self, role, full_name, title):
        from werkzeug.security import generate_password_hash

        username = full_name.lower().replace(' ', '.')
        email = f'{username}@demo.example.com'
        password = self._password()
        if role == 'super_admin':
            # Super admins are created out of band, as with create_super_admin.
            self.db.execute_query(
                "INSERT INTO users (username, full_name, email, password_hash, role) VALUES (%s, %s, %s, %s, %s)",
                (username, full_name, email, generate_password_hash(password), role),
            )
        else:
            self.admin.post('/api/admin/users', {'username': username, 'full_name': full_name, 'email': email,
                                                 'password': password, 'role': role})
        self.accounts.append((title, role, email, password))
        return DemoUser(self.app, email, password, role, username)

    # ---- build ---------------------------------------------------------------------------

    def build(self):
        self.admin = self._user('super_admin', 'Demo Administrator', 'Super admin')
        self._locations()
        self._people()
        self._kericho_history()
        self._nakuru_history()
        self._commerce()
        self._finish()
        return self.accounts

    def _locations(self):
        a = self.admin
        org = a.post('/api/locations/organizations', {
            'organization_code': 'DEMO', 'name': 'Zehunger Demo Co-operative',
            'description': 'Demonstration organization - not real data'})['data']
        self.farms = {}
        for code, name, facilities in (
            ('KER', 'Kericho Demo Farm', [('production', 'Larvae House A'), ('production', 'Larvae House B'),
                                          ('drying', 'Solar Dryer'), ('warehouse', 'Feed Store')]),
            ('NAK', 'Nakuru Demo Farm', [('production', 'Larvae Shed'), ('drying', 'Drying Shed'),
                                         ('warehouse', 'Nakuru Store')]),
        ):
            farm = a.post('/api/locations/farms', {
                'organization_id': org['id'], 'farm_code': code, 'name': name})['data']
            site = a.post('/api/locations/sites', {'farm_id': farm['id'], 'site_code': 'MAIN',
                                                   'name': f'{name.split()[0]} main site'})['data']
            made = {}
            for index, (kind, label) in enumerate(facilities):
                made[label] = a.post('/api/locations/facilities', {
                    'site_id': site['id'], 'facility_code': f'{kind[:3].upper()}{index + 1}',
                    'name': label, 'facility_type': kind})['data']
            self.farms[code] = {'farm': farm, 'site': site, 'facilities': made}

        def scope(code, label):
            place = self.farms[code]
            return {'farm_id': place['farm']['id'], 'site_id': place['site']['id'],
                    'facility_id': place['facilities'][label]['id']}

        self.scope = scope
        self.stores = {
            'KER-dryer': a.post('/api/inventory/locations', {**scope('KER', 'Solar Dryer'),
                                'location_code': 'DRY-STORE', 'name': 'Dryer store'})['data'],
            'KER-bay1': a.post('/api/inventory/locations', {**scope('KER', 'Feed Store'),
                               'location_code': 'BAY-1', 'name': 'Store bay 1'})['data'],
            'KER-bay2': a.post('/api/inventory/locations', {**scope('KER', 'Feed Store'),
                               'location_code': 'BAY-2', 'name': 'Store bay 2'})['data'],
            'NAK-store': a.post('/api/inventory/locations', {**scope('NAK', 'Drying Shed'),
                                'location_code': 'NAK-STORE', 'name': 'Nakuru dry store'})['data'],
        }
        self.pods = {}
        for code, house, count in (('KER', 'Larvae House A', 4), ('KER', 'Larvae House B', 4),
                                   ('NAK', 'Larvae Shed', 3)):
            for n in range(1, count + 1):
                unit_code = f"{code}-{house.split()[-1][0]}{n:02d}"
                self.pods.setdefault((code, house), []).append(a.post('/api/production/units', {
                    **scope(code, house), 'unit_code': unit_code, 'name': f'Bio-pod {unit_code}',
                    'unit_type': 'bio_pod', 'capacity_kg': '120'})['data'])
        self.log('  locations, stores and bio-pods')

    def _people(self):
        users = {}
        for role, name, title in self.ROLES:
            users[name] = self._user(role, name, title)
        grant = lambda user, scope, scope_id: self.admin.post('/api/locations/access', {  # noqa: E731
            'user_id': self.db.fetch_one("SELECT user_id FROM users WHERE email = %s", (user.email,))['user_id'],
            'scope': scope, 'scope_id': scope_id})
        org_id = self.farms['KER']['farm']['organization_id']
        grant(users['Grace Wanjiru'], 'organization', org_id)
        grant(users['Peter Kiprono'], 'farm', self.farms['KER']['farm']['id'])
        grant(users['Mary Atieno'], 'farm', self.farms['NAK']['farm']['id'])
        grant(users['Daniel Otieno'], 'organization', org_id)
        grant(users['Esther Chebet'], 'organization', org_id)
        grant(users['Brian Mwangi'], 'organization', org_id)
        grant(users['Investor Guest'], 'organization', org_id)
        self.manager, self.qc = users['Grace Wanjiru'], users['Daniel Otieno']
        self.stock, self.sales = users['Esther Chebet'], users['Brian Mwangi']
        self.operators = {'KER': users['Peter Kiprono'], 'NAK': users['Mary Atieno']}
        self.log('  people and access')

    # ---- production ------------------------------------------------------------------------

    SOURCES = [
        ('market', 'Kericho Municipal Market (demo)', 'vegetable'),
        ('brewery', 'Highland Brewery spent grain (demo)', 'brewery_grain'),
        ('hotel', 'Tea Country Hotel kitchen (demo)', 'food_waste'),
    ]

    def _batch(self, code, house, start, *, stage, issue_kg, harvest_kg=None, expected=None,
               health=None, dry=None, qc='approved', units=1):
        """One batch from waste to (optionally) a released product lot."""
        op = self.operators[code]
        scope = self.scope(code, house)
        kind, source, waste_type = self.SOURCES[self.rng.randrange(len(self.SOURCES))]
        waste_kg = issue_kg * Decimal('1.25')
        lot = op.post('/api/waste-sourcing', {
            **scope, 'collection_date': self.day(start - 3), 'collection_time': '07:30', 'source_type': kind,
            'source_name': source, 'waste_type': waste_type, 'waste_weight': f'{waste_kg:.1f}',
            'segregation_status': 'organic', 'collection_personnel': op.username, 'lot_status': 'available',
            'contaminants_found': []})['waste_lot']
        substrate = op.post('/api/substrate-preparation', {
            **scope, 'batch_no': f'SUB-{code}-{abs(start):02d}{house[-1]}', 'prep_date': self.day(start - 1),
            'moisture_consistency': 'moist', 'waste_particle_size': 'fine', 'foreign_matter': 'no',
            'handler_operator': op.username,
            'inputs': [{'waste_lot_id': lot['id'], 'quantity_used': f'{issue_kg * Decimal("1.1"):.1f}'}]})['id']
        free_pods = [p['id'] for p in self.pods[(code, house)] if not p.get('_used')][:units]
        for pod in self.pods[(code, house)]:
            if pod['id'] in free_pods:
                pod['_used'] = True
        batch = op.post('/api/production/batches', {
            **scope, 'start_date': self.day(start), 'started_at': self.at(start, 9),
            'expected_harvest_at': self.at(expected if expected is not None else start + 16, 12),
            'current_stage': 'STARTING', 'harvest_limit_kg': f'{issue_kg * Decimal("0.35"):.1f}',
            'unit_ids': free_pods,
            'inputs': [{'substrate_batch_id': substrate, 'quantity_issued': f'{issue_kg:.1f}'}]})['record']
        ref = batch['business_id']
        base = f'/api/production/batches/{ref}'
        if stage == 'PLANNED':
            return batch
        op.post(f'{base}/status', {'status': 'ACTIVE'})
        last = min(0, (start + 16) if harvest_kg is None else start + 15)
        for offset in range(start + 1, last + 1, 2):
            op.post(f'{base}/events/feeding', {
                'occurred_at': self.at(offset, 7), 'feed_type': 'vegetable mash',
                'quantity_offered': f'{issue_kg * Decimal("0.08"):.1f}', 'offered_unit': 'kg',
                'operator': op.username})
        for offset in range(start + 2, last + 1, 3):
            op.post(f'{base}/events/monitoring', {
                'occurred_at': self.at(offset, 10), 'asset_reference': house,
                'temperature': round(self.rng.uniform(27.0, 31.5), 1),
                'humidity': round(self.rng.uniform(58, 72), 1)})
        if health:
            op.post(f'{base}/events/health', {
                'occurred_at': self.at(health[0], 11), 'observed_issue': health[1], 'severity': health[2],
                'action_taken': health[3], 'status': health[4]})
        if stage == 'ACTIVE':
            return batch
        op.post(f'{base}/status', {'status': 'MONITORING'})
        if stage == 'MONITORING':
            return batch
        op.post(f'{base}/status', {'status': 'READY_FOR_HARVEST'})
        if stage == 'READY_FOR_HARVEST':
            return batch
        harvest = op.post(f'{base}/events/harvest', {
            'harvest_date': self.day(start + 17), 'event_time': '10:30', 'wet_weight': f'{harvest_kg:.1f}',
            'unit': 'kg', 'harvest_stage': 'prepupae', 'operator': op.username, 'location': house})['harvest']
        op.post(f'{base}/status', {'status': 'HARVESTED'})
        if dry is None:
            return batch
        dryer = 'Solar Dryer' if code == 'KER' else 'Drying Shed'
        drying = op.post('/api/drying/batches', {
            **self.scope(code, dryer), 'batch_code': f'DRY-{code}-{abs(start):02d}', 'drying_date': self.day(start + 18), 'drying_method': 'solar_drying',
            'personnel': op.username,
            'inputs': [{'harvest_id': harvest['id'], 'quantity': f'{harvest_kg:.1f}', 'unit': 'kg'}]})['data']
        dref = drying['business_id']
        for status in ('RECEIVED', 'DRYING'):
            op.post(f'/api/drying/batches/{dref}/status', {'status': status})
        output = op.post(f'/api/drying/batches/{dref}/outputs', {
            'quantity': f'{dry:.1f}', 'unit': 'kg', 'moisture_percent': '9.5' if qc != 'failed' else '16.0',
            'output_date': self.day(start + 20), 'operator': op.username})['output']
        op.post(f'/api/drying/batches/{dref}/status', {'status': 'QC_PENDING'})
        check = self.qc.post(f"/api/drying/outputs/{output['id']}/quality-checks", {
            'status': 'failed' if qc == 'failed' else 'passed', 'inspector': self.qc.username,
            'moisture_percent': '16.0' if qc == 'failed' else '9.5',
            'notes': 'Moisture above 12% - redry required' if qc == 'failed' else 'Clean, golden colour'})['data']
        if qc == 'failed':
            self.qc.post(f'/api/drying/batches/{dref}/quality-approvals', {
                'quality_check_id': check['id'], 'decision': 'rejected', 'approver': self.qc.username,
                'reason': 'Moisture too high for storage'})
            return batch
        if qc == 'pending':
            return batch
        self.qc.post(f'/api/drying/batches/{dref}/quality-approvals', {
            'quality_check_id': check['id'], 'decision': 'approved', 'approver': self.qc.username})
        store = self.stores['KER-dryer' if code == 'KER' else 'NAK-store']
        self.lots[ref] = self.qc.post('/api/product-lots', {
            'drying_output_id': output['id'], 'product_type': 'dried_larvae',
            'inventory_location_id': store['id'], 'storage_location': store['name']})['data']
        return batch

    def _kericho_history(self):
        k = Decimal
        self.ker = {
            # Sold and delivered.
            'B1': self._batch('KER', 'Larvae House A', -78, stage='DONE', issue_kg=k(220), harvest_kg=k(58),
                              dry=k(17.5)),
            # Sold, delivery on the road.
            'B2': self._batch('KER', 'Larvae House B', -66, stage='DONE', issue_kg=k(240), harvest_kg=k(63),
                              dry=k(19.0)),
            # Failed QC: moisture too high.
            'B3': self._batch('KER', 'Larvae House A', -54, stage='DONE', issue_kg=k(200), harvest_kg=k(51),
                              dry=k(16.0), qc='failed'),
            # In stock, partly reserved.
            'B4': self._batch('KER', 'Larvae House B', -42, stage='DONE', issue_kg=k(260), harvest_kg=k(70),
                              dry=k(21.5),
                              health=(-35, 'Larvae climbing out of trays', 'medium', 'Reduced moisture',
                                      'resolved')),
            # Awaiting QC decision.
            'B5': self._batch('KER', 'Larvae House A', -34, stage='DONE', issue_kg=k(210), harvest_kg=k(55),
                              dry=k(16.5), qc='pending'),
            # Harvest overdue.
            'B6': self._batch('KER', 'Larvae House A', -21, stage='MONITORING', issue_kg=k(230), expected=-3),
            # Open health issue.
            'B7': self._batch('KER', 'Larvae House B', -12, stage='ACTIVE', issue_kg=k(250),
                              health=(-2, 'Mites seen on tray edges', 'critical', 'Isolated pod, cleaned trays',
                                      'open')),
            # Ready to harvest tomorrow.
            'B8': self._batch('KER', 'Larvae House B', -16, stage='READY_FOR_HARVEST', issue_kg=k(200), expected=1),
            # Just planned.
            'B9': self._batch('KER', 'Larvae House A', 0, stage='PLANNED', issue_kg=k(180)),
        }
        self.log('  Kericho production history')

    def _nakuru_history(self):
        k = Decimal
        self.nak = {
            'N1': self._batch('NAK', 'Larvae Shed', -60, stage='DONE', issue_kg=k(150), harvest_kg=k(40),
                              dry=k(12.0)),
            'N2': self._batch('NAK', 'Larvae Shed', -8, stage='ACTIVE', issue_kg=k(160)),
        }
        self.log('  Nakuru production history')

    # ---- stock and sales -------------------------------------------------------------------

    def _commerce(self):
        lots = self.lots
        b1, b2, b4 = (lots[self.ker[n]['business_id']] for n in ('B1', 'B2', 'B4'))
        # The store keeper moves released lots into the feed store.
        for lot, kg in ((b1, '17.5'), (b2, '19.0'), (b4, '21.5')):
            self.stock.post('/api/inventory/movements', {
                'product_lot_id': lot['business_id'], 'movement_type': 'TRANSFER', 'quantity_kg': kg, 'unit': 'kg',
                'from_location_id': self.stores['KER-dryer']['id'], 'to_location_id': self.stores['KER-bay1']['id']})
        self.manager.post('/api/inventory/movements', {
            'product_lot_id': b2['business_id'], 'movement_type': 'WASTAGE', 'quantity_kg': '0.5', 'unit': 'kg',
            'from_location_id': self.stores['KER-bay1']['id'], 'reason': 'Bag torn during handling'})

        customers = {}
        for name, contact in (('Demo Poultry Feeds Ltd', '+254 700 000 101'),
                              ('Demo Aquafarm Kenya', '+254 700 000 102'),
                              ('Demo Pig Unit Co-operative', '+254 700 000 103')):
            slug = name.lower().replace(' ', '.')
            customers[name] = self.sales.post('/api/customers', {
                'name': name, 'contact': contact, 'email': f'orders@{slug}.example.com',
                'address': 'Demonstration customer - not a real business'})['id']
        farm = self.farms['KER']['farm']['id']

        def order(customer, kg, requested, reference):
            return self.sales.post('/api/orders', {
                'customer_id': customers[customer], 'farm_id': farm, 'order_date': self.day(min(requested - 7, 0)),
                'requested_delivery_date': self.day(requested),
                'customer_reference': reference,
                'lines': [{'product_type': 'dried_larvae', 'quantity_kg': kg}]})['data']

        def reserve(o, lot, kg):
            return self.sales.post(f"/api/orders/{o['business_id']}/allocations", {
                'order_line_id': o['lines'][0]['id'], 'product_lot_id': lot['id'],
                'location_id': self.stores['KER-bay1']['id'], 'quantity_kg': kg})['data']

        def dispatch(o, kg, driver, when):
            return self.sales.post(f"/api/orders/{o['business_id']}/deliveries", {
                'dispatched_at': self.at(when, 8), 'lines': [{'allocation_id': o['allocations'][-1]['id'], 'quantity_kg': kg}],
                'vehicle': 'KDA 123A', 'driver': driver})['data']['created_delivery']

        # Delivered in full.
        o1 = reserve(order('Demo Poultry Feeds Ltd', '15', -20, 'PO-2041'), b1, '15')
        delivered = dispatch(o1, '15', 'John Kamau', -21)
        self.sales.post(f'/api/deliveries/{delivered}/confirm', {
            'received_by': 'Demo Poultry store keeper', 'delivered_at': self.at(-20, 14)})
        # On the road.
        o2 = reserve(order('Demo Aquafarm Kenya', '12', 2, 'AQ-118'), b2, '12')
        dispatch(o2, '12', 'Paul Ochieng', 0)
        # Reserved, waiting to ship.
        reserve(order('Demo Pig Unit Co-operative', '10', 5, 'PIG-77'), b4, '10')
        # Overdue and not yet reserved.
        order('Demo Poultry Feeds Ltd', '8', -2, 'PO-2057')
        # Cancelled by the customer.
        cancelled = order('Demo Aquafarm Kenya', '5', 10, 'AQ-121')
        self.sales.post(f"/api/orders/{cancelled['business_id']}/cancel", {'reason': 'Customer changed supplier'})
        self.log('  stock movements, customers, orders and deliveries')

    def _finish(self):
        self.admin.put('/api/alerts/thresholds', {
            'farm_id': self.farms['KER']['farm']['id'], 'product_type': 'dried_larvae', 'minimum_kg': '40'})
        self.db.execute_query("UPDATE operational_alert_sync SET last_run_at = NULL")
        alerts = self.manager.get('/api/alerts?status=all')['data']
        health = [a for a in alerts if a['rule'] == 'health_issue_open']
        if health:
            self.manager.post(f"/api/alerts/{health[0]['id']}/acknowledge",
                              {'note': 'Vet visit booked for tomorrow'})
        self.log(f'  {len(alerts)} alerts raised from the records')


# ---- command line --------------------------------------------------------------------

def _load_app():
    from backend.app import app, db
    from backend.init_db import init_database

    return app, db, init_database


def seed(*, reset=False, accounts_file=None, log=print):
    app, db, init_database = _load_app()
    init_database()
    state = database_state(db)
    if state == 'real':
        raise DemoRefused(
            'This database already holds farms, customers or orders and is not a demo database. '
            'Create an empty database for the demo and point DATABASE_URL at it.')
    if state == 'demo-seeded':
        if not reset:
            raise DemoRefused('The demo dataset is already loaded. Use --reset to rebuild it.')
        _reset_schema(db)
        init_database()
        # The reset also dropped the sign-in session table Flask-Session made at start-up.
        from backend.core.web import sqlalchemy_db

        with app.app_context():
            sqlalchemy_db.create_all()
    _mark(db, DEMO_MARKER)
    log('Seeding the demonstration dataset:')
    # No outer app context: each API call must get its own, or the signed-in
    # user cached on flask.g would carry over between demo users.
    accounts = DemoBuilder(app, db, log=log).build()
    _mark(db, DEMO_SEEDED)
    lines = ['Demo accounts (this demo database only):', '']
    lines += [f'  {title:<18} {role:<18} {email:<38} {password}' for title, role, email, password in accounts]
    text = '\n'.join(lines) + '\n'
    if accounts_file:
        with open(accounts_file, 'w', encoding='utf-8') as handle:
            handle.write(text)
        log(f'Accounts written to {accounts_file}')
    else:
        log(text)
    return accounts


def main(argv=None):
    parser = argparse.ArgumentParser(description='Zehunger demonstration dataset')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status', help='show whether the database is a demo database')
    seed_cmd = sub.add_parser('seed', help='load the demonstration dataset')
    seed_cmd.add_argument('--reset', action='store_true', help='rebuild an existing demo database')
    seed_cmd.add_argument('--accounts-file', help='write demo account passwords to this file')
    args = parser.parse_args(argv)
    try:
        if args.command == 'status':
            app, db, init_database = _load_app()
            init_database()
            print({'demo-seeded': 'Demo database with the demo dataset loaded.',
                   'demo-empty': 'Demo database, dataset not loaded.',
                   'empty': 'Empty database (not marked as a demo).',
                   'real': 'Real database - demo seeding is refused here.'}[database_state(db)])
            return 0
        seed(reset=args.reset, accounts_file=args.accounts_file)
        return 0
    except DemoRefused as exc:
        print(f'Refused: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
