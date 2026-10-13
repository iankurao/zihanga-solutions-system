"""Canonical human-readable identifiers for Phase One production records.

The database migration installs one PostgreSQL sequence per entity and uses
the corresponding sequence in each column default.  Callers should let the
database assign the value in the INSERT statement; they must not calculate a
next value in application code.
"""

BUSINESS_ID_SPECS = {
    "waste_lot": {"prefix": "WL", "sequence": "phase_one_waste_lot_seq"},
    "substrate_batch": {"prefix": "SUB", "sequence": "phase_one_substrate_batch_seq"},
    "production_batch": {"prefix": "BSF", "sequence": "phase_one_production_batch_seq"},
    "harvest": {"prefix": "HRV", "sequence": "phase_one_harvest_seq"},
    "drying_batch": {"prefix": "DRY", "sequence": "phase_one_drying_batch_seq"},
    "product_lot": {"prefix": "LOT", "sequence": "phase_one_product_lot_seq"},
    "inventory_movement": {"prefix": "MOV", "sequence": "phase_one_inventory_movement_seq"},
}


def business_id_expression(entity, date_expression="CURRENT_DATE"):
    """Return a safe SQL expression for a known business-ID entity.

    ``entity`` and ``date_expression`` are internal, allow-listed values.  The
    generated expression is intended for schema defaults, not user input.
    """
    spec = BUSINESS_ID_SPECS[entity]
    return (
        f"'{spec['prefix']}-' || to_char({date_expression}, 'YYYY') || '-' "
        f"|| lpad(nextval('{spec['sequence']}')::text, 5, '0')"
    )