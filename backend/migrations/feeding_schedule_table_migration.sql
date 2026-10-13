-- Migration for creating the feeding_schedule table
DROP TABLE IF EXISTS feeding_schedule;

CREATE TABLE feeding_schedule (
    schedule_id INT AUTO_INCREMENT PRIMARY KEY,
    feeding_date DATE NOT NULL,
    tray_batch_id VARCHAR(255) NOT NULL,
    larvae_age_days INT NOT NULL,
    larvae_weight_g DECIMAL(10, 2) NOT NULL,
    feed_type VARCHAR(255) NOT NULL,
    feed_quantity_kg DECIMAL(10, 2) NOT NULL,
    start_weight_g DECIMAL(10, 2),
    end_weight_kg DECIMAL(10, 2),
    consumption_g DECIMAL(10, 2),
    operator VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
); 