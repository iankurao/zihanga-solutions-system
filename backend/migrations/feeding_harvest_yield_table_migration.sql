-- To ensure a clean slate, we drop the table if it already exists.
DROP TABLE IF EXISTS feeding_harvest_yield;

-- Migration for creating the feeding_harvest_yield table
CREATE TABLE feeding_harvest_yield (
    harvest_id INT AUTO_INCREMENT PRIMARY KEY,
    harvest_date DATE NOT NULL,
    tray_batch_id VARCHAR(255) NOT NULL,
    instar_stage INT NOT NULL,
    larvae_collected_kg DECIMAL(10, 2) NOT NULL,
    processing_method ENUM('sieving', 'self_harvesting', 'manual', 'other') NOT NULL,
    storage_temperature_celsius DECIMAL(5, 2),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
); 