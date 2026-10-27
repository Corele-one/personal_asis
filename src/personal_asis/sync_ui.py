"""Small terminal presentation for explicit sync; no dependency or hidden diff text."""
import os
import shutil
import sys
import unicodedata


def color(text, code):
    enabled = sys.stdout.isatty() and os.environ.get('TERM') != 'dumb' and 'NO_COLOR' not in os.environ
    return f'\x1b[{code}m{text}\x1b[0m' if enabled else text


def header():
    print('\n' + color('  ◈  Pi Sync', '1;36') + color('  /  生活与知识', '2'))
    print(color('  记录归档  →  本机资料  ⇄  共享库', '2'))
    print(color('  ' + '─' * min(62,max(24,shutil.get_terminal_size().columns-4)), '2'))


def stage(number, title, detail=''):
    print('\n' + color(f'  {number}/3', '1;36') + '  ' + color(title, '1'))
    if detail:print(color('       '+detail,'2'))


def line(text, *, indent='    '):
    # Preserve all characters; wrap only for a real terminal. Raw diff is always
    # available with d/--diff, and redirected output remains a lossless plain view.
    if not sys.stdout.isatty():
        print(indent+text);return
    width=max(28,min(100,shutil.get_terminal_size().columns-8))
    current='';used=0
    for c in text:
        size=0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('F','W') else 1
        if used+size>width:
            print(indent+current);current='';used=0
        current+=c;used+=size
    print(indent+current)
