"""Launch the installed, unmodified Pi CLI; old Asis engines are explicit opt-ins."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys


PACKAGE = Path(__file__).resolve().parents[2] / 'runtime/pi-terminal/node_modules/@earendil-works/pi-coding-agent'


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    engine = None
    # Everything after -- belongs to Pi's prompt, including text resembling flags.
    boundary = args.index('--') if '--' in args else len(args)
    flags = args[:boundary]
    if '--engine' in flags:
        index = flags.index('--engine')
        if index + 1 >= boundary or flags[index + 1] not in ('native', 'conversation', 'legacy'):
            print('engine_must_be_native_conversation_or_legacy', file=sys.stderr)
            return 2
        engine = flags[index + 1]
        if engine == 'native':
            del args[index:index + 2]
    old_mode = ('--mode' in flags and flags.index('--mode') + 1 < len(flags)
                and flags[flags.index('--mode') + 1] in ('auto', 'research', 'career', 'life', 'team', 'conversation'))
    if engine in ('conversation', 'legacy') or (engine is None and (
            old_mode or any(arg in flags for arg in ('--worker', '--source')))):
        from .pi_terminal import main as old_main
        return old_main(args)
    node = shutil.which('node')
    entry = PACKAGE / 'dist/bundle/cli.js'
    if not node or not entry.is_file():
        print('optional_pi_terminal_not_installed', file=sys.stderr)
        return 1
    if args == ['--check']:
        from .native_sources import PROFILE
        print(json.dumps({'engine': 'native', 'pi_version': json.loads(
            (PACKAGE / 'package.json').read_text())['version'],
            'entry': str(entry), 'personal_data_extension': False,
            'conversation_core': False, 'asis_budget_enforced': False,
            'personal_profile_configured': (PROFILE / 'personal-sources.md').is_file(),
            'credential_reads': 0, 'model_generation_calls': 0,
            'platform_write_confirmation': True, 'startup_sync_configured': (PROFILE / 'life-sync.json').is_file()}))
        return 0
    environment = os.environ.copy()
    plain = '--plain' in args[:args.index('--') if '--' in args else len(args)]
    if plain:
        args.remove('--plain')
    elif args not in (['--help'], ['-h'], ['--version'], ['-v']):
        from .native_sources import HOME, PROFILE, prepare, credential_environment
        home = Path(environment.get('ASIS_PERSONAL_HOME', str(HOME)))
        profile = Path(environment.get('PI_CODING_AGENT_DIR', str(PROFILE)))
        try:
            configured = prepare(home, profile)
            if args == ['--setup-sources']:
                print(json.dumps(configured, ensure_ascii=False))
                return 0
            command = args[0] if args else None
            is_session = command not in ('mcp', 'auth', 'install', 'remove', 'uninstall', 'update', 'list', 'config')
            environment['PI_CODING_AGENT_DIR'] = str(profile)
            environment['ASIS_WRITE_PYTHON'] = sys.executable
            environment.update(credential_environment(home, model=is_session,
                xhs=configured['xiaohongshu_mcp'] and '--no-mcp' not in args))
            if is_session:
                if not any(x in args for x in ('--mode', '--print', '-p')):
                    from .life_sync import startup
                    try:
                        startup(home, profile)
                    except (OSError, ValueError, KeyError, EOFError, sqlite3.Error):
                        print('AstrBot 同步未完成；未确认的内容不会写入 Obsidian。', file=sys.stderr)
                args = ['--append-system-prompt', configured['context'], '--extension', str(Path(__file__).resolve().parents[2] / 'runtime/pi-terminal/source-write.ts'), *args]
        except (OSError, ValueError, sqlite3.Error):
            # Never echo paths, upstream error bodies or credential values.
            print('native_personal_sources_unavailable_use_check_or_plain', file=sys.stderr)
            return 1
    # Pi retains cwd, HOME, native tools, discovery, models and slash commands.
    os.execvpe(node, [node, str(entry), *args], environment)


if __name__ == '__main__':
    raise SystemExit(main())
