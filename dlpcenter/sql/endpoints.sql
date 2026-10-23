-- Stable device identity is independent of hostname, IP address and display code.
CREATE TABLE IF NOT EXISTS endpoints (
    endpoint_uid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_code TEXT NOT NULL UNIQUE CHECK (endpoint_code <> ''),
    seq BIGSERIAL UNIQUE NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    username TEXT NOT NULL DEFAULT '',
    department TEXT NOT NULL DEFAULT '',
    ip_address TEXT NOT NULL DEFAULT '',
    os TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'offline',
    risk TEXT NOT NULL DEFAULT 'low',
    agent_version TEXT NOT NULL DEFAULT '',
    policy TEXT NOT NULL DEFAULT '',
    last_seen TEXT NOT NULL DEFAULT '',
    isolated BOOLEAN NOT NULL DEFAULT false,
    extra JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_endpoints_status ON endpoints(status);
CREATE INDEX IF NOT EXISTS idx_endpoints_department ON endpoints(department);
CREATE INDEX IF NOT EXISTS idx_endpoints_name ON endpoints(name);
CREATE INDEX IF NOT EXISTS idx_endpoints_ip ON endpoints(ip_address);

CREATE OR REPLACE FUNCTION protect_endpoint_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.endpoint_uid IS DISTINCT FROM OLD.endpoint_uid THEN
        RAISE EXCEPTION 'endpoint_uid is immutable';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS endpoint_identity_guard ON endpoints;
CREATE TRIGGER endpoint_identity_guard BEFORE UPDATE ON endpoints
    FOR EACH ROW EXECUTE FUNCTION protect_endpoint_identity();

ALTER TABLE dlp_records ADD COLUMN IF NOT EXISTS endpoint_uid UUID
    REFERENCES endpoints(endpoint_uid) ON UPDATE RESTRICT ON DELETE RESTRICT;
CREATE INDEX IF NOT EXISTS idx_records_endpoint_uid ON dlp_records(endpoint_uid,kind);

-- JSON retains historical hostname/IP snapshots; endpoint_uid alone is authoritative.
CREATE OR REPLACE FUNCTION sync_record_endpoint() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    requested TEXT;
    resolved UUID;
BEGIN
    IF NEW.kind = 'endpoints' THEN
        RAISE EXCEPTION 'terminal records must be stored in endpoints';
    END IF;
    IF NEW.data ? 'endpointUid' THEN
        requested := nullif(NEW.data->>'endpointUid','');
        resolved := requested::uuid;
        IF TG_OP = 'UPDATE' AND NEW.endpoint_uid IS DISTINCT FROM OLD.endpoint_uid
           AND NEW.endpoint_uid IS DISTINCT FROM resolved THEN
            -- Explicit column updates must also refresh the JSON projection below.
            resolved := NEW.endpoint_uid;
        END IF;
        NEW.endpoint_uid := resolved;
    ELSIF TG_OP = 'INSERT' AND NEW.endpoint_uid IS NULL AND nullif(NEW.data->>'endpointId','') IS NOT NULL THEN
        SELECT endpoint_uid INTO resolved FROM endpoints WHERE endpoint_code=NEW.data->>'endpointId';
        IF resolved IS NULL THEN
            RAISE EXCEPTION 'unknown endpointId';
        END IF;
        NEW.endpoint_uid := resolved;
    ELSIF TG_OP = 'UPDATE' AND NEW.data->>'endpointId' IS DISTINCT FROM OLD.data->>'endpointId'
          AND nullif(NEW.data->>'endpointId','') IS NOT NULL THEN
        SELECT endpoint_uid INTO resolved FROM endpoints WHERE endpoint_code=NEW.data->>'endpointId';
        IF resolved IS NULL THEN RAISE EXCEPTION 'unknown endpointId'; END IF;
        NEW.endpoint_uid := resolved;
    END IF;
    IF NEW.endpoint_uid IS NULL THEN
        NEW.data := NEW.data - 'endpointUid';
    ELSE
        IF NOT EXISTS (SELECT 1 FROM endpoints WHERE endpoint_uid=NEW.endpoint_uid) THEN
            RAISE EXCEPTION 'unknown endpoint_uid';
        END IF;
        NEW.data := NEW.data || jsonb_build_object('endpointUid',NEW.endpoint_uid);
    END IF;
    RETURN NEW;
END $$;
-- The trigger is installed by migrate_endpoints.py after legacy endpoint rows move.

CREATE OR REPLACE VIEW endpoint_records AS
SELECT endpoint_code AS id, seq, 'endpoints'::text AS kind,
       extra || jsonb_build_object(
        'id',endpoint_code,'endpointUid',endpoint_uid,'name',name,'user',username,
        'department',department,'ip',ip_address,'os',os,'status',status,'risk',risk,
        'version',agent_version,'policy',policy,'lastSeen',last_seen,'isolated',isolated) AS data
FROM endpoints;
CREATE OR REPLACE VIEW dlp_record_view AS
SELECT seq,kind,id,data,endpoint_uid FROM dlp_records
UNION ALL
SELECT seq,kind,id,data,(data->>'endpointUid')::uuid FROM endpoint_records;
