-- Prices on customer order lines: unit_price is the agreed price per kg in the
-- system currency (CURRENCY setting, default KES). Revenue is counted when a
-- delivery is confirmed: delivered kg x the line's unit_price.
--
-- New lines must carry a price (CHECK ... NOT VALID: lines from before prices
-- existed stay valid and can be priced later, until they are dispatched).
-- Price changes are audited through the existing audit trigger on
-- customer_order_lines. Repeatable: safe to run on every start.

ALTER TABLE customer_order_lines ADD COLUMN IF NOT EXISTS unit_price NUMERIC(14, 2);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'customer_order_lines_unit_price_positive') THEN
        ALTER TABLE customer_order_lines
            ADD CONSTRAINT customer_order_lines_unit_price_positive CHECK (unit_price >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'customer_order_lines_unit_price_required') THEN
        ALTER TABLE customer_order_lines
            ADD CONSTRAINT customer_order_lines_unit_price_required CHECK (unit_price IS NOT NULL) NOT VALID;
    END IF;
END $$;
