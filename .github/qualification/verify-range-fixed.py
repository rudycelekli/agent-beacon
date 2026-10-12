from pathlib import Path
import json,subprocess,os,hashlib
proof=Path('proof');source=Path('candidate');baseline=json.loads(Path('.github/qualification/range-baseline-outcomes.json').read_text());prefix='TestShowTraceAroundOriginalNumberWithTypeFilter'
def parse(name):
 rows=[json.loads(x) for x in (proof/name).read_text().splitlines() if x.startswith('{')]
 outcomes={x['Test']:x['Action'] for x in rows if x.get('Test') and x['Action'] in ('pass','fail','skip')}
 runs={x['Test'] for x in rows if x.get('Test') and x['Action']=='run'}
 assert runs==set(outcomes),'missing terminal test identity'
 terminal=[x for x in rows if not x.get('Test') and x['Action'] in ('pass','fail','skip')]
 assert len(terminal)==1 and terminal[0]['Action']=='pass',terminal
 return outcomes
fixed=parse('fixed-dashboard.jsonl');race=parse('fixed-race.jsonl');original={t:v for t,v in baseline.items() if not t.startswith(prefix)};new={t:v for t,v in baseline.items() if t.startswith(prefix)}
assert len(original)==195 and len(new)==29
assert set(fixed)==set(baseline),'changed complete test identity set'
assert {t:fixed[t] for t in original}==original,'original outcome or skip changed'
assert all(fixed[t]=='pass' for t in new),'new case failed or skipped'
assert set(race)==set(new) and all(v=='pass' for v in race.values()),race
(proof/'fixed-outcomes.json').write_text(json.dumps(fixed,indent=2)+'\n')
fixture=proof/'runtime.jsonl';events=[]
for n in range(1,8):
 event={'timestamp':f'2026-06-11T10:00:0{n}Z','event':{'id':f'e{n}','action':'command.executed' if n%2==0 else 'prompt.submitted','category':'command' if n%2==0 else 'prompt'},'harness':{'name':'cursor'},'session':{'id':'around'}}
 event['command' if n%2==0 else 'prompt']={'command' if n%2==0 else 'text':f'command {n}' if n%2==0 else f'prompt {n}'};events.append(event)
fixture.write_text(''.join(json.dumps(x)+'\n' for x in events));binary=source/'cli/beacon/beacon';receipts=[]
cases=[
 ('anchor',['--around-event','4','--before','1','--after','1','--event-type','command'],[2,4,6],3,1,3),
 ('absent anchor',['--around-event','3','--before','1','--after','1','--event-type','command'],[2,4],3,1,2),
 ('first',['--around-event','2','--before','1','--after','1','--event-type','command'],[2,4],3,1,2),
 ('last',['--around-event','6','--before','1','--after','1','--event-type','command'],[4,6],3,2,2),
 ('before first',['--around-event','1','--before','1','--after','1','--event-type','command'],[2],3,1,1),
 ('after last',['--around-event','99','--before','1','--after','1','--event-type','command'],[6],3,3,1),
 ('defaults',['--around-event','4','--event-type','command'],[2,4,6],3,1,3),
 ('nonpositive context',['--around-event','4','--before','-1','--after','-2','--event-type','command'],[2,4,6],3,1,3),
 ('empty filter',['--around-event','4','--before','1','--after','1','--event-type','approval'],[],0,1,0),
 ('pagination',['--offset','2','--limit','1','--event-type','command'],[4],3,2,1),
 ('past end',['--offset','4','--limit','1','--event-type','command'],[],3,4,0),
 ('unfiltered',['--around-event','4','--before','1','--after','1'],[3,4,5],7,3,3),
 ('unfiltered boundary',['--around-event','1','--before','1','--after','1'],[1,2,3],7,1,3),
]
home=proof/'isolated-home'
home.mkdir()
for mode in ['fallback','history']:
 cli_env=dict(os.environ,CI='1',HOME=str(home.resolve()),BEACON_HISTORY_DB=str(proof/('absent/history.db' if mode=='fallback' else 'history.db')))
 history_path=Path(cli_env['BEACON_HISTORY_DB'])
 if mode=='fallback':assert not history_path.exists(),'fallback history exists before cases'
 if mode=='history':
  cmd=[str(binary),'endpoint','traces','reindex','--retention-days','36500','--json','--log-path',str(fixture)]
  run=subprocess.run(cmd,env=cli_env,text=True,capture_output=True)
  assert run.returncode==0,run.stderr
  assert (proof/'history.db').exists(),'actual SQLite history missing'
  receipts.append({'mode':mode,'operation':'reindex','args':cmd,'exit_code':run.returncode,'stdout':run.stdout,'stderr':run.stderr})
 for name,args,numbers,total,offset,limit in cases:
  cmd=[str(binary),'endpoint','traces','show','session:cursor:around','--json','--log-path',str(fixture),*args];run=subprocess.run(cmd,env=cli_env,text=True,capture_output=True);assert run.returncode==0,run.stderr;result=json.loads(run.stdout)
  assert [x['number'] for x in result['events'] or []]==numbers,(name,result)
  assert result['range']['total_events']==total and result['range']['offset']==offset and result['range'].get('limit',0)==limit and result['range']['returned_events']==len(numbers),(name,result)
  for event in result['events'] or []:
   n=event['number']
   if n%2==0:assert event['command']['command']==f'command {n}'
   else:assert event['content']['text']==f'prompt {n}'
  receipts.append({'mode':mode,'name':name,'args':cmd,'exit_code':run.returncode,'stdout':run.stdout,'stderr':run.stderr})
 if mode=='fallback':assert not history_path.exists(),'fallback history appeared after cases'
 else:assert history_path.exists(),'history disappeared after cases'
subprocess.run(['git','-C',str(source),'diff','--exit-code'],check=True)
files=subprocess.check_output(['git','-C',str(source),'diff','HEAD^','HEAD','--name-only'],text=True).splitlines()
(proof/'source-hashes.json').write_text(json.dumps({f:hashlib.sha256((source/f).read_bytes()).hexdigest() for f in files},indent=2)+'\n')
(proof/'shipping-cli-proof.json').write_text(json.dumps({'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'cases':receipts},indent=2)+'\n');print('Complete dashboard/race/26 actual shipping CLI history/fallback controls PASS')
