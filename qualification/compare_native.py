"""Validate all native phase receipts and package inventory before comparison."""
import argparse
import json
from pathlib import Path
from compare import compare, parse

parser=argparse.ArgumentParser()
parser.add_argument('baseline',type=Path);parser.add_argument('fixed',type=Path);parser.add_argument('output',type=Path)
args=parser.parse_args()
manifest=json.loads(Path(__file__).with_name('manifest.json').read_text())
try:
    for phase,directory in [('baseline',args.baseline),('fixed',args.fixed)]:
        result=json.loads((directory/'result.json').read_text())
        if result.get('status')!='PASS' or result.get('head')!=manifest['phases'][phase]['head']:
            raise RuntimeError('Native result is not PASS at exact source head')
        if json.loads((directory/'tracked-before.json').read_text())!=json.loads((directory/'tracked-after.json').read_text()):
            raise RuntimeError('Tracked bytes changed')
        fixture=json.loads((directory/'fixture.json').read_text())
        if fixture!={'transplanted':phase=='baseline','path':manifest['fixture_path'],'sha256':manifest['fixture_sha256']}:
            raise RuntimeError('Actual new regression fixture identity not proven')
        commands=json.loads((directory/'commands.json').read_text())
        labels={'cli-build-real-hooks','cli-package-inventory','cli-tests','endpoint-race'}
        labels.update(name+suffix for name in ['hooks','exporter','observe','sandbox'] for suffix in ['-package-inventory','-tests'])
        if len(commands)!=len(labels) or {c['label'] for c in commands}!=labels:
            raise RuntimeError('Canonical native command inventory incomplete')
        for c in commands:
            expected=1 if phase=='baseline' and c['label'] in ['cli-tests','endpoint-race'] else 0
            if c['exit']!=expected or c['expected_exit']!=expected:
                raise RuntimeError('Native exit status mismatch')
        for lane in ['cli','hooks','exporter','observe','sandbox']:
            _,packages,_=parse(directory/(lane+'-tests.stdout'))
            inventory=set((directory/(lane+'-package-inventory.stdout')).read_text().splitlines())
            if inventory!=set(packages):raise RuntimeError('Native package inventory missing from receipts: '+lane)
    lanes={'endpoint-race':compare(args.baseline/'endpoint-race.stdout',args.fixed/'endpoint-race.stdout'),'cli':compare(args.baseline/'cli-tests.stdout',args.fixed/'cli-tests.stdout')}
    for lane in ['hooks-tests','exporter-tests','observe-tests','sandbox-tests']:
        a,ap,askips=parse(args.baseline/(lane+'.stdout'));b,bp,bskips=parse(args.fixed/(lane+'.stdout'))
        if a!=b or ap!=bp or askips!=bskips:raise RuntimeError('Original outcomes or skip reasons changed: '+lane)
        if any(v=='fail' for v in a.values()) or any(v=='fail' for v in ap.values()):raise RuntimeError('Native test/package failure: '+lane)
        lanes[lane]={'tests':len(a),'packages':len(ap),'preserved_skips':len(askips)}
    result={'status':'PASS','lanes':lanes}
except Exception as error:
    result={'status':'FAIL','error':str(error)}
args.output.write_text(json.dumps(result,indent=2));print(json.dumps(result))
if result['status']!='PASS':raise SystemExit(1)
