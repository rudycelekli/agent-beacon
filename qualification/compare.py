"""Compare real whole-module Go test identities; allow only the proven mirror repair."""
import argparse
import json
from pathlib import Path

EXPECTED = 'github.com/asymptote-labs/agent-beacon/cli/beacon/internal/agentskills::TestEmbeddedSkillsMatchPublishedSkills'

def parse(path):
    cases, runs, packages, failures, skip_output = {}, set(), {}, [], {}
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if row['Action'] == 'build-fail':
            raise RuntimeError('Native build failed')
        package = row.get('Package', '')
        test = row.get('Test')
        if test:
            key = package + '::' + test
            if row['Action'] == 'run':
                if key in runs: raise RuntimeError('Duplicate test invocation')
                runs.add(key)
            if row['Action'] == 'output': skip_output.setdefault(key, []).append(row['Output'])
            if row['Action'] in ['pass', 'fail', 'skip']:
                if key in cases: raise RuntimeError('Duplicate test outcome')
                cases[key] = row['Action']
        elif package and row['Action'] in ['pass', 'fail', 'skip']:
            if package in packages: raise RuntimeError('Duplicate package outcome')
            packages[package] = row['Action']
    if not runs or runs != set(cases) or not packages:
        raise RuntimeError('Empty or incomplete native outcome receipts')
    if any(k not in skip_output for k,v in cases.items() if v=='skip'):
        raise RuntimeError('Skip outcome lacks native reason evidence')
    return cases, packages, {k:skip_output[k] for k,v in cases.items() if v=='skip'}

def compare(base, fixed):
    a, ap, askips = parse(base)
    b, bp, bskips = parse(fixed)
    if set(a)!=set(b) or set(ap)!=set(bp): raise RuntimeError('Native test/package identity changed')
    if a.get(EXPECTED)!='fail' or b.get(EXPECTED)!='pass': raise RuntimeError('Mirror negative control absent')
    if any(v=='fail' for k,v in a.items() if k!=EXPECTED): raise RuntimeError('Unexpected baseline failure')
    if any(v=='fail' for v in b.values()): raise RuntimeError('Fixed failure')
    if any(a[k]!=b[k] for k in a if k!=EXPECTED): raise RuntimeError('Original outcome changed')
    if askips!=bskips: raise RuntimeError('Existing skip reason changed')
    mirror_package=EXPECTED.split('::')[0]
    if any(v=='fail' for k,v in ap.items() if k!=mirror_package):raise RuntimeError('Unexpected baseline package failure')
    if any(v=='fail' for v in bp.values()):raise RuntimeError('Fixed package failure')
    if ap.get(mirror_package)!='fail' or bp.get(mirror_package)!='pass':raise RuntimeError('Mirror package status wrong')
    if any(ap[k]!=bp[k] for k in ap if k!=mirror_package):raise RuntimeError('Unrelated package outcome changed')
    return {'status':'PASS','test_identities':len(a),'packages':len(ap),'preserved_skips':len(askips),'only_changed_test':EXPECTED}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('base',type=Path);parser.add_argument('fixed',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    try:result=compare(args.base,args.fixed)
    except Exception as error:
        args.output.write_text(json.dumps({'status':'FAIL','error':str(error)},indent=2));raise
    args.output.write_text(json.dumps(result,indent=2));print(json.dumps(result))
