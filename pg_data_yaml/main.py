import argparse
import asyncio
import os
import shutil
import sys

from .analyze_envs import AnalyzeEnvs
from .extractor import DEFAULT_ROWS_LIMIT, Extractor
from .merge_envs import MergeEnvs
from .pg import Pg
from .synchronizer import Synchronizer
from . import __version__


async def run(args):
    pg = Pg(args)
    await pg.init()

    if args.command == 'export':
        await Extractor(args, pg).export()

    elif args.command in ('diff', 'sync'):
        await Synchronizer(args, pg).sync(show_diff_only=args.command == 'diff')


def main():
    def add_connection_args(parser):
        parser.add_argument('-d', '--dbname',
                            type=str, help='database name to connect to')
        parser.add_argument('-h', '--host',
                            type=str, help='database server host or socket directory')
        parser.add_argument('-p', '--port',
                            type=str, help='database server port')
        parser.add_argument('-U', '--user',
                            type=str, help='database user name')
        parser.add_argument('-W', '--password',
                            type=str, help='database user password')

    def add_registry_args(parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            '--comment-label',
            metavar='LABEL',
            help='include tables whose comment contains LABEL; '
            'optional export query or WHERE filter in parentheses after the label',
        )
        group.add_argument(
            '--table-list-predicate',
            metavar='PREDICATE',
            help='include tables matching SQL PREDICATE (table comments are ignored); '
            'references n.nspname and c.relname from pg_catalog',
        )

    arg_parser = argparse.ArgumentParser(
        epilog='Report bugs: https://github.com/andruche/pg-data-yaml/issues',
        conflict_handler='resolve',
    )

    arg_parser.add_argument(
        '--version',
        action='version',
        version=__version__,
    )

    subparsers = arg_parser.add_subparsers(
        dest='command',
        title='commands',
    )

    parser_export = subparsers.add_parser(
        'export',
        help='export synchronized reference tables to yaml files',
        conflict_handler='resolve',
    )
    add_connection_args(parser_export)
    add_registry_args(parser_export)
    parser_export.add_argument(
        '--out-dir',
        required=True,
        help='directory for exporting files',
    )
    parser_export.add_argument(
        '--clean',
        action='store_true',
        help='clean out_dir if not empty '
        '(env variable DATA_DIRECTORY_AUTOCLEAN=true)',
    )
    parser_export.add_argument(
        '--rows-limit',
        type=int,
        default=DEFAULT_ROWS_LIMIT,
        metavar='ROWS',
        help='skip tables with more than ROWS rows (default: %(default)s)',
    )

    parser_diff = subparsers.add_parser(
        'diff',
        help='show diff between database and yaml files',
        conflict_handler='resolve',
    )
    add_connection_args(parser_diff)
    add_registry_args(parser_diff)
    parser_diff.add_argument(
        '--source',
        required=True,
        help='directory or file with table data to compare with database',
    )

    parser_sync = subparsers.add_parser(
        'sync',
        help='sync yaml files to database tables',
        conflict_handler='resolve',
    )
    add_connection_args(parser_sync)
    add_registry_args(parser_sync)
    parser_sync.add_argument(
        '--source',
        required=True,
        help='directory or file with table data to sync to database',
    )
    parser_sync.add_argument(
        '--dry-run',
        action='store_true',
        help='test run without real changes',
    )
    parser_sync.add_argument(
        '--echo-queries',
        action='store_true',
        help='echo commands sent to server',
    )
    parser_sync.add_argument(
        '-y', '--yes',
        action='store_true',
        help='do not ask confirm',
    )
    parser_sync.add_argument(
        '--session-replication-role',
        metavar='ROLE',
        help='set session_replication_role locally in transaction before DML '
        '(for example replica to disable triggers and foreign keys)',
    )

    parser_merge_envs = subparsers.add_parser(
        'merge-envs',
        help='move identical table files from env dirs to base directory',
        conflict_handler='resolve',
    )
    parser_merge_envs.add_argument(
        '--source',
        action='append',
        required=True,
        metavar='ENV_DIR',
        help='environment directory (can be repeated)',
    )
    parser_merge_envs.add_argument(
        '--out-dir',
        required=True,
        help='base directory for common table files',
    )
    parser_merge_envs.add_argument(
        '--dry-run',
        action='store_true',
        help='show actions without changing files',
    )

    parser_merge_envs = subparsers.add_parser(
        'analyze-envs',
        help='compare data between envs',
        conflict_handler='resolve',
    )
    parser_merge_envs.add_argument(
        '--source',
        action='append',
        required=True,
        metavar='ENV_DIR',
        help='environment directory (can be repeated)',
    )

    args = arg_parser.parse_args()
    if not args.command:
        arg_parser.print_help()
        sys.exit(1)

    if args.command == 'export':
        if os.path.exists(args.out_dir) and os.listdir(args.out_dir):
            if args.clean or os.environ.get('DATA_DIRECTORY_AUTOCLEAN') == 'true':
                shutil.rmtree(args.out_dir)
            else:
                parser_export.error(
                    'out_dir directory not empty (you can use option --clean)'
                )
        try:
            os.makedirs(args.out_dir, exist_ok=True)
        except OSError:
            arg_parser.error("can not access to directory '%s'" % args.out_dir)

    if args.command in ('diff', 'sync'):
        if not os.path.exists(args.source):
            arg_parser.error(f'file or directory not found: {args.source}')

    if args.command == 'merge-envs':
        MergeEnvs(args).run()
        return

    if args.command == 'analyze-envs':
        AnalyzeEnvs(args).run_base()
        return

    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run(args))
