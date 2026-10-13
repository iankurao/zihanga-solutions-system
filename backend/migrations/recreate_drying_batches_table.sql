-- This script drops all drying-related tables and recreates them
-- to ensure a consistent schema that matches the application's forms.

-- Drop tables in the reverse order of creation to respect foreign key constraints.
DROP TABLE IF EXISTS drying_remarks;
DROP TABLE IF EXISTS drying_quality_control;
DROP TABLE IF EXISTS drying_output;
DROP TABLE IF EXISTS drying_input;
DROP TABLE IF EXISTS drying_batches;

-- 1. Create the new `drying_batches` table with a schema that matches the form.
CREATE TABLE drying_batches (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(255) NOT NULL UNIQUE,
    drying_date DATE NOT NULL,
    drying_method VARCHAR(255) NOT NULL,
    personnel VARCHAR(255) NOT NULL,
    recorded_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Recreate the `drying_input` table.
-- Note: The `batch_id` is now VARCHAR(255) to match the new `drying_batches` table.
CREATE TABLE drying_input (
    input_id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(255) NOT NULL,
    input_weight DECIMAL(10,2) NOT NULL,
    drying_method VARCHAR(100) NOT NULL,
    start_time DATETIME NOT NULL,
    operator VARCHAR(100),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES drying_batches(batch_id)
);

-- 3. Recreate the `drying_output` table.
CREATE TABLE drying_output (
    output_id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(255) NOT NULL,
    output_weight DECIMAL(10,2) NOT NULL,
    by_products VARCHAR(255),
    waste_reduction DECIMAL(5,2),
    end_time DATETIME NOT NULL,
    operator VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES drying_batches(batch_id)
);

-- 4. Recreate the `drying_quality_control` table.
CREATE TABLE drying_quality_control (
    qc_id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(255) NOT NULL,
    qc_time DATETIME NOT NULL,
    moisture_content DECIMAL(5,2),
    contamination_level VARCHAR(100),
    passed BOOLEAN,
    inspector VARCHAR(100),
    remarks TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES drying_batches(batch_id)
);

-- 5. Recreate the `drying_remarks` table.
CREATE TABLE drying_remarks (
    remark_id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(255) NOT NULL,
    remark_time DATETIME NOT NULL,
    remark_text TEXT,
    author VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES drying_batches(batch_id)
); 