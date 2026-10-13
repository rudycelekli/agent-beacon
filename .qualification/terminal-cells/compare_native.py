"""Inspect exact command, source, inventory and test receipts from both native jobs."""
import argparse,hashlib,json
from pathlib import Path
from evaluate import parse,list_tests,compare,validate_timestamps
p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('fixed',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
manifest=json.loads(Path(__file__).with_name('manifest.json').read_text())
def expected_commands(phase,source):
 argv={'go-version-initial':['go','version'],'native-uname':['uname','-a'],'go-env':['go','env','-json','GOOS','GOARCH','GOVERSION','CGO_ENABLED'],'source-head-initial':['git','rev-parse','HEAD'],'source-tree-initial':['git','rev-parse','HEAD^{tree}'],'source-diff-initial':['git','diff','--exit-code'],'source-index-initial':['git','diff','--cached','--exit-code'],'before-git-tree':['git','ls-tree','-r','-z',manifest['phases'][phase]['head']],'cli-build-real-hooks':['make','build'],'actual-cli-version':[str(source/'cli/beacon/beacon'),'version'],'actual-cli-traces-help':[str(source/'cli/beacon/beacon'),'endpoint','traces','--help'],'go-version-final':['go','version'],'after-git-tree':['git','ls-tree','-r','-z',manifest['phases'][phase]['head']],'source-head-final':['git','rev-parse','HEAD'],'source-diff-final':['git','diff','--exit-code'],'source-index-final':['git','diff','--cached','--exit-code']}
 if phase=='fixed':argv['source-parent']=['git','rev-parse','HEAD^']
 for name,lane in manifest['lanes'].items():
  argv[name+'-packages']=['go','list',lane['scope']]
  argv[name+'-pristine-list']=['go','test','-json','-count=1','-list','^(Test|Example|Fuzz)']+(['-race'] if lane['race'] else [])+[lane['scope']]
  argv[name+'-tests']=['go','test','-json','-count=1']+(['-race'] if lane['race'] else [])+[lane['scope']]
 return argv
try:
 dirs={'baseline':a.baseline,'fixed':a.fixed};parsed={};listed={};inventory_sets={};command_counts={}
 for phase,directory in dirs.items():
  expected=manifest['phases'][phase];result=json.loads((directory/'result.json').read_text());runtime=json.loads((directory/'runtime.json').read_text());source=Path(runtime['sourceRoot'])
  if result.get('status')!='PASS_NATIVE_PHASE_PENDING_COMPARISON' or result.get('head')!=expected['head'] or result.get('tree')!=expected['tree']:raise ValueError('native source/result mismatch')
  if runtime['system']!='Linux' or runtime['machine']!='x86_64' or runtime['goVersion']!='go version go1.26.4 linux/amd64' or runtime['goEnv']['GOOS']!='linux' or runtime['goEnv']['GOARCH']!='amd64':raise ValueError('native runtime mismatch')
  if runtime['GOFLAGS']!='-p=2 -mod=readonly' or runtime['GOMAXPROCS']!='2' or runtime['GOTOOLCHAIN']!='local':raise ValueError('canonical build/test environment mismatch')
  fixture=json.loads((directory/'fixture.json').read_text())
  if fixture!={'path':manifest['fixturePath'],'sha256':manifest['fixtureSHA256'],'transplanted':phase=='baseline'}:raise ValueError('frozen actual regression differs')
  if json.loads((directory/'fixture-after.json').read_text())!=fixture:raise ValueError('regression fixture changed during native tests')
  harness_hashes=json.loads((directory/'harness-hashes.json').read_text())
  for file in Path(__file__).parent.iterdir():
   if file.is_file() and file.suffix in ['.py','.json','.go','.yml'] and harness_hashes.get(file.name)!=hashlib.sha256(file.read_bytes()).hexdigest():raise ValueError('actual harness source hash mismatch')
  before=json.loads((directory/'before-tracked.json').read_text());after=json.loads((directory/'after-tracked.json').read_text())
  if before!=after or not before:raise ValueError('tracked source mutated/missing')
  if phase=='fixed' and any(before[path]['sha256']!=sha for path,sha in manifest['fixedSourceHashes'].items()):raise ValueError('candidate frozen source hashes differ')
  commands=json.loads((directory/'commands.json').read_text());wanted=expected_commands(phase,source)
  if len(commands)!=len(wanted) or {c['label'] for c in commands}!=set(wanted):raise ValueError('canonical command inventory differs')
  for c in commands:
   label=c['label'];expected_exit=1 if phase=='baseline' and label in ['cli-tests','endpoint-race-tests'] else 0
   cwd=source/'cli/beacon' if label in ['cli-build-real-hooks','actual-cli-version','actual-cli-traces-help'] else source
   for name,lane in manifest['lanes'].items():
    if label in [name+'-packages',name+'-pristine-list',name+'-tests']:cwd=source/lane['module']
   if c['argv']!=wanted[label] or c['cwd']!=str(cwd) or c['actualExit']!=expected_exit or c['expectedExit']!=expected_exit or c['error'] or not c['start'] or not c['end']:raise ValueError('native command receipt mismatch: '+label)
   validate_timestamps(c['start'],c['end'])
   if c['stdoutSHA256']!=hashlib.sha256((directory/(label+'.stdout')).read_bytes()).hexdigest() or c['stderrSHA256']!=hashlib.sha256((directory/(label+'.stderr')).read_bytes()).hexdigest():raise ValueError('raw command log hash mismatch')
  for label in ['source-head-initial','source-head-final']:
   if (directory/(label+'.stdout')).read_text().strip()!=expected['head']:raise ValueError('actual source head mismatch')
  if (directory/'source-tree-initial.stdout').read_text().strip()!=expected['tree']:raise ValueError('actual source tree mismatch')
  if phase=='fixed' and (directory/'source-parent.stdout').read_text().strip()!=manifest['phases']['baseline']['head']:raise ValueError('actual parent mismatch')
  binaries=json.loads((directory/'build-binaries.json').read_text())
  binary_paths={'cli/beacon-hooks/beacon-hooks','cli/beacon/internal/embedded/hooks.bin','cli/beacon/beacon'}
  if set(binaries)!=binary_paths or any(v['bytes']<100000 or len(v['sha256'])!=64 for v in binaries.values()):raise ValueError('actual native build binaries missing')
  if binaries['cli/beacon-hooks/beacon-hooks']!=binaries['cli/beacon/internal/embedded/hooks.bin']:raise ValueError('built native hooks differ from actual embed')
  command_counts[phase]=len(commands);parsed[phase]={};listed[phase]={};inventory_sets[phase]={}
  recorded=json.loads((directory/'inventories.json').read_text())
  for name,lane in manifest['lanes'].items():
   inventory=set((directory/(name+'-packages.stdout')).read_text().splitlines())
   if not inventory or set(recorded['packages'][name])!=inventory:raise ValueError('recorded package inventory differs')
   inventory_sets[phase][name]=inventory;listed[phase][name]=list_tests((directory/(name+'-pristine-list.stdout')).read_text(),inventory)
   if set(recorded['listedMethods'][name])!=listed[phase][name][0] or recorded['listedPackageOutcomes'][name]!={k:list(v) for k,v in listed[phase][name][1].items()}:raise ValueError('recorded listed methods differ')
   parsed[phase][name]=parse((directory/(name+'-tests.stdout')).read_text(),inventory)
 if inventory_sets['baseline']!=inventory_sets['fixed']:raise ValueError('native package sets changed')
 lanes={name:compare(parsed['baseline'][name],parsed['fixed'][name],listed['baseline'][name],listed['fixed'][name],lane['affected']) for name,lane in manifest['lanes'].items()}
 result={'status':'PASS','baseline':manifest['phases']['baseline'],'fixed':manifest['phases']['fixed'],'native':'Linux amd64 Go1.26.4 only','moduleCount':5,'testLaneCount':6,'commandCounts':command_counts,'lanes':lanes,'scope':'full five Go modules and endpoint race, actual hooks/CLI build; paid sandbox and other platforms not verified'}
except Exception as error:result={'status':'FAIL','error':str(error)}
a.output.write_text(json.dumps(result,indent=2));print(json.dumps(result))
if result['status']!='PASS':raise SystemExit(1)
