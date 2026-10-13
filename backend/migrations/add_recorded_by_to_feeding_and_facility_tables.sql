-- Migration: Add 'recorded_by' column to key tables for user tracking

ALTER TABLE feeding_environmental_monitoring
ADD COLUMN recorded_by VARCHAR(255) AFTER notes;

ALTER TABLE fly_facility_cage_monitoring
ADD COLUMN recorded_by VARCHAR(255) AFTER additional_notes;

ALTER TABLE fly_facility_maintenance
ADD COLUMN recorded_by VARCHAR(255) AFTER maintenance_notes; 