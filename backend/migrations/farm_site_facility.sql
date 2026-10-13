-- Canonical organization -> farm -> site -> facility hierarchy.
-- This migration is additive and intentionally does not guess locations for
-- existing operational records.

CREATE TABLE IF NOT EXISTS organizations (
    id SERIAL PRIMARY KEY,
    organization_code VARCHAR(30) UNIQUE NOT NULL,
    name VARCHAR(150) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS farms (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    farm_code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    location_description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (organization_id, farm_code),
    UNIQUE (id, organization_id)
);

CREATE TABLE IF NOT EXISTS sites (
    id SERIAL PRIMARY KEY,
    farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE RESTRICT,
    site_code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    location_description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (farm_id, site_code),
    UNIQUE (id, farm_id)
);

CREATE TABLE IF NOT EXISTS facilities (
    id SERIAL PRIMARY KEY,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE RESTRICT,
    facility_code VARCHAR(30) NOT NULL,
    name VARCHAR(150) NOT NULL,
    facility_type VARCHAR(80) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (site_id, facility_code),
    UNIQUE (id, site_id)
);

CREATE TABLE IF NOT EXISTS user_organization_access (
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    granted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    PRIMARY KEY (user_id, organization_id)
);

CREATE TABLE IF NOT EXISTS user_farm_access (
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
    granted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    PRIMARY KEY (user_id, farm_id)
);

CREATE TABLE IF NOT EXISTS user_site_access (
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    granted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    PRIMARY KEY (user_id, site_id)
);

CREATE TABLE IF NOT EXISTS user_facility_access (
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    facility_id INTEGER NOT NULL REFERENCES facilities(id) ON DELETE CASCADE,
    granted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    PRIMARY KEY (user_id, facility_id)
);

-- This transition table links existing records without changing or guessing
-- the schema of every operational module. entity_id is the existing integer
-- primary key in entity_table.
CREATE TABLE IF NOT EXISTS operational_location_links (
    id BIGSERIAL PRIMARY KEY,
    entity_table VARCHAR(80) NOT NULL,
    entity_id BIGINT NOT NULL,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    farm_id INTEGER NOT NULL REFERENCES farms(id) ON DELETE RESTRICT,
    site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE RESTRICT,
    facility_id INTEGER NOT NULL REFERENCES facilities(id) ON DELETE RESTRICT,
    recorded_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (entity_table, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_farms_organization ON farms(organization_id);
CREATE INDEX IF NOT EXISTS idx_sites_farm ON sites(farm_id);
CREATE INDEX IF NOT EXISTS idx_facilities_site ON facilities(site_id);
CREATE INDEX IF NOT EXISTS idx_user_org_access_user ON user_organization_access(user_id);
CREATE INDEX IF NOT EXISTS idx_user_farm_access_user ON user_farm_access(user_id);
CREATE INDEX IF NOT EXISTS idx_user_site_access_user ON user_site_access(user_id);
CREATE INDEX IF NOT EXISTS idx_user_facility_access_user ON user_facility_access(user_id);
CREATE INDEX IF NOT EXISTS idx_location_links_location
    ON operational_location_links(organization_id, farm_id, site_id, facility_id);