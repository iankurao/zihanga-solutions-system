-- Zehunger Solutions ERP Schema v2.0
-- Circular Economy Waste-to-Value System
-- Created: October 2025

-- ========================================
-- WASTE AGGREGATION MODULE
-- ========================================

CREATE TABLE IF NOT EXISTS waste_sources (
    id SERIAL PRIMARY KEY,
    source_code VARCHAR(20) UNIQUE NOT NULL,
    source_name VARCHAR(100) NOT NULL,
    source_type VARCHAR(50) NOT NULL,
    contact_person VARCHAR(100),
    phone VARCHAR(20),
    email VARCHAR(100),
    location_address TEXT,
    gps_latitude DECIMAL(10,8),
    gps_longitude DECIMAL(11,8),
    contract_status VARCHAR(20) DEFAULT 'active',
    avg_weekly_waste_kg DECIMAL(10,2),
    waste_types TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_waste_sources_type ON waste_sources(source_type);
CREATE INDEX IF NOT EXISTS idx_waste_sources_status ON waste_sources(contract_status);

CREATE TABLE IF NOT EXISTS waste_collection_runs (
    id SERIAL PRIMARY KEY,
    run_code VARCHAR(20) UNIQUE NOT NULL,
    run_date DATE NOT NULL,
    vehicle_id VARCHAR(20),
    driver_name VARCHAR(100),
    route_name VARCHAR(100),
    planned_sources TEXT,
    status VARCHAR(20) DEFAULT 'planned',
    total_weight_kg DECIMAL(10,2),
    start_time TIME,
    end_time TIME,
    notes TEXT,
    recorded_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_collection_runs_date ON waste_collection_runs(run_date);
CREATE INDEX IF NOT EXISTS idx_collection_runs_status ON waste_collection_runs(status);

CREATE TABLE IF NOT EXISTS waste_collection_items (
    id SERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES waste_collection_runs(id),
    waste_source_id INTEGER REFERENCES waste_sources(id),
    lot_code VARCHAR(30) UNIQUE NOT NULL,
    collection_time TIME,
    waste_type VARCHAR(50) NOT NULL,
    weight_kg DECIMAL(10,2) NOT NULL,
    moisture_content DECIMAL(5,2),
    quality_grade VARCHAR(10),
    contamination_level VARCHAR(20),
    rejection_reason TEXT,
    photos_url TEXT,
    recorded_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_collection_items_lot ON waste_collection_items(lot_code);
CREATE INDEX IF NOT EXISTS idx_collection_items_source ON waste_collection_items(waste_source_id);

-- ========================================
-- BSF PRODUCTION LIFECYCLE MODULE
-- ========================================

CREATE TABLE IF NOT EXISTS substrate_batches (
    id SERIAL PRIMARY KEY,
    batch_code VARCHAR(30) UNIQUE NOT NULL,
    preparation_date DATE NOT NULL,
    waste_lot_ids TEXT,
    total_input_weight_kg DECIMAL(10,2),
    moisture_adjusted_to DECIMAL(5,2),
    particle_size VARCHAR(20),
    additives_used TEXT,
    output_weight_kg DECIMAL(10,2),
    quality_approved BOOLEAN DEFAULT FALSE,
    approved_by VARCHAR(100),
    notes TEXT,
    recorded_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_substrate_batches_code ON substrate_batches(batch_code);
CREATE INDEX IF NOT EXISTS idx_substrate_batches_date ON substrate_batches(preparation_date);

CREATE TABLE IF NOT EXISTS production_batches (
    id SERIAL PRIMARY KEY,
    batch_code VARCHAR(30) UNIQUE NOT NULL,
    substrate_batch_id INTEGER REFERENCES substrate_batches(id),
    start_date DATE NOT NULL,
    current_stage VARCHAR(20) NOT NULL,
    tray_ids TEXT,
    initial_egg_weight_g DECIMAL(10,2),
    estimated_larvae_count INTEGER,
    expected_harvest_date DATE,
    actual_harvest_date DATE,
    harvest_weight_kg DECIMAL(10,2),
    frass_weight_kg DECIMAL(10,2),
    mortality_percentage DECIMAL(5,2),
    status VARCHAR(20) DEFAULT 'active',
    notes TEXT,
    recorded_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_production_batches_code ON production_batches(batch_code);
CREATE INDEX IF NOT EXISTS idx_production_batches_stage ON production_batches(current_stage);
CREATE INDEX IF NOT EXISTS idx_production_batches_status ON production_batches(status);

CREATE TABLE IF NOT EXISTS lifecycle_events (
    id SERIAL PRIMARY KEY,
    production_batch_id INTEGER REFERENCES production_batches(id),
    event_date DATE NOT NULL,
    event_time TIME,
    event_type VARCHAR(50) NOT NULL,
    from_stage VARCHAR(20),
    to_stage VARCHAR(20),
    details TEXT,
    recorded_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_lifecycle_events_batch ON lifecycle_events(production_batch_id);
CREATE INDEX IF NOT EXISTS idx_lifecycle_events_date ON lifecycle_events(event_date);

CREATE TABLE IF NOT EXISTS product_lots (
    id SERIAL PRIMARY KEY,
    lot_code VARCHAR(30) UNIQUE NOT NULL,
    production_batch_id INTEGER REFERENCES production_batches(id),
    product_type VARCHAR(50) NOT NULL,
    processing_date DATE NOT NULL,
    quantity_kg DECIMAL(10,2) NOT NULL,
    protein_content_percent DECIMAL(5,2),
    moisture_percent DECIMAL(5,2),
    quality_grade VARCHAR(10),
    storage_location VARCHAR(100),
    expiry_date DATE,
    available_quantity_kg DECIMAL(10,2),
    unit_price DECIMAL(10,2),
    status VARCHAR(20) DEFAULT 'available',
    recorded_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_product_lots_code ON product_lots(lot_code);
CREATE INDEX IF NOT EXISTS idx_product_lots_type ON product_lots(product_type);
CREATE INDEX IF NOT EXISTS idx_product_lots_status ON product_lots(status);

-- ========================================
-- FARMER HUB MODULE
-- ========================================

CREATE TABLE IF NOT EXISTS farmer_profiles (
    id SERIAL PRIMARY KEY,
    farmer_code VARCHAR(20) UNIQUE NOT NULL,
    user_id INTEGER REFERENCES users(user_id),
    full_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    email VARCHAR(100),
    national_id VARCHAR(50),
    gender VARCHAR(10),
    date_of_birth DATE,
    farm_name VARCHAR(100),
    farm_location TEXT,
    farm_size_acres DECIMAL(10,2),
    gps_latitude DECIMAL(10,8),
    gps_longitude DECIMAL(11,8),
    farming_type VARCHAR(50),
    years_of_experience INTEGER,
    registration_date DATE DEFAULT CURRENT_DATE,
    status VARCHAR(20) DEFAULT 'pending',
    approved_by VARCHAR(100),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_farmer_profiles_code ON farmer_profiles(farmer_code);
CREATE INDEX IF NOT EXISTS idx_farmer_profiles_status ON farmer_profiles(status);
CREATE INDEX IF NOT EXISTS idx_farmer_profiles_type ON farmer_profiles(farming_type);

CREATE TABLE IF NOT EXISTS training_programs (
    id SERIAL PRIMARY KEY,
    program_code VARCHAR(20) UNIQUE NOT NULL,
    program_name VARCHAR(100) NOT NULL,
    description TEXT,
    duration_hours INTEGER,
    target_audience VARCHAR(100),
    prerequisites TEXT,
    certification_offered BOOLEAN DEFAULT FALSE,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_training_programs_code ON training_programs(program_code);

CREATE TABLE IF NOT EXISTS farmer_training_sessions (
    id SERIAL PRIMARY KEY,
    session_code VARCHAR(20) UNIQUE NOT NULL,
    program_id INTEGER REFERENCES training_programs(id),
    session_date DATE NOT NULL,
    start_time TIME,
    end_time TIME,
    location VARCHAR(200),
    trainer_name VARCHAR(100),
    max_participants INTEGER,
    status VARCHAR(20) DEFAULT 'scheduled',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_training_sessions_date ON farmer_training_sessions(session_date);
CREATE INDEX IF NOT EXISTS idx_training_sessions_program ON farmer_training_sessions(program_id);

CREATE TABLE IF NOT EXISTS farmer_enrollments (
    id SERIAL PRIMARY KEY,
    farmer_id INTEGER REFERENCES farmer_profiles(id),
    session_id INTEGER REFERENCES farmer_training_sessions(id),
    enrollment_date DATE DEFAULT CURRENT_DATE,
    attendance_status VARCHAR(20) DEFAULT 'enrolled',
    assessment_score DECIMAL(5,2),
    certification_issued BOOLEAN DEFAULT FALSE,
    certification_date DATE,
    certificate_number VARCHAR(50),
    feedback TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(farmer_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_enrollments_farmer ON farmer_enrollments(farmer_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_session ON farmer_enrollments(session_id);

CREATE TABLE IF NOT EXISTS farmer_orders (
    id SERIAL PRIMARY KEY,
    order_code VARCHAR(20) UNIQUE NOT NULL,
    farmer_id INTEGER REFERENCES farmer_profiles(id),
    order_date DATE DEFAULT CURRENT_DATE,
    product_lot_id INTEGER REFERENCES product_lots(id),
    product_type VARCHAR(50) NOT NULL,
    quantity_kg DECIMAL(10,2) NOT NULL,
    unit_price DECIMAL(10,2),
    total_amount DECIMAL(12,2),
    payment_status VARCHAR(20) DEFAULT 'pending',
    delivery_status VARCHAR(20) DEFAULT 'pending',
    delivery_date DATE,
    delivery_address TEXT,
    notes TEXT,
    recorded_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_farmer_orders_code ON farmer_orders(order_code);
CREATE INDEX IF NOT EXISTS idx_farmer_orders_farmer ON farmer_orders(farmer_id);
CREATE INDEX IF NOT EXISTS idx_farmer_orders_date ON farmer_orders(order_date);

-- ========================================
-- TRACEABILITY MODULE
-- ========================================

CREATE TABLE IF NOT EXISTS traceability_nodes (
    id SERIAL PRIMARY KEY,
    node_type VARCHAR(50) NOT NULL,
    node_id INTEGER NOT NULL,
    node_code VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(node_type, node_id)
);

CREATE INDEX IF NOT EXISTS idx_traceability_nodes_type ON traceability_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_traceability_nodes_code ON traceability_nodes(node_code);

CREATE TABLE IF NOT EXISTS traceability_edges (
    id SERIAL PRIMARY KEY,
    source_node_id INTEGER REFERENCES traceability_nodes(id),
    target_node_id INTEGER REFERENCES traceability_nodes(id),
    transformation_type VARCHAR(50),
    transformation_date DATE,
    quantity_transferred DECIMAL(10,2),
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_traceability_edges_source ON traceability_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_traceability_edges_target ON traceability_edges(target_node_id);

-- ========================================
-- SOCIAL IMPACT MODULE
-- ========================================

CREATE TABLE IF NOT EXISTS impact_indicators (
    id SERIAL PRIMARY KEY,
    indicator_code VARCHAR(30) UNIQUE NOT NULL,
    indicator_name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    unit_of_measurement VARCHAR(50),
    calculation_formula TEXT,
    sdg_alignment TEXT,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_impact_indicators_category ON impact_indicators(category);

CREATE TABLE IF NOT EXISTS impact_measurements (
    id SERIAL PRIMARY KEY,
    indicator_id INTEGER REFERENCES impact_indicators(id),
    measurement_date DATE NOT NULL,
    period_type VARCHAR(20),
    value DECIMAL(15,4) NOT NULL,
    source_data TEXT,
    location VARCHAR(100),
    notes TEXT,
    recorded_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_impact_measurements_indicator ON impact_measurements(indicator_id);
CREATE INDEX IF NOT EXISTS idx_impact_measurements_date ON impact_measurements(measurement_date);

CREATE TABLE IF NOT EXISTS impact_targets (
    id SERIAL PRIMARY KEY,
    indicator_id INTEGER REFERENCES impact_indicators(id),
    target_year INTEGER NOT NULL,
    target_quarter INTEGER,
    target_value DECIMAL(15,4) NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(indicator_id, target_year, target_quarter)
);

-- ========================================
-- ROLE-BASED ACCESS CONTROL
-- ========================================

CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    role_code VARCHAR(30) UNIQUE NOT NULL,
    role_name VARCHAR(100) NOT NULL,
    portal_access VARCHAR(20) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS permissions (
    id SERIAL PRIMARY KEY,
    permission_code VARCHAR(50) UNIQUE NOT NULL,
    module VARCHAR(50) NOT NULL,
    action VARCHAR(20) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS role_permissions (
    id SERIAL PRIMARY KEY,
    role_id INTEGER REFERENCES roles(id),
    permission_id INTEGER REFERENCES permissions(id),
    UNIQUE(role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS user_roles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id),
    role_id INTEGER REFERENCES roles(id),
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_by INTEGER,
    UNIQUE(user_id, role_id)
);

-- ========================================
-- AUDIT LOG
-- ========================================

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    action VARCHAR(50) NOT NULL,
    module VARCHAR(50),
    record_type VARCHAR(50),
    record_id INTEGER,
    old_values TEXT,
    new_values TEXT,
    ip_address VARCHAR(50),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_module ON audit_log(module);
CREATE INDEX IF NOT EXISTS idx_audit_log_date ON audit_log(created_at);

-- ========================================
-- SEED DATA: ROLES
-- ========================================

INSERT INTO roles (role_code, role_name, portal_access, description) VALUES
('SUPER_ADMIN', 'Super Administrator', 'admin', 'Full system access'),
('OPS_MANAGER', 'Operations Manager', 'admin', 'Manages daily operations'),
('WASTE_COORD', 'Waste Coordinator', 'admin', 'Manages waste collection'),
('PROD_SUPER', 'Production Supervisor', 'admin', 'Manages BSF production'),
('QA_OFFICER', 'QA Officer', 'admin', 'Quality assurance'),
('IMPACT_ANALYST', 'Impact Analyst', 'admin', 'Social impact reporting'),
('TRAINER', 'Trainer', 'admin', 'Farmer training'),
('FARMER', 'Farmer', 'farmer', 'External farmer user')
ON CONFLICT (role_code) DO NOTHING;

-- ========================================
-- SEED DATA: PERMISSIONS
-- ========================================

INSERT INTO permissions (permission_code, module, action, description) VALUES
('waste.create', 'waste', 'create', 'Create waste records'),
('waste.read', 'waste', 'read', 'View waste records'),
('waste.update', 'waste', 'update', 'Update waste records'),
('waste.delete', 'waste', 'delete', 'Delete waste records'),
('production.create', 'production', 'create', 'Create production records'),
('production.read', 'production', 'read', 'View production records'),
('production.update', 'production', 'update', 'Update production records'),
('production.delete', 'production', 'delete', 'Delete production records'),
('farmers.create', 'farmers', 'create', 'Create farmer profiles'),
('farmers.read', 'farmers', 'read', 'View farmer profiles'),
('farmers.update', 'farmers', 'update', 'Update farmer profiles'),
('farmers.approve', 'farmers', 'approve', 'Approve farmer registrations'),
('training.create', 'training', 'create', 'Create training programs'),
('training.read', 'training', 'read', 'View training programs'),
('training.manage', 'training', 'manage', 'Manage training sessions'),
('orders.create', 'orders', 'create', 'Create orders'),
('orders.read', 'orders', 'read', 'View orders'),
('orders.manage', 'orders', 'manage', 'Manage orders'),
('traceability.read', 'traceability', 'read', 'View traceability'),
('traceability.manage', 'traceability', 'manage', 'Manage traceability'),
('impact.read', 'impact', 'read', 'View impact reports'),
('impact.manage', 'impact', 'manage', 'Manage impact data'),
('admin.users', 'admin', 'users', 'Manage users'),
('admin.roles', 'admin', 'roles', 'Manage roles'),
('admin.settings', 'admin', 'settings', 'System settings')
ON CONFLICT (permission_code) DO NOTHING;

-- ========================================
-- SEED DATA: IMPACT INDICATORS
-- ========================================

INSERT INTO impact_indicators (indicator_code, indicator_name, category, unit_of_measurement, sdg_alignment, description) VALUES
('GHG_AVOIDED', 'GHG Emissions Avoided', 'environmental', 'kg CO2e', '13', 'Greenhouse gas emissions prevented by diverting waste from landfill'),
('WASTE_DIVERTED', 'Waste Diverted from Landfill', 'environmental', 'tonnes', '12', 'Organic waste diverted from landfills'),
('WATER_SAVED', 'Water Saved', 'environmental', 'liters', '6', 'Water saved compared to conventional protein production'),
('PROTEIN_PRODUCED', 'Protein Produced', 'environmental', 'kg', '2', 'BSF larvae protein produced'),
('FERTILIZER_PRODUCED', 'Organic Fertilizer Produced', 'environmental', 'kg', '15', 'Frass organic fertilizer produced'),
('JOBS_CREATED', 'Direct Jobs Created', 'economic', 'count', '8', 'Number of direct employment positions'),
('FARMER_INCOME', 'Farmer Income Uplift', 'economic', 'percentage', '8', 'Percentage increase in farmer income'),
('REVENUE_CIRCULAR', 'Circular Economy Revenue', 'economic', 'KES', '12', 'Revenue from circular economy activities'),
('FARMERS_TRAINED', 'Farmers Trained', 'social', 'count', '4', 'Number of farmers trained'),
('YOUTH_EMPLOYED', 'Youth Employed', 'social', 'count', '8', 'Number of youth under 35 employed'),
('WOMEN_EMPOWERED', 'Women Empowered', 'social', 'count', '5', 'Number of women in leadership or employment'),
('COMMUNITIES_SERVED', 'Communities Served', 'social', 'count', '11', 'Number of communities benefiting')
ON CONFLICT (indicator_code) DO NOTHING;
