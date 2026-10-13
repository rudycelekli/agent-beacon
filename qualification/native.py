"""Immutable, native Linux qualification; never edits tracked source or fakes embeds."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('phase', choices=['baseline', 'fixed'])
parser.add_argument('source', type=Path)
parser.add_argument('proof', type=Path)
args = parser.parse_args()
source, proof = args.source.resolve(), args.proof.resolve()
proof.mkdir(parents=True, exist_ok=True)
manifest = json.loads(Path(__file__).with_name('manifest.json').read_text())
expected = manifest['phases'][args.phase]
records = []

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def command(label, argv, cwd, expected_exit=0):
    start = now()
    with (proof / (label + '.stdout')).open('wb') as out, (proof / (label + '.stderr')).open('wb') as err:
        result = subprocess.run(argv, cwd=cwd, stdout=out, stderr=err, timeout=3600)
    records.append({'label': label, 'argv': argv, 'cwd': str(cwd), 'start': start,
                    'end': now(), 'exit': result.returncode, 'expected_exit': expected_exit})
    (proof / 'commands.json').write_text(json.dumps(records, indent=2))
    if result.returncode != expected_exit:
        raise RuntimeError(f'{label}: exit {result.returncode}, expected {expected_exit}')
    return (proof / (label + '.stdout')).read_text()

def git(*argv):
    return subprocess.check_output(['git', *argv], cwd=source).decode().strip()

def tracked():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=source).decode().split('\0')
    return {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names if name}

before = None
try:
    (proof / 'harness-hashes.json').write_text(json.dumps({f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in Path(__file__).parent.iterdir() if f.is_file()}, indent=2))
    environment = {'runner_os': os.environ.get('RUNNER_OS'), 'system': platform.system(),
                   'platform': platform.platform(), 'machine': platform.machine(),
                   'head': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
                   'autocrlf': git('config', '--get', 'core.autocrlf'),
                   'go_version': subprocess.check_output(['go', 'version'], text=True).strip(),
                   'go_env': json.loads(subprocess.check_output(['go', 'env', '-json'], text=True))}
    (proof / 'environment.json').write_text(json.dumps(environment, indent=2))
    if environment['runner_os'] != 'Linux' or environment['system'] != 'Linux':
        raise RuntimeError('This qualification requires actual native Linux')
    if environment['head'] != expected['head'] or environment['tree'] != expected['tree']:
        raise RuntimeError('Source identity differs from immutable manifest')
    if environment['go_version'].split()[2] != manifest['go_version']:
        raise RuntimeError('Go version differs from pinned runtime')
    if git('status', '--porcelain', '--untracked-files=no'):
        raise RuntimeError('Tracked source starts dirty')
    before = tracked()
    (proof / 'tracked-before.json').write_text(json.dumps(before, indent=2))
    cli = source / 'cli/beacon'
    fixture=source / manifest['fixture_path']
    expected_fixture=Path(__file__).with_name('search_quit_test.go').read_bytes()
    if hashlib.sha256(expected_fixture).hexdigest()!=manifest['fixture_sha256']:
        raise RuntimeError('Immutable new-test fixture hash mismatch')
    if args.phase=='baseline':
        if fixture.exists():raise RuntimeError('Baseline unexpectedly contains new fixture')
        fixture.write_bytes(expected_fixture)
    elif fixture.read_bytes()!=expected_fixture:
        raise RuntimeError('Fixed fixture differs from reviewed regression')
    (proof/'fixture.json').write_text(json.dumps({'transplanted':args.phase=='baseline','path':manifest['fixture_path'],'sha256':manifest['fixture_sha256']},indent=2))
    command('cli-build-real-hooks', ['make', 'build'], cli)
    hooks = source / 'cli/beacon-hooks/beacon-hooks'
    embedded = cli / 'internal/embedded/hooks.bin'
    if hooks.read_bytes() != embedded.read_bytes() or embedded.read_bytes().startswith(b'PLACEHOLDER'):
        raise RuntimeError('CLI embed is not the actual built native hooks binary')
    (proof / 'build-binaries.json').write_text(json.dumps({str(f.relative_to(source)): {
        'bytes': f.stat().st_size, 'sha256': hashlib.sha256(f.read_bytes()).hexdigest()}
        for f in [hooks, embedded, cli / 'beacon']}, indent=2))
    command('cli-package-inventory', ['go', 'list', './...'], cli)
    command('cli-tests', ['go', 'test', '-json', '-count=1', './...'], cli,
            expected_exit=1 if args.phase == 'baseline' else 0)
    command('endpoint-race', ['go', 'test', '-race', '-json', '-count=1', './internal/endpoint/...'], cli, expected_exit=1 if args.phase=='baseline' else 0)
    for name, relative in [('hooks', 'cli/beacon-hooks'), ('exporter', 'collector-builder/exporter/beaconjsonexporter'),
                           ('observe', 'pkg/asymptoteobserve'), ('sandbox', 'beacon-sandbox')]:
        module = source / relative
        command(name + '-package-inventory', ['go', 'list', './...'], module)
        command(name + '-tests', ['go', 'test', '-json', '-count=1', './...'], module)
    result = {'status': 'PASS', 'phase': args.phase, 'head': expected['head'],
              'baseline_expected_two_ctrl_c_failures': args.phase == 'baseline'}
except Exception as error:
    result = {'status': 'FAIL', 'phase': args.phase, 'error': str(error)}
finally:
    if before is not None:
        if (source / manifest['fixture_path']).exists() and hashlib.sha256((source / manifest['fixture_path']).read_bytes()).hexdigest()!=manifest['fixture_sha256']:
            result={'status':'FAIL','error':'New regression fixture mutated'}
        after = tracked()
        (proof / 'tracked-after.json').write_text(json.dumps(after, indent=2))
        changed = sorted(k for k in before if before[k] != after.get(k))
        dirty = git('status', '--porcelain', '--untracked-files=no')
        (proof / 'tracked-status.txt').write_text(dirty)
        if changed or dirty:
            result = {'status': 'FAIL', 'phase': args.phase, 'error': 'Tracked source mutated', 'changed': changed}
    (proof / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
if result['status'] != 'PASS':
    raise SystemExit(1)
