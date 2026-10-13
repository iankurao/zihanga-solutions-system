-- Migration: Add 'recorded_by' column to feeding_harvest_yield table

ALTER TABLE feeding_harvest_yield
ADD COLUMN recorded_by VARCHAR(255) AFTER notes; 