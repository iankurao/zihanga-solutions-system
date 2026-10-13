-- Migration: Create drying section tables with manual batch_id

-- IMPORTANT: To apply this change, you must first DROP the existing drying tables
-- in the following order due to foreign key dependencies, then run the CREATE statements.
--
-- DROP TABLE IF EXISTS drying_remarks;
-- DROP TABLE IF EXISTS drying_quality_control;
-- DROP TABLE IF EXISTS drying_output;
-- DROP TABLE IF EXISTS drying_input;
-- DROP TABLE IF EXISTS drying_batches;

-- 1. Table: drying_batches (with manual batch_id)
CREATE TABLE IF NOT EXISTS drying_batches (
    batch_id INT PRIMARY KEY,
    hatchery_batch_id INT NULL,
    start_date DATE,
    operator VARCHAR(100),
    personnel VARCHAR(100),
    drying_method VARCHAR(100),
    status VARCHAR(50) DEFAULT 'in_progress',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- If the table already exists, run these to update it:
-- ALTER TABLE drying_batches MODIFY hatchery_batch_id INT NULL;
-- ALTER TABLE drying_batches MODIFY start_date DATE NULL;
-- ALTER TABLE drying_batches MODIFY operator VARCHAR(100) NULL;
-- ALTER TABLE drying_batches ADD COLUMN personnel VARCHAR(100);
-- ALTER TABLE drying_batches ADD COLUMN drying_method VARCHAR(100);

-- 2. Table: drying_input
CREATE TABLE IF NOT EXISTS drying_input (
    input_id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id INT NOT NULL,
    input_weight DECIMAL(10,2) NOT NULL,
    drying_method VARCHAR(100) NOT NULL,
    start_time DATETIME NOT NULL,
    operator VARCHAR(100),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES drying_batches(batch_id)
);

-- 3. Table: drying_output
CREATE TABLE IF NOT EXISTS drying_output (
    output_id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id INT NOT NULL,
    output_weight DECIMAL(10,2) NOT NULL,
    by_products VARCHAR(255),
    waste_reduction DECIMAL(5,2),
    end_time DATETIME NOT NULL,
    operator VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES drying_batches(batch_id)
);

-- 4. Table: drying_quality_control
CREATE TABLE IF NOT EXISTS drying_quality_control (
    qc_id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id INT NOT NULL,
    qc_time DATETIME NOT NULL,
    moisture_content DECIMAL(5,2),
    contamination_level VARCHAR(100),
    passed BOOLEAN,
    inspector VARCHAR(100),
    remarks TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES drying_batches(batch_id)
);

-- 5. Table: drying_remarks
CREATE TABLE IF NOT EXISTS drying_remarks (
    remark_id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id INT NOT NULL,
    remark_time DATETIME NOT NULL,
    remark_text TEXT,
    author VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES drying_batches(batch_id)
); 