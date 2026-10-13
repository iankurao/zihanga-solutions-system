-- Migration for creating the fly_facility_cage_monitoring table
DROP TABLE IF EXISTS fly_facility_cage_monitoring;

CREATE TABLE fly_facility_cage_monitoring (
    monitoring_id INT AUTO_INCREMENT PRIMARY KEY,
    monitoring_date DATE NOT NULL,
    cage_id VARCHAR(255) NOT NULL,
    temperature DECIMAL(4, 1) NOT NULL,
    humidity DECIMAL(4, 1) NOT NULL,
    lighting_hours DECIMAL(4, 1) NOT NULL,
    ventilation_ok ENUM('yes', 'no') NOT NULL,
    cage_cleaned ENUM('yes', 'no') NOT NULL,
    dead_flies_removed ENUM('yes', 'no') NOT NULL,
    cage_damage ENUM('no', 'minor', 'major') NOT NULL,
    damage_notes TEXT,
    additional_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
); 