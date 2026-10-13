-- Drop the old table if it exists to ensure a clean slate
DROP TABLE IF EXISTS hatchery_feeding;

-- Create the new hatchery_feeding table with the correct columns
CREATE TABLE hatchery_feeding (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id VARCHAR(255) NOT NULL,
    feeding_date DATE NOT NULL,
    feed_per_5g_eggs_grams DECIMAL(10, 2),
    total_feed_used_grams DECIMAL(10, 2),
    days_to_utilize INT,
    feed_type VARCHAR(255),
    feed_source VARCHAR(255),
    distribution_method VARCHAR(255),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
); 