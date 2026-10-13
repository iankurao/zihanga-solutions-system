import psycopg2
from psycopg2 import sql
import logging
from pathlib import Path
from backend.config import DB_CONFIG

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_database():
    """Initialize the database and create all necessary tables."""
    try:
        # SSL configuration for database connection
        db_config = DB_CONFIG.copy()
        if 'sslmode' in db_config:
            del db_config['sslmode']
        connection = psycopg2.connect(**db_config)
        connection.autocommit = True
        
        cursor = connection.cursor()
        logger.info(f"Connected to database {DB_CONFIG['database']}")
        
        # Create all necessary tables
        create_tables(cursor)
        
        connection.commit()
        logger.info("Database initialization completed successfully")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise
    finally:
        if 'connection' in locals() and connection:
            cursor.close()
            connection.close()
            logger.info("Database connection closed")

def create_tables(cursor):
    """Create all necessary tables in the database."""
    
    # Create users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            full_name VARCHAR(100) NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(20) DEFAULT 'viewer',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_username ON users(username)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_email ON users(email)
    """)
    
    # Create waste_sourcing table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS waste_sourcing (
            id SERIAL PRIMARY KEY,
            collection_date DATE NOT NULL,
            collection_time TIME NOT NULL,
            source_type VARCHAR(50) NOT NULL,
            source_name VARCHAR(100) NOT NULL,
            waste_type VARCHAR(50) NOT NULL,
            waste_weight DECIMAL(10,2) NOT NULL,
            segregation_status VARCHAR(20) NOT NULL,
            collection_personnel VARCHAR(100) NOT NULL,
            contaminants_found TEXT,
            collection_notes TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_collection_date ON waste_sourcing(collection_date)
    """)
    
    # Create storage_records table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS storage_records (
            id SERIAL PRIMARY KEY,
            storage_date DATE NOT NULL,
            storage_method VARCHAR(50) NOT NULL,
            storage_conditions VARCHAR(100) NOT NULL,
            storage_duration INT NOT NULL,
            planned_utilization VARCHAR(100) NOT NULL,
            storage_observations TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_storage_date ON storage_records(storage_date)
    """)
    
    # Create processing_records table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processing_records (
            id SERIAL PRIMARY KEY,
            processing_date DATE NOT NULL,
            processing_type VARCHAR(50) NOT NULL,
            processing_method VARCHAR(100) NOT NULL,
            waste_processed DECIMAL(10,2) NOT NULL,
            waste_reduction DECIMAL(10,2),
            processing_remarks TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_processing_date ON processing_records(processing_date)
    """)
    
    # Create waste_monitoring table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS waste_monitoring (
            id SERIAL PRIMARY KEY,
            monitoring_date DATE NOT NULL,
            monitoring_time TIME NOT NULL,
            temperature DECIMAL(5,2) NOT NULL,
            water_consistency VARCHAR(20) NOT NULL,
            odor_level VARCHAR(20) NOT NULL,
            pest_presence VARCHAR(20) NOT NULL,
            pest_details TEXT,
            mitigation_actions TEXT,
            remarks TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_monitoring_date_waste_monitoring ON waste_monitoring(monitoring_date)
    """)
    
    # Create environmental_monitoring_larvaefeeding table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS environmental_monitoring_larvaefeeding (
            id SERIAL PRIMARY KEY,
            monitoring_date DATE NOT NULL,
            monitoring_time TIME NOT NULL,
            tray_facility_id VARCHAR(50) NOT NULL,
            temperature DECIMAL(5,2) NOT NULL,
            humidity DECIMAL(5,2) NOT NULL,
            ammonia_odor VARCHAR(10) NOT NULL,
            notes TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_monitoring_date_larvae ON environmental_monitoring_larvaefeeding(monitoring_date)
    """)
    
    # Create substrate_preparation table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS substrate_preparation (
            id SERIAL PRIMARY KEY,
            batch_no VARCHAR(50) NOT NULL,
            prep_date DATE NOT NULL,
            organic_waste_source VARCHAR(100) NOT NULL,
            moisture_consistency VARCHAR(20) NOT NULL,
            waste_particle_size VARCHAR(20) NOT NULL,
            foreign_matter VARCHAR(10) NOT NULL,
            substrate_introduced_kg DECIMAL(10,2),
            handler_operator VARCHAR(100) NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_prep_date ON substrate_preparation(prep_date)
    """)
    
    # Create health_intervention table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS health_intervention (
            id SERIAL PRIMARY KEY,
            health_date DATE NOT NULL,
            tray_batch_id VARCHAR(50) NOT NULL,
            observed_issue VARCHAR(255) NOT NULL,
            severity VARCHAR(20) NOT NULL,
            follow_up_date DATE,
            resolved VARCHAR(10),
            action_taken TEXT NOT NULL,
            comments TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_health_date ON health_intervention(health_date)
    """)
    
    # Create harvest_yield table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS harvest_yield (
            id SERIAL PRIMARY KEY,
            harvest_date DATE NOT NULL,
            tray_batch_id VARCHAR(50) NOT NULL,
            instar_stage VARCHAR(10) NOT NULL,
            larvae_collected DECIMAL(10,2) NOT NULL,
            processing_method VARCHAR(50) NOT NULL,
            storage_temp DECIMAL(5,2),
            notes TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_harvest_date ON harvest_yield(harvest_date)
    """)
    
    # Create feeding_schedule table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feeding_schedule (
            id SERIAL PRIMARY KEY,
            feeding_date DATE NOT NULL,
            tray_batch_id VARCHAR(50) NOT NULL,
            larvae_age_days INT NOT NULL,
            larvae_weight DECIMAL(10,2),
            feed_type VARCHAR(50) NOT NULL,
            feed_quantity DECIMAL(10,2) NOT NULL,
            start_weight DECIMAL(10,2),
            end_weight DECIMAL(10,2),
            consumption DECIMAL(10,2),
            operator VARCHAR(100) NOT NULL,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_feeding_date ON feeding_schedule(feeding_date)
    """)
    
    # Create cage_monitoring table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cage_monitoring (
            id SERIAL PRIMARY KEY,
            monitoring_date DATE NOT NULL,
            cage_id VARCHAR(50) NOT NULL,
            temperature DECIMAL(5,2) NOT NULL,
            humidity DECIMAL(5,2) NOT NULL,
            lighting_hours VARCHAR(10) NOT NULL,
            ventilation_ok VARCHAR(10) NOT NULL,
            cage_cleaned VARCHAR(10) NOT NULL,
            dead_flies_removed VARCHAR(10),
            cage_damage VARCHAR(20) NOT NULL,
            damage_notes TEXT,
            additional_notes TEXT,
            cages_damaged_list TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migrate existing table: change lighting_hours to text, drop NOT NULL on dead_flies_removed, add cages_damaged_list
    cursor.execute("""
        DO $$
        BEGIN
            BEGIN
                ALTER TABLE cage_monitoring ALTER COLUMN lighting_hours TYPE VARCHAR(10) USING lighting_hours::VARCHAR;
            EXCEPTION WHEN others THEN NULL;
            END;
            BEGIN
                ALTER TABLE cage_monitoring ALTER COLUMN dead_flies_removed DROP NOT NULL;
            EXCEPTION WHEN others THEN NULL;
            END;
            BEGIN
                ALTER TABLE cage_monitoring ADD COLUMN cages_damaged_list TEXT;
            EXCEPTION WHEN duplicate_column THEN NULL;
            END;
        END $$;
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_monitoring_date_cage ON cage_monitoring(monitoring_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_cage_id ON cage_monitoring(cage_id)
    """)
    
    # Create facility_maintenance table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS facility_maintenance (
            id SERIAL PRIMARY KEY,
            maintenance_date DATE NOT NULL,
            moat_check VARCHAR(20) NOT NULL,
            ants_present VARCHAR(20) NOT NULL,
            rodents_present VARCHAR(10) NOT NULL,
            bird_net_ok VARCHAR(20) NOT NULL,
            trench_refilled VARCHAR(10) NOT NULL,
            maintenance_notes TEXT NOT NULL,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_maintenance_date ON facility_maintenance(maintenance_date)
    """)
    
    # Create pupae_transition table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pupae_transition (
            id SERIAL PRIMARY KEY,
            transition_date DATE NOT NULL,
            love_cage_id VARCHAR(50) NOT NULL,
            pupae_weight_added DECIMAL(10,2) NOT NULL,
            old_pupae_removed DECIMAL(10,2) NOT NULL,
            dead_flies_removed VARCHAR(20) NOT NULL,
            water_points_checked VARCHAR(20) NOT NULL,
            new_egg_crates_installed VARCHAR(10) NOT NULL,
            number_of_crates INT,
            notes TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_transition_date ON pupae_transition(transition_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_love_cage_id ON pupae_transition(love_cage_id)
    """)
    
    # Create egg_collection table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS egg_collection (
            id SERIAL PRIMARY KEY,
            collection_date DATE NOT NULL,
            collection_time VARCHAR(50) NOT NULL,
            cage_id VARCHAR(50) NOT NULL,
            eggs_collected DECIMAL(10,2) NOT NULL,
            bait_replaced VARCHAR(10) NOT NULL,
            eggs_intact VARCHAR(20) NOT NULL,
            collector_name VARCHAR(100) NOT NULL,
            collection_method VARCHAR(50) NOT NULL,
            notes TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_collection_date_egg ON egg_collection(collection_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_cage_id_egg ON egg_collection(cage_id)
    """)
    
    # Create bait_preparation table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bait_preparation (
            id SERIAL PRIMARY KEY,
            barrel_id VARCHAR(50) NOT NULL,
            bait_type VARCHAR(50) NOT NULL,
            ingredients_added TEXT NOT NULL,
            start_date DATE NOT NULL,
            ready_date DATE NOT NULL,
            used_in_cage_ids TEXT,
            notes TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_barrel_id ON bait_preparation(barrel_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_start_date_bait ON bait_preparation(start_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_ready_date_bait ON bait_preparation(ready_date)
    """)
    
    # Create hatchery_batches table (schema matches app.py expectations)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hatchery_batches (
            id SERIAL PRIMARY KEY,
            batch_number VARCHAR(50) NOT NULL,
            batch_date DATE NOT NULL,
            egg_incubation_date DATE NOT NULL,
            total_eggs_grams DECIMAL(10,2) NOT NULL,
            expected_hatch_date DATE NOT NULL,
            actual_hatch_date DATE,
            hatch_days INTEGER,
            supervisor_name VARCHAR(100) NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create hatchery_feeding table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hatchery_feeding (
            id SERIAL PRIMARY KEY,
            batch_id VARCHAR(50) NOT NULL,
            feeding_date DATE NOT NULL,
            feed_per_5g_eggs_grams DECIMAL(10,2),
            total_feed_used_grams DECIMAL(10,2),
            days_to_utilize INTEGER,
            feed_type VARCHAR(100),
            feed_source VARCHAR(100),
            distribution_method VARCHAR(100),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create hatchery_monitoring table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hatchery_monitoring (
            id SERIAL PRIMARY KEY,
            monitoring_date DATE NOT NULL,
            temperature_c DECIMAL(5,2) NOT NULL,
            humidity_percent DECIMAL(5,2) NOT NULL,
            adjustments_made TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create hatchery_cleaning table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hatchery_cleaning (
            id SERIAL PRIMARY KEY,
            cleaning_date DATE NOT NULL,
            areas_cleaned TEXT NOT NULL,
            cleaning_materials TEXT NOT NULL,
            cleaning_personnel VARCHAR(100) NOT NULL,
            remarks TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create hatchery_problems table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hatchery_problems (
            id SERIAL PRIMARY KEY,
            problem_date DATE NOT NULL,
            problem_identified TEXT NOT NULL,
            proposed_solution TEXT NOT NULL,
            responsible_person VARCHAR(100) NOT NULL,
            days_to_implement INTEGER,
            resolution_status VARCHAR(50),
            additional_comments TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create hatchery_health_interventions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hatchery_health_interventions (
            id SERIAL PRIMARY KEY,
            health_date DATE NOT NULL,
            health_issue TEXT NOT NULL,
            severity VARCHAR(20) NOT NULL,
            action_taken TEXT NOT NULL,
            follow_up_date DATE,
            resolved VARCHAR(10),
            comments TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create customers table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            contact VARCHAR(50),
            email VARCHAR(100),
            address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_customer_name ON customers(name)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_customer_email ON customers(email)
    """)
    
    # Create sales table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            customer_id INTEGER REFERENCES customers(id) ON DELETE RESTRICT,
            product VARCHAR(100) NOT NULL,
            quantity DECIMAL(10,2) NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales(customer_id)
    """)
    
    # Create customer_feedback table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer_feedback (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            customer_id INTEGER REFERENCES customers(id) ON DELETE RESTRICT,
            feedback TEXT NOT NULL,
            rating INTEGER CHECK (rating >= 1 AND rating <= 5),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_feedback_date ON customer_feedback(date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_feedback_customer ON customer_feedback(customer_id)
    """)

    # Create deliveries table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deliveries (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            customer_id INTEGER REFERENCES customers(id) ON DELETE RESTRICT,
            product VARCHAR(100),
            quantity DECIMAL(10,2),
            status VARCHAR(50) NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create drying_batches table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drying_batches (
            id SERIAL PRIMARY KEY,
            batch_id VARCHAR(50) UNIQUE NOT NULL,
            drying_date DATE NOT NULL,
            drying_method VARCHAR(100) NOT NULL,
            personnel VARCHAR(100) NOT NULL,
            status VARCHAR(50) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create drying_input table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drying_input (
            id SERIAL PRIMARY KEY,
            batch_id VARCHAR(50) NOT NULL,
            wet_harvested_kg DECIMAL(10,2),
            wet_placed_for_drying_kg DECIMAL(10,2),
            dried_by_personnel_kg DECIMAL(10,2),
            sand_used_kg DECIMAL(10,2),
            sand_reused_kg DECIMAL(10,2),
            notes TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create drying_output table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drying_output (
            id SERIAL PRIMARY KEY,
            batch_id VARCHAR(50) NOT NULL,
            dried_produced_kg DECIMAL(10,2) NOT NULL,
            solar_drying_taken_kg DECIMAL(10,2),
            stored_in_silo_bag_kg DECIMAL(10,2),
            sold_kg DECIMAL(10,2),
            actual_ratio VARCHAR(50),
            yield_percentage DECIMAL(5,2),
            notes TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create drying_quality_control table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drying_quality_control (
            id SERIAL PRIMARY KEY,
            batch_id VARCHAR(50) NOT NULL,
            qc_date DATE NOT NULL,
            sand_removal VARCHAR(50) NOT NULL,
            contaminants_found TEXT,
            color_quality VARCHAR(50) NOT NULL,
            moisture_level VARCHAR(50) NOT NULL,
            qc_personnel VARCHAR(100) NOT NULL,
            notes TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create drying_review_approval table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drying_review_approval (
            id SERIAL PRIMARY KEY,
            batch_id VARCHAR(50) NOT NULL,
            reviewed_by VARCHAR(100) NOT NULL,
            review_date DATE NOT NULL,
            approval_status VARCHAR(50) NOT NULL,
            comments TEXT,
            recorded_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Apply additive, repeatable schema changes after the operational tables
    # exist.  The migration only adds columns/indexes/tables and backfills
    # identifiers; it never drops or renames legacy fields.
    migration_path = Path(__file__).parent / "migrations" / "phase_one_business_identifiers.sql"
    cursor.execute(migration_path.read_text(encoding="utf-8"))
    chain_migration_path = Path(__file__).parent / "migrations" / "waste_to_substrate_chain.sql"
    cursor.execute(chain_migration_path.read_text(encoding="utf-8"))
    location_migration_path = Path(__file__).parent / "migrations" / "farm_site_facility.sql"
    cursor.execute(location_migration_path.read_text(encoding="utf-8"))
    production_chain_migration_path = Path(__file__).parent / "migrations" / "production_batch_chain.sql"
    cursor.execute(production_chain_migration_path.read_text(encoding="utf-8"))
    events_migration_path = Path(__file__).parent / "migrations" / "production_events.sql"
    cursor.execute(events_migration_path.read_text(encoding="utf-8"))
    drying_chain_migration_path = Path(__file__).parent / "migrations" / "drying_chain.sql"
    cursor.execute(drying_chain_migration_path.read_text(encoding="utf-8"))
    product_lot_chain_migration_path = Path(__file__).parent / "migrations" / "product_lot_chain.sql"
    cursor.execute(product_lot_chain_migration_path.read_text(encoding="utf-8"))
    waste_lot_scope_migration_path = Path(__file__).parent / "migrations" / "waste_lot_scope.sql"
    cursor.execute(waste_lot_scope_migration_path.read_text(encoding="utf-8"))
    inventory_ledger_migration_path = Path(__file__).parent / "migrations" / "inventory_ledger.sql"
    cursor.execute(inventory_ledger_migration_path.read_text(encoding="utf-8"))
    orders_migration_path = Path(__file__).parent / "migrations" / "orders_deliveries.sql"
    cursor.execute(orders_migration_path.read_text(encoding="utf-8"))

if __name__ == "__main__":
    init_database()
