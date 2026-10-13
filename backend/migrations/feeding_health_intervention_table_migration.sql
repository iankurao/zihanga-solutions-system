-- Migration for creating the feeding_health_intervention table

CREATE TABLE IF NOT EXISTS feeding_health_intervention (
    intervention_id INT AUTO_INCREMENT PRIMARY KEY,
    health_check_date DATE NOT NULL,
    tray_batch_id VARCHAR(255) NOT NULL,
    observed_issue VARCHAR(255) NOT NULL,
    severity ENUM('low', 'medium', 'high') NOT NULL,
    action_taken TEXT NOT NULL,
    follow_up_date DATE,
    resolved ENUM('yes', 'no'),
    comments TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
); 