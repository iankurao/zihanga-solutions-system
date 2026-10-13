-- Migration for creating the fly_facility_maintenance table
DROP TABLE IF EXISTS fly_facility_maintenance;

CREATE TABLE fly_facility_maintenance (
    maintenance_id INT AUTO_INCREMENT PRIMARY KEY,
    maintenance_date DATE NOT NULL,
    moat_check ENUM('full', 'low', 'empty') NOT NULL,
    ants_present ENUM('no', 'few', 'many') NOT NULL,
    rodents_present ENUM('no', 'yes') NOT NULL,
    bird_net_ok ENUM('yes', 'damaged') NOT NULL,
    trench_refilled ENUM('yes', 'no') NOT NULL,
    maintenance_notes TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
); 