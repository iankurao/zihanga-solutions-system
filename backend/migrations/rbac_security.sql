-- Step 22: roles, session versioning and login throttling.
-- Repeatable: safe to run on every start.

CREATE TABLE IF NOT EXISTS schema_markers (
    name VARCHAR(80) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Before Step 22 every non-admin account was 'viewer' yet could record any
-- operational data in its locations.  Map those accounts to 'manager' once so
-- existing users keep working; 'viewer' is read-only from now on.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_markers WHERE name = 'rbac_roles_v1') THEN
        UPDATE users SET role = 'manager' WHERE role = 'viewer' OR role IS NULL;
        UPDATE users SET role = 'viewer'
        WHERE role NOT IN ('super_admin', 'manager', 'operator', 'qc_officer',
                           'inventory_officer', 'sales_officer', 'viewer');
        INSERT INTO schema_markers (name) VALUES ('rbac_roles_v1');
    END IF;
END $$;

ALTER TABLE users ALTER COLUMN role SET DEFAULT 'viewer';
UPDATE users SET role = 'viewer' WHERE role IS NULL;
ALTER TABLE users ALTER COLUMN role SET NOT NULL;

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (
    role IN ('super_admin', 'manager', 'operator', 'qc_officer',
             'inventory_officer', 'sales_officer', 'viewer')
);

-- Bumped on password reset, deactivation and role change; sessions and
-- remember-me cookies carrying an older version stop working.
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_version INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS auth_login_attempts (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    ip_address VARCHAR(64),
    succeeded BOOLEAN NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_email
    ON auth_login_attempts (email, attempted_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_login_attempts_ip
    ON auth_login_attempts (ip_address, attempted_at DESC);
