"""Roles and permissions.

A role says what someone may do; their organization/farm/site/facility
assignments (user_*_access) say where. Manager covers organization, farm and
facility managers - the level comes from the assignment. Operator covers
production operators and farmers.
"""

ROLE_LABELS = {
    'super_admin': 'Super admin',
    'manager': 'Manager',
    'operator': 'Production operator / farmer',
    'qc_officer': 'QC officer',
    'inventory_officer': 'Inventory officer',
    'sales_officer': 'Sales officer',
    'viewer': 'Viewer (read only)',
}

PERMISSION_LABELS = {
    'production.write': 'Record waste, substrate, batches, feeding, harvest and drying',
    'quality.decide': 'Record quality checks and approve or reject lots',
    'inventory.write': 'Post stock transfers and dispatches',
    'inventory.adjust': 'Post stock adjustments and wastage',
    'sales.read': 'See customers, orders and deliveries',
    'sales.write': 'Create and change customers, orders and deliveries',
    'alerts.manage': 'Acknowledge and snooze alerts',
    # Super admin only:
    'legacy.read': 'See legacy (pre-traceability) records and analytics',
    'legacy.write': 'Edit legacy sales, deliveries and feedback',
    'setup.manage': 'Manage locations, units, thresholds and users',
}

ROLE_PERMISSIONS = {
    'super_admin': frozenset(PERMISSION_LABELS),
    'manager': frozenset({
        'production.write', 'quality.decide', 'inventory.write', 'inventory.adjust',
        'sales.read', 'sales.write', 'alerts.manage',
    }),
    'operator': frozenset({'production.write', 'alerts.manage'}),
    'qc_officer': frozenset({'quality.decide', 'alerts.manage'}),
    # Write-offs and adjustments stay with managers (segregation of duties).
    'inventory_officer': frozenset({'inventory.write', 'alerts.manage'}),
    'sales_officer': frozenset({'sales.read', 'sales.write', 'alerts.manage'}),
    'viewer': frozenset(),
}

ASSIGNABLE_ROLES = tuple(role for role in ROLE_LABELS if role != 'super_admin')


# Commercial alerts name customers; only roles that may see sales data get them.
COMMERCIAL_ALERT_ENTITIES = ('customer_order', 'customer_delivery')


def roles_with(permission):
    return sorted(role for role, granted in ROLE_PERMISSIONS.items() if permission in granted)
