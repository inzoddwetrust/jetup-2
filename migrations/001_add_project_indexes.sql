-- Migration: Add composite indexes to projects table for performance optimization
-- Date: 2025-11-03
-- Description: Adds indexes to improve query performance in project carousel pagination

-- Index for get_project_by_id queries (projectID, lang, status)
-- This speeds up lookups by projectID with language fallback and status filtering
CREATE INDEX IF NOT EXISTS ix_project_id_lang_status
ON projects (projectID, lang, status);

-- Index for sorted project list queries (status, rate)
-- This speeds up fetching and sorting active/child projects by rate
CREATE INDEX IF NOT EXISTS ix_project_status_rate
ON projects (status, rate);

-- To rollback these changes, run:
-- DROP INDEX IF EXISTS ix_project_id_lang_status;
-- DROP INDEX IF EXISTS ix_project_status_rate;
