-- Local bootstrap. Production roles are created by the migration and Terraform.
-- The application NEVER connects as a superuser or as the table owner: either
-- would silently defeat FORCE ROW LEVEL SECURITY.
CREATE EXTENSION IF NOT EXISTS vector;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'airevenueos_app') THEN
    CREATE ROLE airevenueos_app NOLOGIN NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'airevenueos_app_login') THEN
    CREATE ROLE airevenueos_app_login LOGIN NOBYPASSRLS
      PASSWORD 'local_development_only' IN ROLE airevenueos_app;
  END IF;
END $$;
