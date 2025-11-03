# Database Migrations

Manual SQL migration scripts for Jetup bot database.

## How to Apply Migrations

1. Connect to your PostgreSQL database:
   ```bash
   psql $DATABASE_URL
   ```

2. Run the migration script:
   ```bash
   psql $DATABASE_URL -f migrations/001_add_project_indexes.sql
   ```

## Migration List

- `001_add_project_indexes.sql` - Adds composite indexes to `projects` table for pagination performance

## Notes

- Always backup your database before applying migrations
- Check if indexes already exist before creating them (migrations use `IF NOT EXISTS`)
- These migrations are idempotent and can be safely re-run
