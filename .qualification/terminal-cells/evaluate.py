"""Strict native inventories/outcomes; test controls are synthetic, not source proof."""
import datetime,json
from pathlib import Path
PKG='github.com/asymptote-labs/agent-beacon/cli/beacon/internal/endpoint/traceview'
FAIL={
 'TestTraceTerminalCellTruncation','TestTraceTerminalCellTruncation/wide','TestTraceTerminalCellTruncation/emoji-clusters','TestTraceTerminalCellTruncation/combining','TestTraceTerminalCellTruncation/single-cell',
 'TestTraceTerminalCellWrapping','TestTraceTerminalCellWrapping/wide','TestTraceTerminalCellWrapping/emoji-clusters','TestTraceTerminalCellWrapping/combining',
 'TestTraceViewCJKRowsStayWithinTerminal','TestTraceEventDetailsCJKFitsTerminal'}
PASS={'TestTraceTerminalCellTruncation/ascii','TestTraceTerminalCellTruncation/newlines','TestTraceTerminalCellTruncation/unbounded','TestTraceTerminalCellWrapping/ascii-spaces','TestTraceTerminalCellWrapping/blank-crlf'}
NEW={PKG+'::'+name:('fail' if name in FAIL else 'pass','') for name in FAIL|PASS}
ROOTS={PKG+'::'+name for name in FAIL|PASS if '/' not in name}

def validate_timestamps(start,end):
 try:
  begin=datetime.datetime.fromisoformat(start);finish=datetime.datetime.fromisoformat(end)
 except (TypeError,ValueError) as error:raise ValueError('malformed command timestamp') from error
 if begin.utcoffset() is None or finish.utcoffset() is None:raise ValueError('timezone-naive command timestamp')
 if begin>finish:raise ValueError('reversed command timestamps')


def parse(raw,inventory):
 runs=set();cases={};starts=set();packages={};outputs={};package_output={}
 for line in raw.splitlines():
  e=json.loads(line);a=e.get('Action');p=e.get('Package');t=e.get('Test')
  if a=='build-fail' or '[build failed]' in e.get('Output',''):raise ValueError('native build failed')
  if p is None:
   if a not in ['build-output']:raise ValueError('event has no package')
   continue
  if p not in inventory:raise ValueError('unexpected package')
  key=p+'::'+t if t else None
  if a=='start':
   if p in starts:raise ValueError('duplicate package start')
   starts.add(p)
  if a=='run':
   if not t or key in runs:raise ValueError('duplicate/missing test start')
   runs.add(key)
  if a=='output' and not t:package_output.setdefault(p,[]).append(e.get('Output',''))
  if a=='output' and t:
   output=e.get('Output','')
   if not output.lstrip().startswith(('=== RUN','=== PAUSE','=== CONT','--- PASS','--- FAIL','--- SKIP')):outputs.setdefault(key,[]).append(output)
  if a in ['pass','fail','skip']:
   if t:
    if key in cases:raise ValueError('duplicate test outcome')
    reason=''.join(outputs.get(key,[])) if a=='skip' else ''
    if a=='skip' and not reason:raise ValueError('skip without actual reason')
    cases[key]=(a,reason)
   else:
    if p in packages:raise ValueError('duplicate package outcome')
    reason='[no test files]' if a=='skip' and '[no test files]' in ''.join(package_output.get(p,[])) else ''
    if a=='skip' and not reason:raise ValueError('unexpected package skip')
    packages[p]=(a,reason)
 if starts!=set(inventory) or set(packages)!=set(inventory):raise ValueError('missing package start/outcome')
 if runs!=set(cases):raise ValueError('missing test start/outcome')
 return cases,packages

def list_tests(raw,inventory):
 roots=set();packages={};starts=set();package_output={}
 for line in raw.splitlines():
  e=json.loads(line);a=e.get('Action');p=e.get('Package')
  if a=='build-fail' or '[build failed]' in e.get('Output',''):raise ValueError('inventory build failed')
  if p is None:
   if a!='build-output':raise ValueError('inventory package absent')
   continue
  if p not in inventory:raise ValueError('inventory extra package')
  if a=='start':
   if p in starts:raise ValueError('duplicate inventory package start')
   starts.add(p)
  if a=='output':
   package_output.setdefault(p,[]).append(e.get('Output',''))
   for output in e.get('Output','').splitlines():
    if output.startswith(('Test','Example','Fuzz')) and not any(c.isspace() for c in output):
     key=p+'::'+output
     if key in roots:raise ValueError('duplicate listed method')
     roots.add(key)
  if a in ['pass','fail','skip'] and not e.get('Test'):
   if p in packages:raise ValueError('duplicate inventory package outcome')
   reason='[no test files]' if a=='skip' and '[no test files]' in ''.join(package_output.get(p,[])) else ''
   if a=='skip' and not reason:raise ValueError('unexpected inventory package skip')
   packages[p]=(a,reason)
 if starts!=set(inventory) or set(packages)!=set(inventory) or any(v[0] not in ['pass','skip'] for v in packages.values()):raise ValueError('incomplete/failed pristine method inventory')
 return roots,packages

def compare(baseline,fixed,base_list,fixed_list,affected):
 a,ap=baseline;b,bp=fixed;new=NEW if affected else {}
 base_roots,listed_packages=base_list;fixed_roots,fixed_listed_packages=fixed_list
 if listed_packages!=fixed_listed_packages:raise ValueError('pristine package inventory outcomes changed')
 if set(b)!=set(a) or set(ap)!=set(bp):raise ValueError('test/package identities changed')
 if fixed_roots!=base_roots|(ROOTS if affected else set()):raise ValueError('pristine/fixed listed methods changed')
 actual_roots={key for key in a if '/' not in key.split('::',1)[1]}
 if actual_roots!=fixed_roots:raise ValueError('same omission of listed methods')
 if any(a.get(k)!=v or b.get(k)!=('pass','') for k,v in new.items()):raise ValueError('new expected outcomes mismatch')
 if any(k not in a for k in new):raise ValueError('new identity missing')
 if any(a[k]!=b[k] or a[k][0]=='fail' for k in a if k not in new):raise ValueError('original outcome or skip reason changed/failed')
 expected_packages=dict(listed_packages)
 if affected:expected_packages[PKG]=('fail','')
 if ap!=expected_packages or bp!=listed_packages:raise ValueError('unrelated baseline or fixed package failure')
 return {'testIdentities':len(a),'originalIdentities':len(a)-len(new),'packages':len(ap),'skips':[{'identity':k,'reason':v[1]} for k,v in a.items() if v[0]=='skip'],'newExpectedBaseline':{'fail':11,'pass':5} if affected else None}
