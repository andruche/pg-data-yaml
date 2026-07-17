## pg-data-yaml — Yaml interface for reference tables in PostgreSQL

Export, diff and sync rows of reference tables in PostgreSQL to YAML files in a repository.

## installation

```
pip install pg-data-yaml
```

## which tables are included

Table selection is configured with `--comment-label` or `--table-list-predicate`. One of these options is **required** for `export`, `diff` and `sync` (mutually exclusive).

### `--comment-label LABEL`

Include tables whose comment contains `LABEL`. Any label can be used, for example `global directory` or `env directory`.

Optional clause in parentheses after the label is parsed from the comment (see [marking tables](#marking-tables) below).

```
pg_data_yaml export -d mydb --out-dir /tmp/refs --comment-label "global directory"
```

### `--table-list-predicate PREDICATE`

Include tables matching a SQL predicate. Table comments are ignored; export always uses `select * from <schema>.<table> order by <primary key columns>`.

The predicate is inserted into a query against `pg_catalog.pg_class` and `pg_catalog.pg_namespace`. Use `n.nspname` for schema name and `c.relname` for table name.

Example — tables without tenant columns:

```
pg_data_yaml export -d mydb --out-dir /tmp/refs --table-list-predicate "
not exists (
    select 1
      from information_schema.columns col
     where col.table_schema = n.nspname
       and col.table_name = c.relname
       and col.column_name in ('app_id', 'customer_id', 'customerid')
)"
```

Tables must have a primary key. Tables without a PK are skipped with a warning.

## marking tables

When using `--comment-label`, add a comment on the table (via `COMMENT ON TABLE`):

```
synchronized directory
```

With a custom label:

```
global directory
```

Optional clause in parentheses:

- if it contains the word `select` — a full export query, for example:

```
synchronized directory(select id, name from my_schema.my_table order by name)
```

- otherwise — a `WHERE` filter inserted into the default template:

```
synchronized directory(not is_deleted)
```

→ `select * from <schema>.<table> where not is_deleted order by <primary key columns>`

If parentheses are omitted, export uses:

```
select * from <schema>.<table> order by <primary key columns>
```

Exported file layout: `<out-dir>/<schema>/<table>.yaml`

Each file is a YAML list of row mappings. Row and field order match the query result.

## usage

### export

```
usage: pg_data_yaml export [--help] [-d DBNAME] [-h HOST] [-p PORT] [-U USER] [-W PASSWORD]
                             (--comment-label LABEL | --table-list-predicate PREDICATE)
                             --out-dir OUT_DIR [--clean] [--rows-limit ROWS]

options:
  --help                show this help message and exit
  -d DBNAME, --dbname DBNAME
                        database name to connect to
  -h HOST, --host HOST  database server host or socket directory
  -p PORT, --port PORT  database server port
  -U USER, --user USER  database user name
  -W PASSWORD, --password PASSWORD
                        database user password
  --comment-label LABEL
                        include tables whose comment contains LABEL
  --table-list-predicate PREDICATE
                        include tables matching SQL PREDICATE (comments ignored)
  --out-dir OUT_DIR     directory for exporting files
  --clean               clean out_dir if not empty (env variable DATA_DIRECTORY_AUTOCLEAN=true)
  --rows-limit ROWS     skip tables with more than ROWS rows (default: 50000)
```

### diff

```
usage: pg_data_yaml diff [--help] [-d DBNAME] [-h HOST] [-p PORT] [-U USER] [-W PASSWORD]
                           (--comment-label LABEL | --table-list-predicate PREDICATE)
                           --source SOURCE

options:
  --help                show this help message and exit
  -d DBNAME, --dbname DBNAME
  -h HOST, --host HOST  database server host or socket directory
  -p PORT, --port PORT  database server port
  -U USER, --user USER  database user name
  -W PASSWORD, --password PASSWORD
                        database user password
  --comment-label LABEL
                        include tables whose comment contains LABEL
  --table-list-predicate PREDICATE
                        include tables matching SQL PREDICATE (comments ignored)
  --source SOURCE       directory or yaml file to compare with the database
```

### sync

```
usage: pg_data_yaml sync [--help] [-d DBNAME] [-h HOST] [-p PORT] [-U USER] [-W PASSWORD]
                           (--comment-label LABEL | --table-list-predicate PREDICATE)
                           --source SOURCE [--dry-run] [--echo-queries] [-y]
                           [--quiet] [--session-replication-role ROLE]

options:
  --help                show this help message and exit
  -d DBNAME, --dbname DBNAME
  -h HOST, --host HOST  database server host or socket directory
  -p PORT, --port PORT  database server port
  -U USER, --user USER  database user name
  -W PASSWORD, --password PASSWORD
                        database user password
  --comment-label LABEL
                        include tables whose comment contains LABEL
  --table-list-predicate PREDICATE
                        include tables matching SQL PREDICATE (comments ignored)
  --source SOURCE       directory or yaml file to sync to the database
  --dry-run             test run without real changes
  --echo-queries        echo commands sent to server
  -y, --yes             do not ask confirm
  --quiet               do not show yaml diff before applying changes
  --session-replication-role ROLE
                        set session_replication_role locally in transaction before DML
```

### merge-envs

Move table files that are identical in all given environment directories into a shared base directory and remove them from the environment directories.

```
usage: pg_data_yaml merge-envs [--help] --source ENV_DIR [--source ENV_DIR ...] --out-dir OUT_DIR [--dry-run]

options:
  --help                show this help message and exit
  --source ENV_DIR      environment directory (repeat for each env)
  --out-dir OUT_DIR     base directory for common table files
  --dry-run             show actions without changing files
```

Example layout after merge:

```
refs/
  base/public/countries.yaml   # identical in all envs
  dev/public/special.yaml      # env-specific
  prod/public/special.yaml
```

## examples

Comment label for synchronized reference data:

```
$ pg_data_yaml export -d my_database -h 127.0.0.1 -p 5432 -U postgres \
    --out-dir /tmp/refs/ --comment-label "synchronized directory"
```

Comment label for per-environment data:

```
$ pg_data_yaml export -d my_database --out-dir /tmp/refs/base --comment-label "global directory"
$ pg_data_yaml export -d my_database --out-dir /tmp/refs/dev --comment-label "env directory"
```

Predicate-based selection:

```
$ pg_data_yaml export -d my_database --out-dir /tmp/refs/ --table-list-predicate "
not exists (
    select 1 from information_schema.columns col
     where col.table_schema = n.nspname
       and col.table_name = c.relname
       and col.column_name in ('app_id', 'customer_id', 'customerid')
)"
```

Diff and sync use the same table selection options as export:

```
$ pg_data_yaml merge-envs --source /tmp/refs/dev --source /tmp/refs/prod --out-dir /tmp/refs/base
$ pg_data_yaml diff -d my_database -h 127.0.0.1 -p 5432 -U postgres --source /tmp/refs/ --comment-label "global directory"
$ pg_data_yaml sync -d my_database -h 127.0.0.1 -p 5432 -U postgres \
    --source /tmp/refs/ --comment-label "synchronized directory"
$ pg_data_yaml diff -d my_database -h 127.0.0.1 -p 5432 -U postgres --source /tmp/refs/public/countries.yaml
```

When syncing a directory, only tables that are both in the selected set and have a yaml file in `--source` are compared. A warning is printed and the table is skipped when the file exists but the table is not in the selection, or when the table is in the selection but the yaml file is missing. When syncing a single file, only that table is compared and updated if it is in the selection. Each table is synced in its own transaction, so a failed table does not leave other tables half-updated.
