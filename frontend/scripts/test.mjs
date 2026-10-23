import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import path from 'node:path';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const root = path.resolve(import.meta.dirname, '..');

function environment(options = {}) {
  const data = new Map();
  const storage = { getItem:k=>data.get(k)??null, setItem:(k,v)=>data.set(k,v), removeItem:k=>data.delete(k) };
  const window = new EventTarget();
  window.localStorage = storage; window.sessionStorage = storage;
  const scope = vm.createContext({window, console, Event, CustomEvent, AbortController, AbortSignal, DOMException,
    URL, URLSearchParams, Headers, Response, TextDecoder, crypto:globalThis.crypto, fetch:(...args)=>scope.fetchImpl(...args)});
  const modules = new Map();
  function load(name, parent = root) {
    if (options.mocks && Object.hasOwn(options.mocks,name)) return options.mocks[name];
    if (options.shallowComponents && name.startsWith('../components/')) return {__esModule:true,default:path.basename(name)};
    if (name.endsWith('.css')) return {};
    if (name.endsWith('.json')) return JSON.parse(readFileSync(path.resolve(parent,name),'utf8'));
    if (name === 'react') return options.react || {useEffect: fn => fn(), useSyncExternalStore: (subscribe, snapshot) => {subscribe(()=>{});return snapshot();}};
    const base = name.startsWith('.') ? path.resolve(parent, name) : path.join(root, name.replace(/^@\//,''));
    const file = [`${base}.ts`,`${base}.tsx`,path.join(base,'index.ts')].find(file=>existsSync(file));
    if (modules.has(file)) return modules.get(file).exports;
    const record = {exports:{}}; modules.set(file,record);
    const code = ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
    vm.runInContext(`(function(exports,require,module){${code}\n})`,scope,{filename:file})(record.exports,name=>load(name,path.dirname(file)),record);
    return record.exports;
  }
  return {load,scope,window,data,storage};
}

// Exercise component effects and callbacks without a browser or paid APIs.
function componentEnvironment() {
  const cells=[];let cursor=0,dirty=true,component,props,tree;const effects=[];
  const same=(left,right)=>left&&right&&left.length===right.length&&left.every((value,index)=>Object.is(value,right[index]));
  const react={
    useState(initial){const index=cursor++;const cell=cells[index]??=( {value:typeof initial==='function'?initial():initial} );return [cell.value,value=>{const next=typeof value==='function'?value(cell.value):value;if(!Object.is(cell.value,next)){cell.value=next;dirty=true}}]},
    useRef(initial){return cells[cursor++]??={current:initial}},
    useMemo(compute,deps){const index=cursor++;if(!same(cells[index]?.deps,deps))cells[index]={deps,value:compute()};return cells[index].value},
    useEffect(effect,deps){const index=cursor++;if(!same(cells[index]?.deps,deps))effects.push(()=>{cells[index]?.cleanup?.();cells[index]={deps,cleanup:effect()}})},
  };
  react.useCallback=(callback,deps)=>react.useMemo(()=>callback,deps);react.useLayoutEffect=react.useEffect;
  react.useSyncExternalStore=(_subscribe,snapshot)=>snapshot();
  const jsx=(type,props,key)=>({type,props:props||{},key});
  react.createElement=(type,props,...children)=>jsx(type,{...props,...(children.length?{children:children.length===1?children[0]:children}:{})},props?.key);
  const message={success(){},error(){},warning(){},info(){}};const antd={App:{useApp:()=>({message})},Layout:{Content:'Content'},Typography:{Text:'Text',Paragraph:'Paragraph',Title:'Title'},Input:{TextArea:'TextArea'},Empty:Object.assign(()=>null,{PRESENTED_IMAGE_SIMPLE:'empty'})};
  antd.Checkbox={Group:'CheckboxGroup'};
  for(const name of ['Alert','Button','Drawer','Modal','Table','Popconfirm','Segmented','Space','Spin','Tabs','Tag','Select','Tooltip'])antd[name]=name;
  const navigations=[];
  const mocks={'react/jsx-runtime':{jsx,jsxs:jsx,Fragment:'Fragment'},antd,'lucide-react':new Proxy({},{get:(_,name)=>name}),
    '../context':{useAttackPilotIdentity:()=>({userId:'alice',onLogin(){}})},'./MarkdownRenderer':{__esModule:true,default:'MarkdownRenderer'},
    '../services/navigation':{useNavigate:()=>path=>navigations.push(path),useParams:()=>({taskId:'task'})}};
  const env=environment({react,mocks,shallowComponents:true});env.scope.WebSocket={OPEN:1,CLOSED:3};
  env.scope.setInterval=()=>1;env.scope.clearInterval=()=>{};
  env.scope.setTimeout=()=>1;env.scope.clearTimeout=()=>{};env.window.location={hash:''};
  const render=()=>{cursor=0;dirty=false;tree=component(props);effects.splice(0).forEach(effect=>effect());return tree};
  const nodes=(value=tree)=>{const found=[],seen=new Set();function visit(item){if(!item||typeof item!=='object'||seen.has(item))return;seen.add(item);if(item.type&&item.props)found.push(item);for(const value of Object.values(item))visit(value)}visit(value);return found};
  return {...env,navigations,mount(next,nextProps){component=next;props=nextProps;return render()},nodes,
    async settle(){for(let turn=0;turn<12;turn++){if(dirty)render();await flush()}if(dirty)render();return tree},
    unmount(){for(const cell of cells)cell?.cleanup?.()},get tree(){return tree}};
}

test('account caches isolate users and retain unclaimed legacy reports',()=>{
  const env=environment(); const api=env.load('@/lib/browser-storage');
  env.data.set('cryptorisk.analysisRecords','legacy');
  api.setAccountScope('alice'); api.localStore.setItem('cryptorisk.analysisRecords','alice report');
  const aliceSignal=api.getAccountSignal(); api.setAccountScope('bob');
  assert.equal(aliceSignal.aborted,true); assert.equal(api.localStore.getItem('cryptorisk.analysisRecords'),null);
  api.localStore.setItem('cryptorisk.analysisRecords','bob report'); api.setAccountScope('alice');
  assert.equal(api.localStore.getItem('cryptorisk.analysisRecords'),'alice report');
  assert.equal(env.data.get('cryptorisk.analysisRecords'),'legacy');
  api.clearCurrentAccountStorage(); assert.equal(api.localStore.getItem('cryptorisk.analysisRecords'),null);
  api.setAccountScope('bob'); assert.equal(api.localStore.getItem('cryptorisk.analysisRecords'),'bob report');
});

test('storage quota and unavailable storage fall back with a warning',()=>{
  const env=environment(); const api=env.load('@/lib/browser-storage'); let warnings=0;
  env.window.addEventListener(api.storageWarningEvent,()=>warnings++);
  Object.defineProperty(env.window,'localStorage',{get(){throw new Error('SecurityError')}});
  api.localStore.setItem('draft','中文 🌏'); assert.equal(api.localStore.getItem('draft'),'中文 🌏');
  api.localStore.removeItem('draft'); assert.equal(api.localStore.getItem('draft'),null); assert.equal(warnings,1);
});

test('cache invalidation does not allow an old response to repopulate cache',async()=>{
  const env=environment();const api=env.load('@/lib/api');const resolvers=[];let calls=0;
  env.scope.fetchImpl=()=>{calls++;return new Promise(resolve=>resolvers.push(resolve))};
  const old=api.fetchRiskOverview(); api.clearApiCache();const fresh=api.fetchRiskOverview();
  resolvers[1](Response.json({version:2}));await fresh;
  resolvers[0](Response.json({version:1}));await old;
  assert.equal((await api.fetchRiskOverview()).version,2); assert.equal(calls,2);
});

test('requestJson keeps Headers instances, CSRF and Pydantic validation messages',async()=>{
  const env=environment();const api=env.load('@/lib/api');let sent;
  env.scope.fetchImpl=async(_url,init)=>{sent=init;return Response.json({detail:[{msg:'请输入有限正数'}]},{status:422})};
  await assert.rejects(api.requestJson('/api/user-assets',{method:'POST',headers:new Headers({'X-Test':'ok'})}),/请输入有限正数/);
  assert.equal(sent.headers.get('X-Test'),'ok'); assert.equal(sent.headers.get('X-CryptoRisk-CSRF'),'1');
});

test('SSE decodes split UTF-8, CRLF, multiline JSON and a final event without blank line',async()=>{
  const {readEventStream}=environment().load('@/lib/event-stream');const text=': ping\r\nevent: chunk\r\ndata: {"content":\r\ndata: "中文 🌏"}\r\n\r\nevent: result\ndata: {"ok":true}';
  const bytes=new TextEncoder().encode(text);let offset=0;const events=[];
  const body=new ReadableStream({pull(c){if(offset>=bytes.length)c.close();else c.enqueue(bytes.slice(offset,++offset));}});
  await readEventStream(new Response(body),(name,data)=>events.push({name,data}));
  assert.equal(events.length,2);assert.equal(events[0].data.content,'中文 🌏');assert.equal(events[1].data.ok,true);
});

test('malformed SSE cancels and releases its reader',async()=>{
  const {readEventStream}=environment().load('@/lib/event-stream');let cancelled=false;
  const body=new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('data: broken\n\n'));},cancel(){cancelled=true}});
  await assert.rejects(readEventStream(new Response(body),()=>{}),/数据格式异常/);
  assert.equal(cancelled,true); assert.equal(body.locked,false);
});

test('assistant treats empty or interrupted streams as failure',async()=>{
  const env=environment();const api=env.load('@/lib/api');env.scope.fetchImpl=async()=>new Response('event: done\ndata: {}\n\n');
  await assert.rejects(api.streamRiskAssistant('hi',{},()=>{}),/未收到回答/);
  await assert.rejects(api.streamChatMessage('hi',()=>{}),/未收到完整报告/);
});

test('SSE bounds even a complete oversized event in a single network chunk',async()=>{
  const {readEventStream}=environment().load('@/lib/event-stream');let dispatched=false;
  const body='data: '+JSON.stringify({content:'x'.repeat(4_000_001)})+'\n\n';
  await assert.rejects(readEventStream(new Response(body),()=>{dispatched=true}),/响应过大/);
  assert.equal(dispatched,false);
});


test('navigation rejects protocol-relative, backslash and executable URLs', () => {
  const {load} = environment(); const {safeInternalPath, safeHttpUrl} = load('@/lib/safe-url');
  for (const value of ['//evil.test', '/\\evil.test', '/\tevil.test', 'https://evil.test']) assert.equal(safeInternalPath(value), '');
  assert.equal(safeInternalPath('/news?range=7d'), '/news?range=7d');
  for (const value of ['javascript:alert(1)', 'data:text/html,hello', 'file:///etc/passwd', '//evil.test']) assert.equal(safeHttpUrl(value), '');
  assert.equal(safeHttpUrl('https://example.com/news'), 'https://example.com/news');
});


test('market candles merge revisions, sort and bound history', () => {
  const {load}=environment();const {mergeCandles}=load('@/lib/market');
  const candle=(time,close=10)=>({time,open:10,high:12,low:8,close,volume:1});
  const rows=mergeCandles([candle(2),candle(1)],[candle(2,11),candle(3),candle(4)],3);
  assert.deepEqual(Array.from(rows,row=>row.time),[2,3,4]);assert.equal(rows[0].close,11);
  assert.equal(mergeCandles([], [{...candle(1),close:NaN}]).length,0);
});

test('market indicators have correct warmup and flat-market RSI', () => {
  const {load}=environment();const {sma,ema,rsi}=load('@/lib/market');
  const candles=Array.from({length:30},(_,i)=>({time:i+1,open:10,high:11,low:9,close:10,volume:1}));
  assert.equal(sma(candles,10).length,21);assert.equal(ema(candles,20).length,11);
  assert.ok(rsi(candles).every(point=>point.value===50));
  const increasing=candles.map((c,i)=>({...c,close:i+1}));
  assert.equal(sma(increasing,10)[0].value,5.5);assert.equal(rsi(increasing)[0].value,100);
});


test('market size formatting does not turn small nonzero orders into zero', () => {
  const {load}=environment();const {compact}=load('@/lib/market');
  assert.equal(compact(0.00014),'0.00014');assert.notEqual(compact(1e-10),'0');
  assert.equal(compact(undefined),'—');
});


test('legacy portfolio links only resolve to supported markets or follow management',()=>{
  const {legacyPortfolioTarget,normalizeMarketSymbol}=environment().load('@/lib/market-symbols');
  assert.equal(legacyPortfolioTarget('btc'),'/market?symbol=BTCUSDT');
  for(const value of ['TON','../../settings','https://bad.example','',null]) assert.equal(legacyPortfolioTarget(value),'/my?tab=assets');
  assert.equal(normalizeMarketSymbol('SOLUSDT'),'SOLUSDT');
});

const flush=()=>new Promise(resolve=>setImmediate(resolve));
const followRow=symbol=>({symbol,base_asset:symbol.replace(/USDT$/,''),name:symbol,alert_threshold:70,created_at:'old',updated_at:'old'});
test('guest follows stay local and are never silently imported at login',async()=>{
  const env=environment(),storage=env.load('@/lib/browser-storage'),follows=env.load('@/lib/follows');const requests=[];
  env.scope.fetchImpl=async(url,init)=>{requests.push({url,method:init.method||'GET'});return Response.json({items:[],revision:'alice-empty'})};
  follows.useFollows();assert.equal(await follows.changeFollow('TONUSDT','add'),true);
  assert.ok(follows.readGuestFollows().includes('TONUSDT'));assert.equal(requests.length,0);
  storage.setAccountScope('alice');await flush();
  assert.equal(follows.useFollows().items.length,0);assert.ok(requests.every(r=>r.method==='GET'));
  storage.setAccountScope(null);assert.ok(follows.useFollows().items.some(item=>item.symbol==='TONUSDT'));
});

test('follow saves serialize, deduplicate clicks and retain state on failure',async()=>{
  const env=environment(),storage=env.load('@/lib/browser-storage'),follows=env.load('@/lib/follows');
  storage.setAccountScope('alice');let resolveMutation;let writes=0;
  env.scope.fetchImpl=async(_url,init)=>{if(!init.method||init.method==='GET')return Response.json({items:[],revision:'empty'});writes++;return new Promise(resolve=>{resolveMutation=resolve})};
  follows.useFollows();await flush();
  const pending=follows.changeFollow('BTCUSDT','add');await flush();assert.equal(await follows.changeFollow('BTCUSDT','add'),false);assert.equal(writes,1);
  resolveMutation(Response.json({items:[followRow('BTCUSDT')],revision:'saved'}));assert.equal(await pending,true);
  env.scope.fetchImpl=async()=>Response.json({detail:'保存失败'},{status:500});
  assert.equal(await follows.changeFollow('BTCUSDT','remove'),false);assert.equal(follows.useFollows().items.length,1);assert.match(follows.useFollows().error,/保存失败/);
});

test('late follow response cannot cross account boundaries',async()=>{
  const env=environment(),storage=env.load('@/lib/browser-storage'),follows=env.load('@/lib/follows');let resolveMutation;
  storage.setAccountScope('alice');
  env.scope.fetchImpl=async(_url,init)=>init.method==='POST'?new Promise(resolve=>{resolveMutation=resolve}):Response.json({items:[],revision:'empty'});
  follows.useFollows();await flush();const save=follows.changeFollow('BTCUSDT','add');await flush();
  storage.setAccountScope('bob');await flush();resolveMutation(Response.json({items:[followRow('BTCUSDT')],revision:'alice'}));assert.equal(await save,false);
  assert.equal(follows.useFollows().scope,'bob');assert.equal(follows.useFollows().items.length,0);
});


test('malformed follow responses cannot replace a usable list',()=>{
  const {parseFollowSnapshot}=environment().load('@/lib/follows');
  for(const value of [null,{}, {items:null,revision:'1'}, {items:[{}],revision:'1'}, {items:[{...followRow('BTCUSDT'),alert_threshold:NaN}],revision:'1'}])assert.throws(()=>parseFollowSnapshot(value),/格式异常/);
  assert.equal(parseFollowSnapshot({items:[followRow('BTCUSDT'),followRow('BTCUSDT')],revision:'1'}).items.length,1);
});

test('AttackPilot incomplete analyses never produce risk scores',()=>{
  const {analyzeAgentConsistency}=environment().load('@/components/attackpilot/utils/agentConsistency');
  for (const status of ['failed','running','pending','cancelled','completed']) {
    const result=analyzeAgentConsistency({status,final_report:null},[{type:'LOG',agent:'Workflow',message:'failed'}],null);
    assert.equal(result.status,'unavailable');assert.equal(result.score,null);assert.equal(result.checks.length,0);
  }
  const completed=analyzeAgentConsistency({status:'completed',final_report:'Root cause: withdraw() violates invariant.'},[],null);
  assert.equal(typeof completed.score,'number');assert.equal(completed.checks.length,5);
});

test('AttackPilot missing dollar valuations stay unknown while measured zero remains zero',()=>{
  const {formatUsdDelta}=environment().load('@/components/attackpilot/utils/presentation');
  for(const value of [null,undefined,NaN,Infinity,-Infinity])assert.equal(formatUsdDelta(value),'未知');
  assert.equal(formatUsdDelta(0),'$0');assert.equal(formatUsdDelta(10),'+$10');assert.equal(formatUsdDelta(-10),'$-10');
});

test('AttackPilot attack summaries ignore verification tables, patch code and valuation sections',()=>{
  const {reportNarrativeParagraphs,findNarrativeSummary}=environment().load('@/components/attackpilot/utils/reportNarrative');
  const report=[
    '## 补丁验证状态：尚未确认','',
    '| 检查项 | 记录结果 |','|---|---|','| 执行阶段 / 状态 | judge / unverified |','| 回放收益估值 | 未知 |','',
    '验证结论仅覆盖攻击路径，尚未验证触发交易。','',
    '## Applied Patches（实际应用补丁）','','```solidity','require(pool.transfer(), "profit trigger");','```','',
    '## 漏洞根因','','该漏洞在份额计算中丢失精度。','',
    '### 攻击准备','','攻击者先创建流动性池。','',
    '### 漏洞触发','','1. 攻击者调用 convert，触发错误的份额换算','2. 赎回放大后的份额','',
    '### 状态操纵','','池中的余额状态与份额记录不一致。','',
    '### 攻击获利','','攻击者转移底层资产获得收益。','',
    '## 补丁建议','','应在执行 transfer 前增加校验，阻止获利。','',
    '## 价格证据','','历史参考收益未知。',
  ].join('\n');
  const paragraphs=reportNarrativeParagraphs(report),joined=paragraphs.map(row=>row.content).join('\n');
  assert.ok(!joined.includes('|'));assert.ok(!joined.includes('judge'));assert.ok(!joined.includes('require('));assert.ok(!joined.includes('历史参考'));
  assert.match(joined,/1\. 攻击者调用 convert/);
  assert.match(findNarrativeSummary(report,['执行','触发','调用'],'missing',360,['漏洞触发']),/convert/);
  assert.equal(findNarrativeSummary(report,['收益','获利'],'missing',360,['攻击获利']),'攻击者转移底层资产获得收益。');
});

test('AttackPilot status-only and pipe-less table reports never become attack narratives',()=>{
  const {findNarrativeSummary}=environment().load('@/components/attackpilot/utils/reportNarrative');
  const report='检查项 | 记录结果\n--- | ---\n执行状态 | unverified\n收益 | 未知\n\n```text\n调用执行并获利\n```';
  assert.equal(findNarrativeSummary(report,['执行','调用','收益'],'缺少攻击叙述'),'缺少攻击叙述');
  assert.equal(findNarrativeSummary('## Verification Status\n\nExecution and profit are unknown.',['profit'],'missing'),'missing');
});

test('AttackPilot explains missing trigger coverage without calling unrelated successful replay ineffective',()=>{
  const {getPatchVerificationPresentation:present}=environment().load('@/components/attackpilot/utils/verification');
  const tx='0x'+'a'.repeat(64),trigger='0x'+'7'.repeat(64);
  const coverage={mode:'independent_historical_transaction_pairs',modified_addresses:['0x'+'c'.repeat(40)],intercepted_transaction_hashes:[],unaffected_transaction_hashes:[tx],unresolved_transaction_hashes:[],sequence_replay_verified:false};
  const verification={schema_version:2,status:'unverified',reason_code:'patch_interception_not_established',replay_completed:true,replay_attempted:true,evidence_version:1,evidence_validated:false,scope:'attack_path_only',coverage};
  const task={status:'completed',result:{verification}};
  assert.equal(present(task).status,'unverified');assert.match(present(task).description,/未触及实际修改代码/);assert.match(present(task).description,/不能据此判断补丁有效或失效/);
  const missing={...task,result:{verification:{...verification,reason_code:'required_trigger_replay_missing',coverage:{...coverage,required_trigger_transaction_hashes:[trigger],unresolved_transaction_hashes:[trigger]}},replay_evidence:{schema_version:1,transactions:[{original_transaction_hash:tx,patched:{completed:true,status:'success'}}]}}};
  assert.equal(present(missing).status,'unverified');assert.match(present(missing).description,/缺少 1 笔应验证的源码触发交易/);assert.match(present(missing).description,/0x77777777/);assert.match(present(missing).description,/即使执行成功，也不能代替/);
  assert.ok(!present(missing).description.includes('补丁失效'));
  assert.equal(present(task).label,'证据不足');assert.match(present(task).nextStep,/重新定位触发交易/);
  assert.equal(present(missing).label,'证据不足');assert.match(present(missing).nextStep,/补齐触发交易/);
});

test('AttackPilot distinguishes missing evidence, capability and verifier errors without changing outcomes',()=>{
  const {getPatchVerificationPresentation:present,getPatchVerificationDimensions:dimensions}=environment().load('@/components/attackpilot/utils/verification');
  for(const [reason,label,next] of [
    ['patched_trace_unavailable','证据不足',/补齐完整执行轨迹/],
    ['control_evidence_mismatch','证据不足',/原始交易对照/],
    ['historical_runtime_context_mismatch','证据不足',/原始交易对照/],
    ['missing_source','无法验证',/对应历史版本/],
    ['source_fetch_failed','验证异常',/重试源码获取/],
    ['source_not_verified','无法验证',/已验证源码/],
    ['patched_trace_format_unsupported','验证异常',/适配执行轨迹格式/],
    ['patched_trace_invalid','验证异常',/复核原始执行轨迹/],
    ['replay_timeout','验证异常',/修复验证服务/],
    ['tenderly_unauthorized','验证异常',/修复验证服务/],
    ['judge_negative_unsubstantiated','判定待复核',/复核判定/],
  ]){
    const task={status:'completed',result:{verification:{schema_version:2,status:'unverified',reason_code:reason,replay_completed:true,evidence_version:1,evidence_validated:false,dimensions:{attack_interception:{status:'passed'},normal_regression:{status:'passed',evidence_validated:true},profit:{status:'available',usd:25}}}}};
    const summary=present(task);assert.equal(summary.status,'unverified',reason);assert.equal(summary.label,label,reason);assert.match(summary.nextStep,next);assert.notEqual(summary.color,'success');
    assert.deepEqual(Array.from(dimensions(task),item=>item.value),['待核实','未验证','无法确认']);
  }
  const unknown=present({result:{verification:{status:'unverified',reason_code:'future_reason',reason:'已经确认成功',next_action:'revise_patch'}}});
  assert.equal(unknown.status,'unverified');assert.equal(unknown.label,'尚未确认');assert.ok(!unknown.description.includes('已经确认成功'));assert.equal(unknown.nextStep,undefined);
  for(const status of ['blocked','error','unverified']){
    const fetchFailure=present({result:{verification:{status,reason_code:'source_fetch_failed'}}});
    assert.equal(fetchFailure.description,'源码获取失败，请检查区块浏览器连接或稍后重试。');
    assert.match(fetchFailure.nextStep,/重试源码获取/);assert.ok(!fetchFailure.description.includes('尚未提供已验证源码'));
    const unverifiedSource=present({result:{verification:{status,reason_code:'source_not_verified'}}});
    assert.equal(unverifiedSource.description,'目标合约尚未提供已验证源码，无法生成可验证补丁。');
    assert.match(unverifiedSource.nextStep,/已验证源码/);
    const legacy=present({result:{verification:{status,reason_code:'missing_source'}}});
    assert.equal(legacy.description,'缺少可用源码，已停止补丁生成与回放。');
  }
  for(const reason of ['ineffective_patch','wrong_root_cause','broken_logic']){
    const pending=present({result:{verification:{status:'unverified',reason_code:reason}}});
    assert.equal(pending.label,'判定待复核');assert.match(pending.description,/尚不能确认/);
    const unsupported=present({result:{verification:{status:'failed',reason_code:reason}}});
    assert.equal(unsupported.status,'unverified');assert.match(unsupported.description,/不能据此/);
  }
});

test('AttackPilot presents observed successful modified execution without declaring attack success or failed verification',()=>{
  const {getPatchVerificationPresentation:present}=environment().load('@/components/attackpilot/utils/verification');
  const tx='0x'+'a'.repeat(64);
  const coverage={mode:'independent_historical_transaction_pairs',modified_addresses:['0x'+'c'.repeat(40)],intercepted_transaction_hashes:[],unaffected_transaction_hashes:[],unresolved_transaction_hashes:[tx],sequence_replay_verified:false};
  const verification={schema_version:2,status:'unverified',reason_code:'patch_interception_not_established',replay_completed:true,replay_attempted:true,evidence_version:1,evidence_validated:false,scope:'attack_path_only',next_action:'revise_patch',coverage};
  const summary=present({result:{verification}});assert.equal(summary.status,'unverified');assert.equal(summary.label,'未建立拦截');assert.match(summary.description,/不能据此判定攻击成功或根因错误/);assert.match(summary.nextStep,/相同的触发交易/);
  for(const changes of [{replay_completed:false},{replay_attempted:false},{schema_version:1},{evidence_version:undefined},{scope:undefined},{next_action:'collect_missing_evidence'},{coverage:undefined}]){
    const incomplete=present({result:{verification:{...verification,...changes}}});assert.equal(incomplete.status,'unverified');assert.equal(incomplete.label,'证据不足');assert.ok(!incomplete.description.includes('交易仍然成功'));
  }
  const verified={...verification,verification_policy_version:2,status:'verified',reason_code:'interception_confirmed',judge_verdict:'VERIFIED',replay_evidence_sha256:'d'.repeat(64),applied_patch_sha256:'e'.repeat(64),evidence_validated:true,dimensions:{attack_interception:{status:'passed'}},coverage:{...coverage,intercepted_transaction_hashes:[tx],unresolved_transaction_hashes:[]}};
  const replay_evidence={schema_version:1,status:'completed',applied_patch_sha256:verified.applied_patch_sha256};
  assert.equal(present({result:{verification:verified,replay_evidence}}).status,'verified');
  for(const changes of [{evidence_validated:false},{replay_attempted:false},{evidence_version:undefined},{dimensions:{attack_interception:{status:'unavailable'}}},{coverage},{coverage:undefined},{replay_evidence_sha256:undefined},{applied_patch_sha256:'f'.repeat(64)},{judge_verdict:'UNVERIFIED'}])assert.equal(present({result:{verification:{...verified,...changes},replay_evidence}}).status,'unverified');
  assert.equal(present({result:{verification:verified}}).status,'unverified');
  assert.equal(present({is_demo:true,result:{verification}}).status,'archived');
});

test('AttackPilot respects normalized API evidence and never invents regression or profit for attack-only replay',async()=>{
  const env=environment();const api=env.load('@/components/attackpilot/services/api');
  const {getPatchVerificationPresentation:present,getPatchVerificationDimensions:dimensions}=env.load('@/components/attackpilot/utils/verification');
  const tx='0x'+'a'.repeat(64);
  const verification={schema_version:2,verification_policy_version:2,status:'verified',reason_code:'attack_path_intercepted',judge_verdict:'VERIFIED',replay_completed:true,replay_attempted:true,evidence_version:1,evidence_validated:true,scope:'attack_path_only',replay_evidence_sha256:'d'.repeat(64),applied_patch_sha256:'e'.repeat(64),coverage:{mode:'independent_historical_transaction_pairs',modified_addresses:['0x'+'c'.repeat(40)],intercepted_transaction_hashes:[tx],unaffected_transaction_hashes:[],unresolved_transaction_hashes:[],sequence_replay_verified:false},dimensions:{attack_interception:{status:'passed'},normal_regression:{status:'passed',evidence_validated:true},profit:{status:'available',usd:2500}}};
  const task={task_id:'task',status:'completed',final_report:'Original model prose: verification passed.',result:{verification,replay_evidence:{schema_version:1,status:'completed',applied_patch_sha256:verification.applied_patch_sha256}}};
  env.scope.fetchImpl=async()=>Response.json(task);
  const verified=await api.getTask('task');assert.equal(present(verified).status,'verified');
  assert.deepEqual(Array.from(dimensions(verified),item=>item.value),['已通过','未验证','无法确认']);
  const {buildPatchVerificationMarkdown:markdown}=env.load('@/components/attackpilot/utils/verification');
  for(const policy of [undefined,null,1,3,true,'2']){
    task.result.verification={...verification,verification_policy_version:policy};
    const legacy=await api.getTask('task');
    assert.equal(present(legacy).status,'unverified',`policy=${String(policy)}`);
    assert.notEqual(present(legacy).color,'success');
    assert.deepEqual(Array.from(dimensions(legacy),item=>item.value),['待核实','未验证','无法确认']);
    assert.ok(!markdown(legacy).includes('触发交易拦截通过'));
    assert.equal(legacy.final_report,task.final_report);
  }
  task.result.verification={...verification,status:'unverified',evidence_validated:false,reason_code:'replay_evidence_invalid',dimensions:{attack_interception:{status:'unavailable'},normal_regression:{status:'not_run'},profit:{status:'unavailable',usd:null}}};
  const projected=await api.getTask('task');assert.equal(present(projected).status,'unverified');assert.equal(present(projected).label,'验证异常');
  assert.deepEqual(Array.from(dimensions(projected),item=>item.value),['待核实','未验证','无法确认']);
  assert.equal(projected.final_report,task.final_report);
});

test('AttackPilot treats unproven guard locations and revert propagation as missing evidence',()=>{
  const {getPatchVerificationPresentation:present,buildPatchVerificationMarkdown:markdown}=environment().load('@/components/attackpilot/utils/verification');
  for(const [reason,description,next] of [
    ['patch_guard_location_unproven',/错误文案相同不能证明执行了新增校验/,/源码映射与回滚指令位置/],
    ['revert_propagation_unproven',/子调用失败导致上层回滚的因果证据/,/错误包装的因果关系/],
  ]){
    const task={status:'completed',result:{verification:{schema_version:2,verification_policy_version:2,status:'unverified',reason_code:reason,replay_completed:true,replay_attempted:true,evidence_version:1,evidence_validated:false}}};
    const summary=present(task);
    assert.equal(summary.status,'unverified');assert.equal(summary.label,'证据不足');
    assert.match(summary.description,description);assert.match(summary.nextStep,next);
    assert.notEqual(summary.color,'success');assert.match(markdown(task),description);assert.match(markdown(task),next);
    assert.ok(!markdown(task).includes('触发交易拦截通过'));
  }
});

test('AttackPilot patch panel shows the specific recovery step for an unsupported trace',()=>{
  const env=componentEnvironment(),Panel=env.load('@/components/attackpilot/components/PatchVerificationPanel').default;
  env.mount(Panel,{task:{status:'completed',result:{verification:{status:'unverified',reason_code:'patched_trace_format_unsupported'}}},events:[]});
  const text=env.nodes().filter(node=>node.type==='Text'||node.type==='Paragraph'||node.type==='Tag').map(node=>node.props.children).flat().join('');
  assert.match(text,/验证异常/);assert.match(text,/下一步：适配执行轨迹格式后，用已有回放记录重新核验/);assert.ok(!text.includes('拦截通过'));env.unmount();
});

test('AttackPilot identifies unavailable compiler versions without blaming the source or exposing host diagnostics',()=>{
  const env=componentEnvironment(),Panel=env.load('@/components/attackpilot/components/PatchVerificationPanel').default;
  const {getPatchVerificationPresentation:present,getPatchCompileDiagnostics:diagnostics}=env.load('@/components/attackpilot/utils/verification');
  const diagnostic={address:'0x'+'a'.repeat(40),contract_name:'Game',compiler_version:'v0.8.23+commit.f704f362',reason_code:'compiler_unavailable',errors:[{severity:'error',message:'Unavailable compiler at /private/compiler/cache; INTERNAL_CONFIG=value'}]};
  const verification={status:'blocked',reason_code:'compiler_unavailable',replay_attempted:false,replay_completed:false,compile_diagnostics:[diagnostic]};
  for(const status of ['blocked','error','unverified']){
    const summary=present({result:{verification:{...verification,status}}});
    assert.match(summary.description,/缺少匹配的 Solidity 编译器，尚未开始补丁回放/);
    assert.match(summary.nextStep,/准确 Solidity 编译器版本/);assert.notEqual(summary.color,'success');
    assert.ok(!summary.description.includes('源码编译失败'));
  }
  const task={status:'completed',result:{verification}};
  env.mount(Panel,{task,events:[]});
  const text=env.nodes().filter(node=>node.type==='Text'||node.type==='Paragraph'||node.type==='Tag').map(node=>node.props.children).flat().join('');
  assert.match(text,/Game · Solidity v0.8.23\+commit.f704f362：未找到匹配的编译器/);
  assert.match(text,/下一步：补齐合约所需的准确 Solidity 编译器版本/);
  assert.ok(!text.includes('/private/'));assert.ok(!text.includes('INTERNAL_CONFIG'));assert.ok(!text.includes('拦截通过'));env.unmount();
  const malformed={...diagnostic,contract_name:'/private/Game.sol',address:'invalid',compiler_version:'/private/compiler'};
  const rows=diagnostics({result:{verification:{compile_diagnostics:[null,diagnostic,diagnostic,malformed]}}});
  assert.equal(rows.length,2);assert.equal(rows[1].target,'目标合约');assert.equal(rows[1].compilerVersion,undefined);
  assert.equal(diagnostics({result:{verification:{compile_diagnostics:{}}}}).length,0);
  assert.equal(diagnostics({result:{verification:{compile_diagnostics:Array.from({length:6},(_,index)=>({...diagnostic,contract_name:`Target${index}`}))}}}).length,3);
  const sourceFailure=present({result:{verification:{status:'blocked',reason_code:'original_compile_failed'}}});
  assert.match(sourceFailure.description,/原始源码编译失败/);assert.match(sourceFailure.nextStep,/原始源码、依赖和编译设置/);
});

test('AttackPilot API keeps chain, modules, encoded task paths and server errors',async()=>{
  const env=environment();const api=env.load('@/components/attackpilot/services/api');const requests=[];
  env.scope.fetchImpl=async(url,init)=>{requests.push({url,init});return Response.json({task_id:'task',status:'pending'})};
  const payload={tx_hash:'0x'+'a'.repeat(64),tx_hashes:['0x'+'a'.repeat(64)],chain:'bnbchain',modules:['attack_detection','fault_localization']};
  await api.startTransactionDeepAnalysis(payload);
  assert.equal(requests[0].url,'/api/attackpilot/tx-review/deep-analysis');
  assert.deepEqual(JSON.parse(requests[0].init.body),payload);assert.equal(requests[0].init.headers.get('X-CryptoRisk-CSRF'),'1');
  await api.getTask('a/b');assert.equal(requests[1].url,'/api/attackpilot/tasks/a%2Fb');
  await api.getTaskLogs('a/b',{after_id:12,limit:500});assert.equal(requests[2].url,'/api/attackpilot/tasks/a%2Fb/logs?after_id=12&limit=500');
  let login=0;env.window.addEventListener('attackpilot:login',()=>login++);
  env.scope.fetchImpl=async()=>Response.json({detail:'请先登录'},{status:401});
  await assert.rejects(api.getTask('private'),error=>api.errorMessage(error)==='请先登录');assert.equal(login,1);
  env.scope.fetchImpl=async()=>new Response('',{status:503});
  await assert.rejects(api.getTask('private'),error=>api.errorMessage(error).includes('暂时不可用'));
  const timeout=vm.runInContext('Object.assign(new Error("timed out"),{name:"TimeoutError"})',env.scope);
  env.scope.fetchImpl=async()=>{throw timeout};
  await assert.rejects(api.startTransactionDeepAnalysis(payload),/先在任务库检查/);
});

test('AttackPilot translation gets its backend time budget while caller and account cancellation still win',async()=>{
  const env=environment();const durations=[];
  env.scope.AbortSignal={timeout:ms=>{durations.push(ms);return new AbortController().signal},any:signals=>AbortSignal.any(signals)};
  const api=env.load('@/components/attackpilot/services/api');const storage=env.load('@/lib/browser-storage');
  env.scope.fetchImpl=async()=>Response.json({status:'ready'});
  await api.createReportTranslation('task');await api.getReportTranslation('task');await api.getTask('task');
  assert.deepEqual(durations,[300_000,120_000,120_000]);
  env.scope.fetchImpl=async(_url,init)=>new Promise((resolve,reject)=>{
    init.signal.addEventListener('abort',()=>reject(init.signal.reason),{once:true});
  });
  const caller=new AbortController();
  const cancelled=api.request('/tasks/task/report-translation',{method:'POST',signal:caller.signal});
  caller.abort();await assert.rejects(cancelled,error=>error.name==='AbortError');
  const accountChange=api.createReportTranslation('task');storage.setAccountScope('next-account');
  await assert.rejects(accountChange,error=>error.name==='AbortError');
});

function taskEnvironment() {
  const env=environment();const timers=new Map();const sources=[];let nextTimer=0;
  env.scope.setInterval=fn=>{const id=++nextTimer;timers.set(id,fn);return id};
  env.scope.clearInterval=id=>timers.delete(id);
  env.scope.EventSource=class {
    constructor(url){this.url=url;this.closed=false;sources.push(this)}
    close(){this.closed=true}
  };
  const events=env.load('@/components/attackpilot/services/TaskEventService').default;
  return {...env,events,sources,timers,poll:()=>Array.from(timers.values())[0]()};
}

test('AttackPilot recovers a missed SSE final event and drains duplicate log pages',async()=>{
  const env=taskEnvironment();const received=[];const errors=[];const cursors=[];
  env.events.subscribe(event=>received.push(event));
  env.scope.fetchImpl=async(url)=>{
    if(!url.includes('/logs?'))return Response.json({task_id:'task',status:'completed',final_report:'done',result:{verification:{status:'unverified'}}});
    const after=Number(new URL(url,'https://test.local').searchParams.get('after_id'));cursors.push(after);
    const persisted_id=after+1;
    return Response.json({events:[{type:'LOG',task_id:'task',log_id:after<2?'duplicate':'last',persisted_id,message:'evidence'}],next_after_id:persisted_id,has_more:after<2});
  };
  env.events.connect('task',()=>{},error=>errors.push(error));env.sources[0].onopen();
  await env.poll();
  assert.deepEqual(cursors,[0,1,2]);assert.equal(received.filter(event=>event.type==='LOG').length,2);
  assert.equal(received.find(event=>event.type==='TASK_FINAL').result.verification.status,'unverified');
  assert.equal(env.sources[0].closed,true);assert.equal(env.timers.size,0);assert.equal(errors.length,0);
});

test('AttackPilot polls without EventSource and stops a stalled pagination cursor',async()=>{
  const env=taskEnvironment();const errors=[];let recovered=0;
  env.scope.EventSource=class{constructor(){throw new Error('unsupported')}};
  env.scope.fetchImpl=async(url)=>Response.json(url.includes('/logs?')?{events:[],has_more:true,next_after_id:0}:{task_id:'task',status:'running'});
  env.events.connect('task',()=>recovered++,error=>errors.push(error));
  await env.poll();assert.equal(errors.length,2);assert.equal(recovered,1);
  env.scope.fetchImpl=async(url)=>Response.json(url.includes('/logs?')?{events:[],has_more:false,next_after_id:0}:{task_id:'task',status:'running'});
  await env.poll();assert.equal(recovered,2);assert.equal(env.events.getHistory().at(-1).status,'running');
  env.events.disconnect();assert.equal(env.timers.size,0);
});

test('AttackPilot exposes completed reports before slow or failed log recovery',async()=>{
  const env=taskEnvironment();const received=[];const errors=[];let finishLogs;
  env.events.subscribe(event=>received.push(event));
  env.scope.fetchImpl=async url=>url.includes('/logs?')?new Promise(resolve=>{finishLogs=resolve})
    :Response.json({task_id:'task',status:'completed',final_report:'persisted report'});
  env.events.connect('task',()=>{},error=>errors.push(error));env.sources[0].onopen();
  const pending=env.poll();await flush();
  assert.equal(received.find(event=>event.type==='TASK_FINAL')?.final_report,'persisted report');
  assert.equal(env.sources[0].closed,true);assert.equal(env.events.getConnectionState(),null);
  finishLogs(Response.json({detail:'logs unavailable'},{status:503}));await pending;
  assert.equal(env.timers.size,0);assert.match(errors.at(-1),/部分日志暂不可用/);
});

test('AttackPilot cancels old task requests and ignores their late results',async()=>{
  const env=taskEnvironment();const received=[];let finish;let oldSignal;
  env.events.subscribe(event=>received.push(event));
  env.scope.fetchImpl=async(url,init)=>{
    if(url.includes('/logs?'))return Response.json({events:[],has_more:false,next_after_id:0});
    oldSignal=init.signal;return new Promise(resolve=>{finish=resolve});
  };
  env.events.connect('old',()=>{},()=>{});env.sources[0].onopen();
  const pending=env.poll();await flush();
  env.events.connect('new',()=>{},()=>{});assert.equal(oldSignal.aborted,true);
  finish(Response.json({task_id:'old',status:'completed',final_report:'old account'}));await pending;
  assert.equal(received.length,0);assert.equal(env.events.getHistory().length,0);
  assert.equal(env.sources[0].closed,true);env.events.disconnect();
});

test('AttackPilot stops retrying a task after access expires',async()=>{
  const env=taskEnvironment();const errors=[];let login=0;
  env.window.addEventListener('attackpilot:login',()=>login++);
  env.scope.fetchImpl=async()=>Response.json({detail:'任务不存在或无权访问'},{status:404});
  env.events.connect('task',()=>{},error=>errors.push(error));env.sources[0].onopen();
  await env.poll();assert.equal(errors.at(-1),'任务不存在或无权访问');
  assert.equal(env.sources[0].closed,true);assert.equal(env.timers.size,0);assert.equal(login,0);
});

test('AttackPilot rejects malformed SSE terminal status and keeps recovery active',async()=>{
  const env=taskEnvironment();const errors=[];
  env.events.connect('task',()=>{},error=>errors.push(error));env.sources[0].onopen();
  env.sources[0].onmessage({data:JSON.stringify({type:'TASK_FINAL',task_id:'task',status:'running'})});
  env.sources[0].onmessage({data:JSON.stringify({type:'TASK_FINAL',task_id:'task'})});
  assert.equal(env.events.getHistory().length,0);assert.equal(env.sources[0].closed,false);assert.equal(env.timers.size,1);assert.equal(errors.length,2);
  env.events.disconnect();
});

test('AttackPilot deep analysis preserves the complete user scope and order without expanding a single selection',async()=>{
  const env=environment();const {buildDeepAnalysisRequest}=env.load('@/components/attackpilot/utils/requestPayloads');
  const api=env.load('@/components/attackpilot/services/api');const sent=[];
  const hashes=[
    '0xa815480589250d649314731d084fb4f58137b5fef70c8b19dc3cadc2ccc0b21f',
    '0x747088ed3054d66fbd2c2ec6f6e0b077e71c3155dab0d56ccea2b5841903738f',
    '0xba833487c09f934c7ed77ad415ff4f322d470a1fa508120aacea8a8f0bb656a9',
  ];
  env.scope.fetchImpl=async(url,init)=>{sent.push({url,payload:JSON.parse(init.body)});return Response.json({task_id:'mock-only'})};
  await api.startTransactionDeepAnalysis(buildDeepAnalysisRequest([...hashes,hashes[1].toUpperCase()],'ethereum',['patch_verification']));
  await api.startTransactionDeepAnalysis(buildDeepAnalysisRequest([hashes[2]],'bnbchain',['attack_detection']));
  assert.equal(sent[0].url,'/api/attackpilot/tx-review/deep-analysis');
  assert.deepEqual(sent[0].payload.tx_hashes,hashes);assert.equal(sent[0].payload.tx_hash,hashes[0]);
  assert.deepEqual(sent[0].payload.modules,['attack_detection','fault_localization','rag_retrieval','patch_generation','patch_verification']);
  assert.deepEqual(sent[1].payload.tx_hashes,[hashes[2]]);assert.equal(sent[1].payload.chain,'bnbchain');
  assert.throws(()=>buildDeepAnalysisRequest(hashes,'unknown',[]),/仅支持/);
});

function landingFixture() {
  const env=componentEnvironment(),requests=[],pending=[];
  env.scope.fetchImpl=async(url,init)=>{
    if(init.method==='POST'){
      requests.push({url,init});return new Promise(resolve=>pending.push(resolve));
    }
    if(url.endsWith('/dapps')||url.endsWith('/knowledge/vulnerabilities'))return Response.json({items:[]});
    if(url.endsWith('/capabilities'))return Response.json({model:{configured:true},chains:{ethereum:{rpc:true,explorer:true}},compiler:true,node:true,node_modules:true,tenderly:true,missing_dependencies:[]});
    return Response.json([]);
  };
  const Landing=env.load('@/components/attackpilot/pages/LandingWarRoom').default;
  env.mount(Landing,{});return {...env,requests,pending};
}

test('AttackPilot ignores repeated deep submissions and cancels navigation after leaving the workbench',async()=>{
  const env=landingFixture();await env.settle();
  env.nodes().find(node=>node.props.id==='ap-tx-hash-0').props.onChange({target:{value:'0x'+'a'.repeat(64)}});await env.settle();
  const start=env.nodes().find(node=>node.type==='Button'&&Array.isArray(node.props.children)&&node.props.children[0]==='直接开始分析');
  const first=start.props.onClick();const duplicate=start.props.onClick();await flush();
  assert.equal(env.requests.length,1);
  env.unmount();assert.equal(env.requests[0].init.signal.aborted,true);
  env.pending[0](Response.json({task_id:'late-task',status:'pending'}));await Promise.all([first,duplicate]);
  assert.deepEqual(env.navigations,[]);
});

test('AttackPilot stops the remaining case batch when the task list is left',async()=>{
  const env=componentEnvironment(),requests=[];let finish;
  env.scope.fetchImpl=async(url,init)=>{
    if(init.method==='POST'){requests.push({url,init});return new Promise(resolve=>{finish=resolve})}
    return Response.json(url.endsWith('/dapps')?{items:[]}:[]);
  };
  const TaskList=env.load('@/components/attackpilot/pages/TaskList').default;env.mount(TaskList,{});await env.settle();
  env.nodes().find(node=>node.type==='Select'&&node.props.mode==='multiple').props.onChange(['SushiSwap','Balancer']);await env.settle();
  const modal=env.nodes().find(node=>node.type==='Modal');
  const first=modal.props.onOk();const duplicate=modal.props.onOk();await flush();assert.equal(requests.length,1);
  env.unmount();assert.equal(requests[0].init.signal.aborted,true);
  finish(Response.json({task_id:'late-case',dapp_name:'SushiSwap',status:'pending'}));await Promise.all([first,duplicate]);
  assert.equal(requests.length,1);assert.deepEqual(env.navigations,[]);
});

test('AttackPilot unchanged status polls do not displace task evidence',async()=>{
  const env=taskEnvironment();const received=[];let archived=false;
  env.events.subscribe(event=>received.push(event));
  env.scope.fetchImpl=async()=>Response.json({task_id:'task',status:'running',archived});
  env.events.connect('task',()=>{},()=>{});env.sources[0].onopen();await env.poll();
  env.sources[0].onmessage({data:JSON.stringify({type:'LOG',task_id:'task',log_id:'evidence',message:'trace'})});
  for(let turn=0;turn<3;turn++)await env.poll();
  assert.equal(received.filter(event=>event.type==='TASK_STATUS').length,1);assert.equal(env.events.getHistory().length,2);
  archived=true;await env.poll();assert.equal(received.filter(event=>event.type==='TASK_STATUS').length,2);
  env.events.disconnect();
});

test('AttackPilot raw logs expose a manual recovery after the initial request fails',async()=>{
  const env=componentEnvironment();let calls=0;
  env.scope.fetchImpl=async()=>++calls===1?Response.json({detail:'暂时不可用'},{status:503}):Response.json({
    events:[{type:'LOG',log_id:'recovered',agent:'Workflow',level:'INFO',message_type:'text',message:'trace recovered'}],has_more:false,next_before_id:1,
  });
  const LogStream=env.load('@/components/attackpilot/components/LogStream').default;
  env.mount(LogStream,{taskId:'task',events:[],selectedAgent:'all',rawMode:true,onSelectLog(){}});await env.settle();
  const retry=env.nodes().find(node=>node.type==='Button'&&node.props.children==='重试日志加载');
  assert.ok(retry);assert.equal(retry.props.disabled,false);assert.equal(calls,1);
  await retry.props.onClick();await env.settle();assert.equal(calls,2);
  assert.ok(env.nodes().some(node=>node.key==='recovered'));
  assert.equal(env.nodes().some(node=>node.props.role==='alert'),false);env.unmount();
});

test('AttackPilot clips assistant request history and cancels cleared or unmounted sessions',async()=>{
  const env=componentEnvironment();const requests=[];const finishes=[];
  const storage=env.load('@/lib/browser-storage');const key='cryptorisk.attackpilot-assistant:alice:task:ethereum:task';
  storage.localStore.setItem(key,JSON.stringify([{id:'old',role:'assistant',content:'证'.repeat(4500)}]));
  env.scope.fetchImpl=async(_url,init)=>{requests.push(init);return new Promise(resolve=>finishes.push(resolve))};
  const Drawer=env.load('@/components/attackpilot/components/ForensicAssistantDrawer').default;
  const session=Drawer({open:true,onClose(){},scope:'task',taskId:'task'});env.mount(session.type,session.props);await env.settle();
  const ask=async()=>{
    env.nodes().find(node=>node.type==='TextArea').props.onChange({target:{value:'证据是什么？'}});await env.settle();
    const pending=env.nodes().find(node=>node.type==='Button'&&node.props.children==='发送').props.onClick();await env.settle();return {pending};
  };
  const first=await ask();const payload=JSON.parse(requests[0].body);
  assert.equal(payload.history[0].content.length,4000);assert.equal(payload.task_id,'task');
  assert.equal(env.nodes().find(node=>node.type==='MarkdownRenderer').props.content.length,4500);
  env.nodes().find(node=>node.type==='Button'&&node.props.children==='清空').props.onClick();await env.settle();
  assert.equal(requests[0].signal.aborted,true);
  finishes[0](Response.json({answer:'late answer',sources:[]}));await first.pending;await env.settle();
  assert.equal(env.nodes().some(node=>node.type==='MarkdownRenderer'),false);
  const second=await ask();env.unmount();assert.equal(requests[1].signal.aborted,true);
  finishes[1](Response.json({answer:'another late answer',sources:[]}));await second.pending;
});

function dashboardFixture(translationResponse) {
  const env=componentEnvironment();const requests=[];const task={task_id:'task',dapp_name:'Mock Case',status:'completed',created_at:'2026-01-01',completed_at:'2026-01-02',final_report:'Original trace evidence',result:{verification:{status:'unverified'}}};
  env.scope.fetchImpl=async(url,init)=>{
    requests.push({url,method:init.method||'GET'});
    if(url.endsWith('/report-translation'))return translationResponse(init);
    if(url.includes('/logs?'))return Response.json({events:[],has_more:false});
    if(url.endsWith('/macro-analysis')||url.endsWith('/automated-review'))return Response.json({});
    return Response.json(task);
  };
  const Dashboard=env.load('@/components/attackpilot/pages/Dashboard').default;
  env.mount(Dashboard,{});return {...env,requests,task};
}

test('AttackPilot loads initial macro and consistency once and reuses a ready translation',async()=>{
  const env=dashboardFixture(()=>Response.json({status:'ready',translated_report:'中文证据'}));await env.settle();
  assert.equal(env.requests.filter(request=>request.url.endsWith('/macro-analysis')).length,1);
  assert.equal(env.requests.filter(request=>request.url.endsWith('/automated-review')).length,1);
  const language=()=>env.nodes().find(node=>node.type==='Segmented'&&node.props.options.some(option=>option.value==='original'));
  language().props.onChange('original');await env.settle();language().props.onChange('zh');await env.settle();
  assert.equal(env.requests.filter(request=>request.url.endsWith('/report-translation')).length,1);
  const report=env.nodes().find(node=>node.type==='StructuredReport');assert.equal(report.props.task.final_report,'中文证据');
  assert.equal(report.props.originalTask.final_report,env.task.final_report);assert.equal(report.props.originalTask.result.verification.status,'unverified');env.unmount();
});

test('AttackPilot translation failure preserves original evidence and retries only on explicit action',async()=>{
  let recovered=false;
  const env=dashboardFixture(init=>recovered?Response.json({status:'ready',translated_report:'中文证据'}):init.method==='POST'
    ?Response.json({detail:'翻译暂不可用'},{status:503}):Response.json({status:'missing',translated_report:null}));await env.settle();
  const translationRequests=()=>env.requests.filter(request=>request.url.endsWith('/report-translation'));
  assert.deepEqual(translationRequests().map(request=>request.method),['GET','POST']);
  const report=env.nodes().find(node=>node.type==='StructuredReport');assert.equal(report.props.task.final_report,env.task.final_report);
  assert.equal(report.props.originalTask.result.verification.status,'unverified');
  const warning=env.nodes().find(node=>node.type==='Alert'&&node.props.title==='中文译文暂时无法加载，当前显示原文。');assert.ok(warning);
  const language=()=>env.nodes().find(node=>node.type==='Segmented'&&node.props.options.some(option=>option.value==='original'));
  language().props.onChange('original');await env.settle();language().props.onChange('zh');await env.settle();
  assert.equal(translationRequests().length,2);
  recovered=true;warning.props.action.props.onClick();await env.settle();
  assert.deepEqual(translationRequests().map(request=>request.method),['GET','POST','GET']);env.unmount();
});

test('AttackPilot record ranking never promotes hashes or tool calls to verified evidence',()=>{
  const {inferEvidenceTier,enrichEvidenceItem,evidenceScoreLabel}=environment().load('@/components/attackpilot/utils/evidenceScoring');
  for(const item of [
    {source:'transaction',content:'0x'+'a'.repeat(64)},
    {source:'tool',message_type:'tool',content:'replay failed for 0x'+'a'.repeat(40)},
    {source:'agent_log',message_type:'result',content:'verification succeeded',evidence_tier:'verified'},
  ]){
    const record={id:'record',title:'attack verification',confidence:'high',...item};
    assert.notEqual(inferEvidenceTier(record),'verified');
    assert.notEqual(enrichEvidenceItem(record).evidence_tier,'verified');
    assert.ok(!enrichEvidenceItem(record).score_reasons.join(' ').includes('已验证'));
  }
  assert.equal(evidenceScoreLabel('strong'),'高相关');
});

test('AttackPilot failed replay mentions and final report repetition cannot create a passing consistency loop',()=>{
  const {analyzeAgentConsistency}=environment().load('@/components/attackpilot/utils/agentConsistency');
  const report='Root cause withdraw() and transfer(). Patch verification success claimed by model.';
  for(const verification of [undefined,{status:'blocked',reason_code:'compiler_unavailable'},{status:'failed'},{status:'verified'}]){
    const summary=analyzeAgentConsistency({status:'completed',final_report:report,result:{verification}},[
      {type:'LOG',agent:'Code Patcher',message:'patch failed, replay verification success was not established'}
    ],null);
    assert.notEqual(summary.checks.find(item=>item.id==='verification-loop').status,'pass');
    assert.notEqual(summary.checks.find(item=>item.id==='root-to-patch').status,'pass');
    assert.equal(summary.sharedFunctions.length,0);
  }
});

test('AttackPilot structured verification and exported Markdown use execution state over model success claims',async()=>{
  const env=componentEnvironment();
  env.scope.Blob=Blob;let exported;
  env.scope.URL={createObjectURL:blob=>{exported=blob;return 'blob:report'},revokeObjectURL(){}};
  env.scope.document={body:{appendChild(){}},createElement:()=>({click(){},remove(){}})};
  const Component=env.load('@/components/attackpilot/components/StructuredReport').default;
  const task={task_id:'task',dapp_name:'Case',created_at:'now',status:'completed',final_report:'## 验证结果\n\n补丁已通过，正常业务已验证。',result:{verification:{status:'blocked',reason_code:'compiler_unavailable'}}};
  env.mount(Component,{task,events:[]});await env.settle();
  const section=env.nodes().find(node=>node.props.id==='ap-report-section-verification_results');
  const content=env.nodes(section).find(node=>node.type==='MarkdownRenderer').props.content;
  assert.match(content,/缺少匹配的 Solidity 编译器/);assert.ok(!content.includes('正常业务已验证'));
  const button=env.nodes().find(node=>node.type==='Button'&&node.props.children==='导出 Markdown');
  button.props.onClick();const markdown=await exported.text();
  assert.match(markdown,/## 验证结果\n\n\*\*补丁暂时无法验证/);
  assert.match(markdown,/模型叙述保留供核对/);
  assert.ok(markdown.indexOf('缺少匹配的 Solidity 编译器')<markdown.indexOf('## 模型原始报告'));
  env.unmount();
});

test('AttackPilot report-only transaction references stay unclassified regardless of keyword or list order',async()=>{
  const env=componentEnvironment();
  const Component=env.load('@/components/attackpilot/components/KeyTransactionCards').default;
  env.mount(Component,{task:{task_id:'task',final_report:'create liquidity pool 0x'+'a'.repeat(64)+'\n\nprofit transfer 0x'+'b'.repeat(64)},events:[],macroAnalysis:null});await env.settle();
  const labels=env.nodes().filter(node=>node.type==='Tag').map(node=>node.props.children);
  assert.equal(labels.filter(label=>label==='交易引用 · 分类待核实').length,2);
  assert.ok(!labels.includes('攻击准备'));assert.ok(!labels.includes('攻击获利'));
  env.unmount();
});

test('AttackPilot explains baseline and layout blockers without treating replay reverts as verified interception',()=>{
  const {getPatchVerificationPresentation:present}=environment().load('@/components/attackpilot/utils/verification');
  for(const [reason,description,next] of [
    ['original_runtime_mismatch',/历史链上代码不匹配/,/编译设置/],
    ['storage_layout_unavailable',/无法取得原始合约存储布局/,/存储布局信息/],
    ['storage_layout_changed',/存储布局/,/槽位/],
    ['immutable_layout_mismatch',/不可变变量布局/,/部署值/],
    ['constructor_or_immutable_changed',/初始化条件与历史合约不一致/,/构造器/],
    ['patch_runtime_unchanged',/未改变实际执行代码/,/目标业务校验/],
    ['analysis_report_invalid',/未通过结果检查/,/输入交易/],
  ]){
    const result=present({status:'failed',result:{verification:{status:'blocked',reason_code:reason}}});
    assert.equal(result.status,'blocked');assert.match(result.description,description);assert.match(result.nextStep,next);
  }
});

test('AttackPilot repeated records across report sections do not inflate evidence totals',()=>{
  const {summarizeEvidenceHealth}=environment().load('@/components/attackpilot/utils/evidenceScoring');
  const record={source:'agent_log',content:'attack trace',agent:'Debugger',log_id:'one-log',confidence:'high'};
  const health=summarizeEvidenceHealth([{...record,id:'root-cause'},{...record,id:'attack-path'},{...record,id:'patch'}]);
  assert.equal(health.total,1);assert.equal(health.agents,1);
});

test('AttackPilot never truncates calldata or bytecode into a transaction hash',()=>{
  const {extractTransactionHashes}=environment().load('@/components/attackpilot/utils/evidence');
  const hash='0x'+'a'.repeat(64);
  assert.deepEqual(Array.from(extractTransactionHashes('runtime_bytecode 0x'+'b'.repeat(128)+'\ncalldata 0x'+'c'.repeat(72))),[]);
  assert.deepEqual(Array.from(extractTransactionHashes('('+hash+') '+hash.toUpperCase())),[hash]);
});
