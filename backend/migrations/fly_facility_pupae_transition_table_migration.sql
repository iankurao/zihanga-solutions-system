-- Migration for creating the fly_facility_pupae_transition table
DROP TABLE IF EXISTS fly_facility_pupae_transition;

CREATE TABLE fly_facility_pupae_transition (
    transition_id INT AUTO_INCREMENT PRIMARY KEY,
    transition_date DATE NOT NULL,
    love_cage_id VARCHAR(255) NOT NULL,
    pupae_weight_added_kg DECIMAL(10, 2) NOT NULL,
    old_pupae_removed_kg DECIMAL(10, 2) NOT NULL,
    dead_flies_removed ENUM('none', 'few', 'many') NOT NULL,
    water_points_checked ENUM('yes', 'some', 'no') NOT NULL,
    new_egg_crates_installed ENUM('yes', 'no') NOT NULL,
    number_of_crates INT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
); 