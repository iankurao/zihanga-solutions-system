-- Migration: Add 'recorded_by' column to feeding_health_intervention table

ALTER TABLE feeding_health_intervention
ADD COLUMN recorded_by VARCHAR(255) AFTER comments; 