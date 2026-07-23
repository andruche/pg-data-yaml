## pg-data-yaml — Yaml interface for reference tables in PostgreSQL

Export, diff and sync rows of reference tables in PostgreSQL to YAML files in a repository. Utilities `merge-envs` and `analyze-envs` help compare data across environment directories.

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

`diff` compares full yaml lists as text; row order matters.

### sync

```
usage: pg_data_yaml sync [--help] [-d DBNAME] [-h HOST] [-p PORT] [-U USER] [-W PASSWORD]
                           (--comment-label LABEL | --table-list-predicate PREDICATE)
                           --source SOURCE [--dry-run] [--echo-queries] [-y]
                           [--quiet] [--skip-error] [--session-replication-role ROLE]

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
  --source SOURCE       directory or yaml file to sync to the database
  --dry-run             test run without real changes
  --echo-queries        echo commands sent to server
  -y, --yes             do not ask confirm
  --quiet               suppress output; once: yaml diff, twice: table progress too
  --skip-error          continue syncing remaining tables after a failed table
  --session-replication-role ROLE
                        set session_replication_role locally in transaction before DML
```

Unlike `diff`, `sync` applies row-level DML (`insert`, `update`, `delete`) by primary key. Row order in yaml files does not matter: if only the order differs, sync reports `Nothing to do`. Before applying changes, sync validates that rows with the same primary key have the same set of columns in the file and in the database.

During apply, progress is printed per table unless suppressed:

```
public.countries... ok
public.cities... ok
```

On failure:

```
public.countries... ERROR: Traceback (most recent call last):
  ...
```

Progress is not printed with `--echo-queries` (queries would split the line). Use `--quiet --quiet` to suppress progress while keeping other output. With `--skip-error`, failed tables are rolled back and remaining tables are synced; the command still exits with code 1 if any table failed.

Each table is synced in its own transaction (`begin; ... commit;`), so a failed table does not leave other tables half-updated unless `--skip-error` is used to continue after an error.

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

### analyze-envs

Compare table yaml files across environment directories. For each table, prints a tab-separated line:

```
schema.table<TAB>identical_rows/different_rows<TAB>sync_mark
```

- `identical_rows` — rows present and identical in all directories
- `different_rows` — distinct row variants found across directories
- `*` after the ratio — table file is missing in at least one directory
- `sync_mark` — `да` when the table is listed in `/tmp/synchronized_directory.txt`, otherwise empty

Requires at least two directories.

```
usage: pg_data_yaml analyze-envs [--help] ENV_DIR [ENV_DIR ...]

options:
  --help                show this help message and exit
  ENV_DIR               environment directories to compare
```

Example:

```
$ pg_data_yaml analyze-envs /tmp/refs/dev /tmp/refs/prod /tmp/refs/stage
public.countries	120/0	да
public.settings	45/3*	
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
$ pg_data_yaml analyze-envs /tmp/refs/dev /tmp/refs/prod /tmp/refs/stage
$ pg_data_yaml diff -d my_database -h 127.0.0.1 -p 5432 -U postgres --source /tmp/refs/ --comment-label "global directory"
$ pg_data_yaml sync -d my_database -h 127.0.0.1 -p 5432 -U postgres \
    --source /tmp/refs/ --comment-label "synchronized directory" -y
$ pg_data_yaml sync -d my_database -h 127.0.0.1 -p 5432 -U postgres \
    --source /tmp/refs/ --comment-label "synchronized directory" --quiet --quiet --skip-error -y
$ pg_data_yaml diff -d my_database -h 127.0.0.1 -p 5432 -U postgres --source /tmp/refs/public/countries.yaml
```

When syncing a directory, only tables that are both in the selected set and have a yaml file in `--source` are compared. A warning is printed and the table is skipped when the file exists but the table is not in the selection, or when the table is in the selection but the yaml file is missing. When syncing a single file, only that table is compared and updated if it is in the selection.
