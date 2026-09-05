#!/usr/bin/env python3
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parent


def output(*command, cwd=None):
  return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False).stdout.strip()


def main():
  parser = argparse.ArgumentParser(description="Validate an exact openpilot revision without modifying its source tree.")
  parser.add_argument('--checkout', type=Path, required=True)
  parser.add_argument('--sha', required=True)
  parser.add_argument('--suite', choices=('unit', 'hwsim'), default='unit')
  parser.add_argument('--filter', default='')
  parser.add_argument('--allow-dirty', action='store_true', help='Development only; record that the result is not for a clean commit')
  parser.add_argument('--results', type=Path)
  args = parser.parse_args()
  checkout = args.checkout.resolve()
  if not re.fullmatch('[0-9a-f]{40}', args.sha):
    parser.error('--sha must be a full commit SHA')
  if output('git', 'rev-parse', 'HEAD', cwd=checkout) != args.sha:
    parser.error('The checkout HEAD does not match --sha; checkout the requested revision first')
  dirty = output('git', 'status', '--porcelain', '--untracked-files=normal', cwd=checkout)
  if dirty and not args.allow_dirty:
    parser.error('The openpilot checkout is dirty; commit changes or explicitly use --allow-dirty for a development run')
  python = checkout / '.venv/bin/python'
  if not python.is_file():
    parser.error('Prepare the openpilot environment first; .venv/bin/python is missing')
  now = datetime.datetime.now(datetime.UTC)
  results = (args.results or ROOT / 'results' / f'{now:%Y%m%dT%H%M%S%fZ}-{args.sha[:12]}-{args.suite}').resolve()
  results.mkdir(parents=True, exist_ok=False)
  env = {**os.environ, 'PYTHONPATH': str(checkout), 'PWD': str(checkout), 'RAYLIB_BACKEND': 'headless', 'OPENPILOT_ROOT': str(checkout),
         'WIFI_E2E_PYTHON': str(python), 'WIFI_E2E_LOG_DIR': str(results / 'services')}
  if args.suite == 'unit':
    command = [str(python), 'tools/test_runner.py', '-j', '1', 'openpilot/system/ui/lib/tests']
  else:
    command = [str(ROOT / 'run_wifi_e2e.sh'), f'--junitxml={results / "junit.xml"}']
  if args.filter:
    command += ['-k', args.filter]
  packages = 'import importlib.metadata as m, json; print(json.dumps({d.metadata["Name"]: d.version for d in m.distributions()}, sort_keys=True))'
  version_commands = {
    'python': [str(python), '--version'], 'kernel': ['uname', '-r'], 'packages': [str(python), '-c', packages],
  }
  for program, flag in [('NetworkManager', '--version'), ('wpa_supplicant', '-v'), ('hostapd', '-v'), ('dnsmasq', '--version')]:
    if shutil.which(program):
      version_commands[program] = [program, flag]
  tracked_sources = sorted([*ROOT.glob('*.py'), *ROOT.glob('*.sh'), ROOT / 'requirements.txt'])
  manifest = {
    'openpilot_sha': args.sha, 'openpilot_dirty': dirty.splitlines(),
    'openpilot_diff_sha256': hashlib.sha256(subprocess.check_output(['git', 'diff', 'HEAD', '--binary'], cwd=checkout)).hexdigest(),
    'harness_sha': output('git', 'rev-parse', '--verify', 'HEAD', cwd=ROOT),
    'harness_dirty': output('git', 'status', '--porcelain', cwd=ROOT).splitlines(),
    'harness_files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked_sources},
    'platform': platform.platform(), 'suite': args.suite, 'command': command, 'started': now.isoformat(),
    'versions': {name: output(*cmd) for name, cmd in version_commands.items()}, 'status': 'running',
  }
  manifest_path = results / 'manifest.json'
  manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
  print(f'Results: {results}', flush=True)
  try:
    with (results / 'run.log').open('w') as log:
      code = subprocess.run(command, cwd=checkout, env=env, stdout=log, stderr=subprocess.STDOUT, check=False).returncode
    manifest['exit_code'] = code
    manifest['status'] = 'passed' if code == 0 else 'blocked' if args.suite == 'hwsim' and code == 77 else 'failed'
    print((results / 'run.log').read_text())
    return code
  except (OSError, KeyboardInterrupt) as exc:
    manifest['status'], manifest['error'] = 'error', str(exc)
    raise
  finally:
    manifest['finished'] = datetime.datetime.now(datetime.UTC).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
  raise SystemExit(main())
