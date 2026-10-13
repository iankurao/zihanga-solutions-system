-- Migration for creating the feeding_environmental_monitoring table

CREATE TABLE IF NOT EXISTS feeding_environmental_monitoring (
    monitoring_id INT AUTO_INCREMENT PRIMARY KEY,
    monitoring_date DATE NOT NULL,
    monitoring_time TIME NOT NULL,
    tray_facility_id VARCHAR(255) NOT NULL,
    temperature DECIMAL(5, 2) NOT NULL,
    humidity DECIMAL(5, 2) NOT NULL,
    ammonia_odor ENUM('yes', 'no') NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
); 