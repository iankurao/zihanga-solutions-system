-- Migration: Add 'recorded_by' column to all fly facility tables for user tracking

ALTER TABLE fly_facility_egg_collection
ADD COLUMN recorded_by VARCHAR(255) AFTER notes;

ALTER TABLE fly_facility_bait_preparation
ADD COLUMN recorded_by VARCHAR(255) AFTER notes;

ALTER TABLE fly_facility_pupae_transition
ADD COLUMN recorded_by VARCHAR(255) AFTER notes;

ALTER TABLE fly_facility_cage_monitoring
ADD COLUMN recorded_by VARCHAR(255) AFTER additional_notes;

ALTER TABLE fly_facility_maintenance
ADD COLUMN recorded_by VARCHAR(255) AFTER maintenance_notes; 