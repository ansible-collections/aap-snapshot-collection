-- Run in the migration pod as the target component user, before idling AAP.
WITH application_objects AS (
    SELECT c.oid, 'pg_class'::regclass AS classid, c.relnamespace AS namespace, c.relowner AS owner
      FROM pg_class c WHERE c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
    UNION ALL
    SELECT p.oid, 'pg_proc'::regclass, p.pronamespace, p.proowner FROM pg_proc p
    UNION ALL
    SELECT t.oid, 'pg_type'::regclass, t.typnamespace, t.typowner FROM pg_type t
      WHERE t.typtype IN ('d', 'e', 'r', 'm', 'b') AND t.typelem = 0
), unowned AS (
    SELECT o.oid FROM application_objects o JOIN pg_namespace n ON n.oid = o.namespace
     WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
       AND NOT pg_has_role(current_user, o.owner, 'USAGE')
       AND NOT EXISTS (SELECT 1 FROM pg_depend d
                        WHERE d.classid = o.classid AND d.objid = o.oid AND d.deptype = 'e')
)
SELECT json_build_object(
    'version', current_setting('server_version_num')::integer,
    'writable', NOT current_setting('transaction_read_only')::boolean AND NOT pg_is_in_recovery(),
    'database_create', has_database_privilege(current_user, current_database(), 'CREATE'),
    'extension_config_privileges', (SELECT coalesce(json_object_agg(config.extension, config.writable), '{}'::json)
                                     FROM (SELECT e.extname AS extension,
                                                  bool_and(has_table_privilege(current_user, config_oid, 'INSERT')) AS writable
                                             FROM pg_extension e CROSS JOIN LATERAL unnest(e.extconfig) AS config_oid
                                            GROUP BY e.extname) config),
    'extensions', (SELECT coalesce(json_object_agg(e.extname, n.nspname), '{}'::json)
                     FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace),
    'schemas', (SELECT coalesce(json_object_agg(n.nspname, json_build_object(
                       'usage', has_schema_privilege(current_user, n.oid, 'USAGE'),
                       'create', has_schema_privilege(current_user, n.oid, 'CREATE'),
                       'owned', pg_has_role(current_user, n.nspowner, 'USAGE'))), '{}'::json)
                   FROM pg_namespace n WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'),
    'unowned_objects', (SELECT count(*) FROM unowned)
);
