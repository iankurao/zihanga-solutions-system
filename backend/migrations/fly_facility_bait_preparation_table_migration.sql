-- Migration for creating the fly_facility_bait_preparation table
DROP TABLE IF EXISTS fly_facility_bait_preparation;

CREATE TABLE fly_facility_bait_preparation (
    bait_id INT AUTO_INCREMENT PRIMARY KEY,
    barrel_id VARCHAR(255) NOT NULL,
    bait_type ENUM('frass_mix', 'blood', 'combined') NOT NULL,
    ingredients_added TEXT NOT NULL,
    start_date DATE NOT NULL,
    ready_date DATE NOT NULL,
    used_in_cage_ids VARCHAR(255),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
); 