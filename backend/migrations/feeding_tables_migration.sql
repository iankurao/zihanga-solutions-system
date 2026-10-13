-- Migration script to replace old feeding tables with new hatchery tables

-- First, backup existing data (if needed)
CREATE TABLE IF NOT EXISTS backup_feeding_schedule AS SELECT * FROM feeding_schedule;
CREATE TABLE IF NOT EXISTS backup_harvest_yield AS SELECT * FROM harvest_yield;
CREATE TABLE IF NOT EXISTS backup_health_intervention AS SELECT * FROM health_intervention;

-- Drop old tables
DROP TABLE IF EXISTS feeding_schedule;
DROP TABLE IF EXISTS harvest_yield;
DROP TABLE IF EXISTS health_intervention;

-- Create new hatchery tables
CREATE TABLE IF NOT EXISTS hatchery_batches (
    batch_id SERIAL PRIMARY KEY,
    batch_number VARCHAR(50) NOT NULL UNIQUE,
    batch_date DATE NOT NULL,
    egg_incubation_date DATE NOT NULL,
    total_eggs_grams DECIMAL(10,2) NOT NULL CHECK (total_eggs_grams > 0),
    expected_hatch_date DATE NOT NULL,
    actual_hatch_date DATE,
    hatch_days INTEGER CHECK (hatch_days > 0),
    supervisor_name VARCHAR(100) NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_dates CHECK (
        batch_date <= egg_incubation_date AND
        egg_incubation_date <= expected_hatch_date AND
        (actual_hatch_date IS NULL OR actual_hatch_date >= egg_incubation_date)
    )
);

CREATE TABLE IF NOT EXISTS hatchery_feeding (
    feeding_id SERIAL PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES hatchery_batches(batch_id),
    feeding_date DATE NOT NULL,
    feed_per_5g_eggs_grams DECIMAL(10,2) NOT NULL CHECK (feed_per_5g_eggs_grams > 0),
    total_feed_used_grams DECIMAL(10,2) NOT NULL CHECK (total_feed_used_grams > 0),
    days_to_utilize INTEGER NOT NULL CHECK (days_to_utilize > 0),
    feed_type VARCHAR(50) NOT NULL CHECK (
        feed_type IN ('brewery_waste', 'wheat_bran', 'potatoes', 'mixed', 'other')
    ),
    feed_source VARCHAR(100),
    distribution_method VARCHAR(100) NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_feeding_date CHECK (
        feeding_date >= (SELECT batch_date FROM hatchery_batches WHERE batch_id = hatchery_feeding.batch_id)
    )
);

CREATE TABLE IF NOT EXISTS hatchery_monitoring (
    monitoring_id SERIAL PRIMARY KEY,
    monitoring_date DATE NOT NULL,
    temperature_c DECIMAL(5,2) NOT NULL CHECK (temperature_c BETWEEN -50 AND 100),
    humidity_percent DECIMAL(5,2) NOT NULL CHECK (humidity_percent BETWEEN 0 AND 100),
    adjustments_made TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hatchery_cleaning (
    cleaning_id SERIAL PRIMARY KEY,
    cleaning_date DATE NOT NULL,
    areas_cleaned TEXT NOT NULL,
    cleaning_materials TEXT NOT NULL,
    cleaning_personnel VARCHAR(100) NOT NULL,
    remarks TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hatchery_problems (
    problem_id SERIAL PRIMARY KEY,
    problem_date DATE NOT NULL,
    problem_identified VARCHAR(50) NOT NULL CHECK (
        problem_identified IN (
            'larvae_escaping', 'high_temperature', 'dry_feed', 
            'feed_not_utilized', 'mites', 'ants', 'rodents', 'other'
        )
    ),
    proposed_solution TEXT NOT NULL,
    responsible_person VARCHAR(100) NOT NULL,
    days_to_implement INTEGER CHECK (days_to_implement >= 0),
    resolution_status VARCHAR(20) CHECK (
        resolution_status IN ('pending', 'in_progress', 'resolved', 'failed')
    ),
    additional_comments TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better query performance
CREATE INDEX idx_hatchery_batches_batch_number ON hatchery_batches(batch_number);
CREATE INDEX idx_hatchery_batches_dates ON hatchery_batches(batch_date, egg_incubation_date, expected_hatch_date);
CREATE INDEX idx_hatchery_feeding_batch_id ON hatchery_feeding(batch_id);
CREATE INDEX idx_hatchery_feeding_dates ON hatchery_feeding(feeding_date);
CREATE INDEX idx_hatchery_monitoring_dates ON hatchery_monitoring(monitoring_date);
CREATE INDEX idx_hatchery_cleaning_dates ON hatchery_cleaning(cleaning_date);
CREATE INDEX idx_hatchery_problems_dates ON hatchery_problems(problem_date);

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers for updated_at
CREATE TRIGGER update_hatchery_batches_updated_at
    BEFORE UPDATE ON hatchery_batches
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_hatchery_feeding_updated_at
    BEFORE UPDATE ON hatchery_feeding
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_hatchery_monitoring_updated_at
    BEFORE UPDATE ON hatchery_monitoring
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_hatchery_cleaning_updated_at
    BEFORE UPDATE ON hatchery_cleaning
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_hatchery_problems_updated_at
    BEFORE UPDATE ON hatchery_problems
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Data migration (if needed)
-- Note: This is a basic migration. You may need to adjust the field mappings based on your data
INSERT INTO hatchery_batches (
    batch_number,
    batch_date,
    egg_incubation_date,
    total_eggs_grams,
    expected_hatch_date,
    supervisor_name,
    notes
)
SELECT DISTINCT
    tray_batch_id,
    MIN(feeding_date),
    MIN(feeding_date),
    SUM(larvae_weight),
    MAX(feeding_date) + INTERVAL '7 days',
    operator,
    'Migrated from old feeding schedule'
FROM backup_feeding_schedule
GROUP BY tray_batch_id, operator;

-- Clean up backup tables (optional)
-- DROP TABLE IF EXISTS backup_feeding_schedule;
-- DROP TABLE IF EXISTS backup_harvest_yield;
-- DROP TABLE IF EXISTS backup_health_intervention; 