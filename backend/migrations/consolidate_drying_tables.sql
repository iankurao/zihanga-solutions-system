-- This script consolidates all drying-related data into a single table.

-- Drop all old drying tables to avoid conflicts and foreign key issues.
DROP TABLE IF EXISTS drying_remarks;
DROP TABLE IF EXISTS drying_quality_control;
DROP TABLE IF EXISTS drying_output;
DROP TABLE IF EXISTS drying_input;
DROP TABLE IF EXISTS drying_batches;

-- Create a single, consolidated table for all drying data.
-- All columns are nullable, except for the batch_id, to allow for incremental data entry.
CREATE TABLE drying_batches (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    recorded_by VARCHAR(255),

    -- From Batch Form
    drying_date DATE,
    drying_method VARCHAR(255),
    personnel VARCHAR(255),

    -- From Input Form
    wet_harvested_kg DECIMAL(10, 2),
    wet_placed_for_drying_kg DECIMAL(10, 2),
    dried_by_personnel_kg DECIMAL(10, 2),
    sand_used_kg DECIMAL(10, 2),
    sand_reused_kg DECIMAL(10, 2),
    input_notes TEXT,

    -- From Output Form
    dried_produced_kg DECIMAL(10, 2),
    solar_drying_taken_kg DECIMAL(10, 2),
    stored_in_silo_bag_kg DECIMAL(10, 2),
    sold_kg DECIMAL(10, 2),
    actual_ratio VARCHAR(50),
    yield_percentage DECIMAL(5, 2),
    output_notes TEXT,

    -- From QC Form
    qc_date DATE,
    sand_removal VARCHAR(100),
    contaminants_found VARCHAR(255),
    color_quality VARCHAR(100),
    moisture_level DECIMAL(5, 2),
    qc_personnel VARCHAR(255),
    qc_notes TEXT,

    -- From Review Form
    reviewed_by VARCHAR(255),
    review_date DATE,
    approval_status VARCHAR(50),
    review_comments TEXT
); 