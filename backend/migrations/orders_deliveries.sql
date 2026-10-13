-- Phase One Step 15: traceable commercial flow.
--
--   Customer -> Customer Order -> Order Lines -> Allocations (Product Lot at
--   an Inventory Location) -> Customer Delivery -> Delivery Lines
--
-- An allocation reserves lot stock at one location; it does not move stock.
-- Dispatching a delivery posts one DISPATCH inventory movement per line, so
-- stock is still derived only from the inventory ledger.  The legacy free-text
-- `sales` and `deliveries` tables are left untouched as history.
-- Additive and safe to run at every application startup.

CREATE SEQUENCE IF NOT EXISTS phase_one_customer_order_seq AS BIGINT;
CREATE SEQUENCE IF NOT EXISTS phase_one_customer_delivery_seq AS BIGINT;

CREATE TABLE IF NOT EXISTS customer_orders (
    id SERIAL PRIMARY KEY,
    business_id VARCHAR(30) NOT NULL UNIQUE DEFAULT (
        'ORD-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
        lpad(nextval('phase_one_customer_order_seq')::text, 5, '0')
    ),
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE RESTRICT,
    order_date DATE NOT NULL DEFAULT CURRENT_DATE,
    requested_delivery_date DATE,
    customer_reference VARCHAR(60),
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'FULFILLED', 'CANCELLED')),
    cancel_reason TEXT,
    cancelled_at TIMESTAMPTZ,
    notes TEXT,
    created_by VARCHAR(100) NOT NULL,
    created_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_customer_orders_farm_status
    ON customer_orders(farm_id, status);
CREATE INDEX IF NOT EXISTS idx_customer_orders_customer
    ON customer_orders(customer_id);

CREATE TABLE IF NOT EXISTS customer_order_lines (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES customer_orders(id) ON DELETE RESTRICT,
    line_no INTEGER NOT NULL CHECK (line_no > 0),
    product_type VARCHAR(50) NOT NULL CHECK (length(trim(product_type)) > 0),
    quantity_kg NUMERIC(14, 3) NOT NULL CHECK (quantity_kg > 0),
    unit VARCHAR(16) NOT NULL DEFAULT 'kg' CHECK (unit = 'kg'),
    notes TEXT,
    UNIQUE (order_id, line_no)
);

CREATE TABLE IF NOT EXISTS order_allocations (
    id SERIAL PRIMARY KEY,
    order_line_id INTEGER NOT NULL REFERENCES customer_order_lines(id) ON DELETE RESTRICT,
    product_lot_id INTEGER NOT NULL REFERENCES product_lots(id) ON DELETE RESTRICT,
    location_id INTEGER NOT NULL REFERENCES inventory_locations(id) ON DELETE RESTRICT,
    quantity_kg NUMERIC(14, 3) NOT NULL CHECK (quantity_kg > 0),
    -- Undelivered quantity handed back to stock (order cancelled or the
    -- allocation released).  Outstanding = quantity - dispatched - released.
    released_kg NUMERIC(14, 3) NOT NULL DEFAULT 0 CHECK (released_kg >= 0),
    released_at TIMESTAMPTZ,
    release_reason TEXT,
    created_by VARCHAR(100) NOT NULL,
    created_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (released_kg <= quantity_kg)
);

CREATE INDEX IF NOT EXISTS idx_order_allocations_line
    ON order_allocations(order_line_id);
CREATE INDEX IF NOT EXISTS idx_order_allocations_lot_location
    ON order_allocations(product_lot_id, location_id);

CREATE TABLE IF NOT EXISTS customer_deliveries (
    id SERIAL PRIMARY KEY,
    business_id VARCHAR(30) NOT NULL UNIQUE DEFAULT (
        'DEL-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
        lpad(nextval('phase_one_customer_delivery_seq')::text, 5, '0')
    ),
    order_id INTEGER NOT NULL REFERENCES customer_orders(id) ON DELETE RESTRICT,
    status VARCHAR(20) NOT NULL DEFAULT 'DISPATCHED'
        CHECK (status IN ('DISPATCHED', 'DELIVERED')),
    dispatched_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMPTZ,
    received_by VARCHAR(100),
    vehicle VARCHAR(60),
    driver VARCHAR(100),
    notes TEXT,
    created_by VARCHAR(100) NOT NULL,
    created_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (status <> 'DELIVERED' OR delivered_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_customer_deliveries_order
    ON customer_deliveries(order_id);

CREATE TABLE IF NOT EXISTS customer_delivery_lines (
    id SERIAL PRIMARY KEY,
    delivery_id INTEGER NOT NULL REFERENCES customer_deliveries(id) ON DELETE RESTRICT,
    allocation_id INTEGER NOT NULL REFERENCES order_allocations(id) ON DELETE RESTRICT,
    quantity_kg NUMERIC(14, 3) NOT NULL CHECK (quantity_kg > 0),
    inventory_movement_id INTEGER NOT NULL UNIQUE
        REFERENCES inventory_movements(id) ON DELETE RESTRICT,
    UNIQUE (delivery_id, allocation_id)
);

CREATE INDEX IF NOT EXISTS idx_customer_delivery_lines_allocation
    ON customer_delivery_lines(allocation_id);
