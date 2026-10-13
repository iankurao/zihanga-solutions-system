-- Migration for creating the fly_facility_egg_collection table
DROP TABLE IF EXISTS fly_facility_egg_collection;

CREATE TABLE fly_facility_egg_collection (
    collection_id INT AUTO_INCREMENT PRIMARY KEY,
    collection_date DATE NOT NULL,
    collection_time ENUM('early_morning', 'late_evening', 'other') NOT NULL,
    cage_id VARCHAR(255) NOT NULL,
    eggs_collected_g DECIMAL(10, 2) NOT NULL,
    bait_replaced ENUM('yes', 'no') NOT NULL,
    eggs_intact ENUM('yes', 'some', 'many') NOT NULL,
    collector_name VARCHAR(255) NOT NULL,
    collection_method ENUM('razor', 'specialized', 'manual') NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
); 