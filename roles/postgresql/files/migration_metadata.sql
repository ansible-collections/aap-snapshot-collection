SELECT json_build_object(
  'version', current_setting('server_version_num')::integer,
  'writable', NOT pg_is_in_recovery() AND current_setting('default_transaction_read_only') = 'off',
  'database_create', has_database_privilege(current_user, current_database(), 'CREATE'),
  'schemas', COALESCE((SELECT json_object_agg(nspname, json_build_object(
      'usage', has_schema_privilege(current_user, oid, 'USAGE'),
      'create', has_schema_privilege(current_user, oid, 'CREATE')))
    FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema'), '{}'::json),
  'extensions', COALESCE((SELECT json_object_agg(e.extname, n.nspname)
    FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace), '{}'::json),
  'object_privileges', NOT EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
      AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')
      AND ((c.relkind IN ('r','p') AND (
        NOT (has_table_privilege(current_user, c.oid, 'SELECT')
          AND has_table_privilege(current_user, c.oid, 'INSERT')
          AND has_table_privilege(current_user, c.oid, 'UPDATE')
          AND has_table_privilege(current_user, c.oid, 'DELETE'))
        OR NOT pg_has_role(current_user, c.relowner, 'USAGE')))
        OR (c.relkind='S' AND NOT (has_sequence_privilege(current_user, c.oid, 'USAGE')
          AND has_sequence_privilege(current_user, c.oid, 'SELECT')
          AND has_sequence_privilege(current_user, c.oid, 'UPDATE'))))),
  'tables', COALESCE((SELECT json_agg(n.nspname || '.' || c.relname ORDER BY n.nspname, c.relname)
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE c.relkind IN ('r','p') AND n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
      AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')), '[]'::json),
  'migrations', COALESCE((SELECT json_agg(app || ':' || name ORDER BY app, name) FROM django_migrations), '[]'::json)
) AS metadata;
