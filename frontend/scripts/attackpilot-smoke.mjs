// Offline browser check: no website server, Next build, model, or chain calls.
// Usage: node scripts/attackpilot-smoke.mjs /tmp/attackpilot-ui-check
import { createRequire } from 'node:module';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer';
import postcss from 'postcss';
import tailwind from '@tailwindcss/postcss';

const root = process.cwd();
const temporary = path.resolve(process.argv[2] || '/tmp/attackpilot-ui-check');
const { build } = createRequire(path.join(temporary, 'package.json'))('esbuild');
const fixture = JSON.parse(await readFile(path.join(temporary, 'fixtures.json'), 'utf8'));
const output = path.join(temporary, 'site');
await mkdir(output, { recursive: true });

const navigation = `import React, {useSyncExternalStore} from 'react';
const subscribe = cb => { window.addEventListener('popstate', cb); return () => window.removeEventListener('popstate', cb); };
const push = url => { history.pushState({}, '', url); window.dispatchEvent(new PopStateEvent('popstate')); };
const router = {push, replace:push, back:()=>history.back()};
export function usePathname(){return useSyncExternalStore(subscribe,()=>location.pathname)}
export function useRouter(){return router}
export function useParams(){return {taskId:usePathname().split('/')[3]}}
export default function Link({href,children,...props}) {return <a href={href} {...props} onClick={e=>{e.preventDefault();push(href)}}>{children}</a>}`;
await build({
  stdin: { contents: `import React,{useState} from 'react'; import {createRoot} from 'react-dom/client'; import Workbench from './components/attackpilot/workbench';
    function App(){const [user,setUser]=useState(null); return <div className="fixture-host"><button id="fixture-identity" onClick={()=>setUser(user?null:'alice')}>{user?'退出测试账号':'访客'}</button><Workbench userId={user} onLogin={()=>setUser('alice')} /></div>};
    createRoot(document.getElementById('root')).render(<App/>);`, resolveDir: root, loader: 'tsx' },
  outfile: path.join(output, 'check.js'), bundle: true, platform: 'browser', format: 'esm', jsx: 'automatic',
  define: { 'process.env.NODE_ENV': '"production"' },
  plugins: [{ name: 'next-test-router', setup(builder) {
    builder.onResolve({filter:/^next\/(link|navigation|dynamic|image)$/}, args=>({path:args.path, namespace:'test-next'}));
    builder.onLoad({filter:/.*/,namespace:'test-next'}, args=>({contents:args.path==='next/dynamic'
      ? `import React,{lazy,Suspense} from 'react'; export default function dynamic(loader,options={}) {const Component=lazy(loader); return props=><Suspense fallback={options.loading?.()}><Component {...props}/></Suspense>}`
      : args.path==='next/image' ? `import React from 'react'; export default function Image({unoptimized,...props}){return <img {...props}/>} ` : navigation, loader:'tsx', resolveDir:root}));
  }}],
});
const js = await readFile(path.join(output, 'check.js'));
const hostStyles = await postcss([tailwind({base: root})]).process(await readFile(path.join(root,'app/globals.css'),'utf8'), {from:path.join(root,'app/globals.css')});
const css = hostStyles.css + '\n' + await readFile(path.join(output, 'check.css'), 'utf8') + '\n.fixture-host{min-height:100vh}.report-language-toolbar{margin:12px 0}';
const logo = await readFile(path.join(root,'public/attackpilot/riskpilot_logo.png'));
const html = '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/check.css"></head><body style="margin:0;background:#f1f5f9;font-family:Arial,sans-serif"><div id="root"></div><script type="module" src="/check.js"></script></body></html>';
const errors = [], missing = [], mutations = [];
let useRecordedTranslation = false;
const liveId = '00000000-0000-4000-a000-000000000001';
const liveTask = {task_id:liveId,dapp_name:'Offline live task',status:'running',created_at:'2026-01-01T00:00:00Z',is_demo:false};
const browser = await puppeteer.launch({headless:true,executablePath:process.env.PUPPETEER_EXECUTABLE_PATH || undefined,args:['--no-sandbox','--disable-dev-shm-usage']});
try {
  const page = await browser.newPage();
  page.on('pageerror',error=>errors.push(error.message));
  await page.setRequestInterception(true);
  page.on('request', async request => {
    const url = new URL(request.url());
    if (url.origin !== 'https://attackpilot.test') return request.abort();
    if (url.pathname === '/attackpilot/riskpilot_logo.png') return request.respond({status:200,contentType:'image/png',body:logo});
    if (url.pathname === '/check.js') return request.respond({status:200,contentType:'application/javascript',body:js});
    if (url.pathname === '/check.css') return request.respond({status:200,contentType:'text/css',body:css});
    if (!url.pathname.startsWith('/api/')) return request.respond({status:200,contentType:'text/html',body:html});
    if (request.method() !== 'GET') mutations.push({path:url.pathname,csrf:request.headers()['x-cryptorisk-csrf'],body:request.postData()});
    if (!useRecordedTranslation && url.pathname.endsWith('/report-translation')) return request.respond({status:200,contentType:'application/json',body:JSON.stringify({task_id:url.pathname.split('/')[4],language:'zh-CN',source_language:'en',status:'ready',source_hash:'offline',translated_report:'# 离线中文报告夹具\n\n## 漏洞根因\n\n这是验证中文报告展示的模拟数据。\n\n- 保留原始证据\n- 对照实际调用\n\n## 攻击路径\n\n1. 获取临时资金\n2. 触发漏洞函数\n\n## 补丁建议\n\n增加权限校验。',cached:true,model:'offline mock',translated_at:'2026-09-12T00:00:00Z'})});
    if (['/api/attackpilot/tx-review','/api/attackpilot/tx-detect'].includes(url.pathname)) {
      const payload=JSON.parse(request.postData());
      const body=url.pathname.endsWith('/tx-detect') ? {chain:payload.chain,input_count:payload.tx_hashes.length,analyzed_count:payload.tx_hashes.length,invalid_hashes:[],deep_analysis_ready:true,risk_level:'high',summary:'离线批量检测成功',attack_candidates:payload.tx_hashes.map(tx_hash=>({tx_hash,summary:'离线交易信号',risk_level:'high',classification:'attack_candidate',signals:[],signal_details:[],metrics:{},matched_cases:[],live_observation_status:'ok'})),auxiliary_candidates:[],unrelated_candidates:[],unknown_candidates:[],recommended_tx_hashes:payload.tx_hashes,modules:payload.modules} : {risk_level:'high',summary:'离线单笔审查成功',tx_hash:payload.tx_hash,chain:payload.chain,signals:['离线交易信号'],signal_details:[],evidence:[],metrics:{},tx_type:'unreviewed_transaction',matched_cases:[],recommend_deep_analysis:true,deep_analysis_ready:true,live_observation_status:'ok'};
      return request.respond({status:200,contentType:'application/json',body:JSON.stringify(body)});
    }
    if (request.method()==='POST' && ['/api/attackpilot/tasks','/api/attackpilot/tx-review/deep-analysis'].includes(url.pathname)) return request.respond({status:200,contentType:'application/json',body:JSON.stringify(liveTask)});
    if (url.pathname.startsWith('/api/attackpilot/tasks/'+liveId)) {
      const suffix = url.pathname.slice(('/api/attackpilot/tasks/'+liveId).length);
      if (suffix==='/events') return request.respond({status:200,contentType:'text/event-stream',body:'id: 1\ndata: '+JSON.stringify({...liveTask,type:'TASK_FINAL',status:'completed',final_report:'Offline task report',result:{verification:{status:'skipped'}}})+'\n\n'});
      const body = suffix==='' ? liveTask : suffix==='/logs' ? {events:[],has_more:false} : suffix==='/agent-log-files' ? {files:[]} : {detail:'No fixture evidence'};
      return request.respond({status:['','/logs','/agent-log-files'].includes(suffix)?200:404,contentType:'application/json',body:JSON.stringify(body)});
    }
    if (url.pathname.endsWith('/assistant/chat')) return request.respond({status:200,contentType:'application/json',body:JSON.stringify({answer:'离线模拟取证回答：请核对任务证据。',sources:[],suggested_questions:[],used_fallback:false,model:'offline mock',scope:'task',task_id:fixture.task_id})});
    const response = fixture.responses[url.pathname];
    if (!response) missing.push(url.pathname);
    await request.respond({status:response?.status || 404,contentType:'application/json',body:JSON.stringify(response?.body || {detail:'No offline fixture'})});
  });
  const visit = async route => { await page.goto('https://attackpilot.test'+route,{waitUntil:'networkidle0'}); };
  const contains = text => page.waitForFunction(value=>document.body.innerText.includes(value),{},text);
  const clickText = async text => {
    const found = await page.evaluate(value=>{const item=[...document.querySelectorAll('button,a')].find(node=>node.textContent.trim()===value || node.getAttribute('aria-label')===value);item?.click();return !!item;},text);
    assert.ok(found, `Clickable text missing: ${text}`);
  };
  const checkWidth = async label => {
    const sizes = await page.evaluate(()=>{const root=document.querySelector('.attackpilot-root');return {window:innerWidth,document:document.documentElement.scrollWidth,moduleWidth:root.clientWidth,moduleScroll:root.scrollWidth};});
    assert.ok(sizes.document<=sizes.window+1 && sizes.moduleScroll<=sizes.moduleWidth+1, `${label}: horizontal page overflow ${JSON.stringify(sizes)}`);
  };
  const dismissContext = async () => {
    await page.evaluate(()=>document.querySelector('.ant-drawer-open .ant-drawer-close')?.click());
  };
  const clickLabel = async text => {
    const found=await page.evaluate(value=>{const el=[...document.querySelectorAll('label,.ant-tabs-tab')].find(el=>el.textContent.trim()===value);el?.click();return !!el;},text);
    assert.ok(found,`Label missing: ${text}`);
  };
  await page.setViewport({width:1440,height:1000});
  await visit('/attackpilot'); await contains('链上攻击复盘平台'); await checkWidth('desktop workbench');
  await page.screenshot({path:path.join(output,'review-desktop.png'),fullPage:true});
  await clickText('黑夜模式'); await page.waitForSelector('[data-appearance="dark"]');
  await page.screenshot({path:path.join(output,'review-dark.png'),fullPage:true});
  await page.reload({waitUntil:'networkidle0'}); await page.waitForSelector('[data-appearance="dark"]');
  await clickText('白天模式');
  await page.type('input[aria-label="第 1 笔交易哈希"]','bad-hash'); await contains('交易哈希格式不正确');
  await clickText('填入示例交易');
  await page.waitForSelector('.ant-modal .ant-select');
  await page.click('.ant-modal .ant-select');
  await page.type('.ant-modal .ant-select input', 'ApeCoin');
  await page.waitForSelector('.ant-select-item-option');
  await page.evaluate(()=>[...document.querySelectorAll('.ant-select-item-option')].find(el=>el.textContent.includes('ApeCoin'))?.click());
  await clickText('填入全部交易');
  await page.waitForFunction(()=>!document.querySelector('.ant-modal:not([style*="display: none"])'));
  await page.click('.hero-action-panel .ant-select');
  await page.waitForSelector('.ant-select-item-option');
  await page.evaluate(()=>[...document.querySelectorAll('.ant-select-item-option')].find(el=>el.textContent.includes('币安智能链'))?.click());
  await page.evaluate(()=>[...document.querySelectorAll('.workflow-module-box label')].find(el=>el.querySelector('strong')?.textContent==='补丁生成')?.click());
  await page.waitForFunction(()=>document.querySelectorAll('.workflow-module-box input:checked').length===3);
  await page.evaluate(()=>[...document.querySelectorAll('.workflow-module-box label')].find(el=>el.querySelector('strong')?.textContent==='补丁验证')?.click());
  await page.waitForFunction(()=>document.querySelectorAll('.workflow-module-box input:checked').length===5);
  const draft=await page.$eval('input[aria-label="第 1 笔交易哈希"]',el=>el.value);
  await clickText('快速攻击检测'); await contains('退出测试账号');
  await page.waitForFunction(value=>document.querySelector('input[aria-label="第 1 笔交易哈希"]')?.value===value,{},draft);
  await contains('币安智能链 BNB Chain');
  await clickText('快速攻击检测'); await contains('离线单笔审查成功');
  await clickText('+ 交易');
  await page.type('.tx-row-item:nth-child(2) input','0x'+'b'.repeat(64));
  await clickText('快速攻击检测'); await contains('离线批量检测成功');
  assert.ok(mutations.some(item=>item.path.endsWith('/tx-review')));
  assert.ok(mutations.some(item=>item.path.endsWith('/tx-detect')));
  assert.equal(JSON.parse(mutations.find(item=>item.path.endsWith('/tx-detect')).body).chain,'bnbchain');
  await clickText('任务库'); await contains('任务总数'); await page.waitForSelector('.ant-table-row');
  await checkWidth('desktop tasks'); await page.screenshot({path:path.join(output,'tasks-desktop.png'),fullPage:true});
  await visit('/attackpilot/tasks/'+fixture.task_id); await contains('未在当前环境重新验证'); await contains('结构化报告');
  await dismissContext(); await contains('中文译文 · 可切换原文核对');
  await contains('离线中文报告夹具');
  const typography=await page.evaluate(()=>({heading:getComputedStyle(document.querySelector('.markdown-content h1')).fontWeight,list:getComputedStyle(document.querySelector('.markdown-content ul')).listStyleType}));
  assert.ok(Number(typography.heading)>=600,'Report headings lost emphasis'); assert.equal(typography.list,'disc');
  await clickLabel('原文'); await contains('模型原始报告');
  await clickLabel('中文'); await contains('离线中文报告夹具');
  await clickText('智能体摘要'); await page.waitForSelector('.ap-detail-drawer .agent-row', {visible:true});
  await page.click('.ap-detail-drawer .agent-row'); await page.waitForSelector('.ap-detail-agent-filter');
  await page.waitForSelector('.ap-detail-drawer', {hidden:true});
  await clickText('显示全部智能体');
  await page.waitForFunction(()=>!document.querySelector('.ap-detail-agent-filter'));
  await page.click('.ap-report-appendix summary');
  await page.waitForFunction(()=>document.querySelector('.ap-report-appendix details')?.open);
  await checkWidth('expanded report evidence'); await page.click('.ap-report-appendix summary');
  await page.evaluate(()=>scrollTo(0,0));
  await checkWidth('desktop detail'); await page.screenshot({path:path.join(output,'detail-desktop.png'),fullPage:true});
  await clickText('访客'); await dismissContext(); await clickText('取证助手'); await contains('助手会基于当前交易');
  await page.type('.assistant-composer textarea','这份报告有哪些关键证据？'); await clickText('发送'); await contains('离线模拟取证回答');
  await page.screenshot({path:path.join(output,'assistant-desktop.png'),fullPage:true});
  await page.evaluate(id=>{history.pushState({},'', '/attackpilot/tasks/'+id);window.dispatchEvent(new PopStateEvent('popstate'));},liveId);
  await contains('验证已跳过'); await dismissContext();
  await visit('/attackpilot/knowledge'); await contains('漏洞'); await checkWidth('desktop knowledge');
  const nextLesson=await page.$eval('.knowledge-subject:nth-child(2) strong',node=>node.textContent);
  await page.click('.knowledge-subject:nth-child(2)');
  await page.waitForFunction(text=>document.querySelector('#knowledge-lesson-title')?.textContent===text,{},nextLesson);
  assert.equal(await page.$eval('.knowledge-section ol',node=>getComputedStyle(node).listStyleType),'decimal');
  await page.screenshot({path:path.join(output,'knowledge-desktop.png'),fullPage:true});
  await visit('/attackpilot/briefing'); await contains('证据驱动的链上攻击复盘平台'); await checkWidth('desktop briefing');
  await page.screenshot({path:path.join(output,'briefing-desktop.png'),fullPage:true});
  for (const [name,route] of [['review','/attackpilot'],['tasks','/attackpilot/tasks'],['detail','/attackpilot/tasks/'+fixture.task_id],['knowledge','/attackpilot/knowledge'],['briefing','/attackpilot/briefing']]) {
    await page.setViewport({width:390,height:844}); await visit(route);
    await page.waitForSelector('.ap-module-nav'); await dismissContext(); await checkWidth('mobile '+name);
    await page.screenshot({path:path.join(output,name+'-mobile.png'),fullPage:true});
  }
  await clickText('任务库'); await contains('任务总数');
  await page.goBack({waitUntil:'networkidle0'}); await contains('证据驱动的链上攻击复盘平台');
  useRecordedTranslation = true;
  await page.setViewport({width:1440,height:1000});
  await visit('/attackpilot/tasks/'+fixture.task_id); await dismissContext();
  await contains('中文译文 · 可切换原文核对');
  assert.equal(fixture.responses['/api/attackpilot/tasks/'+fixture.task_id+'/report-translation'].body.status,'ready');
  await page.screenshot({path:path.join(output,'recorded-chinese-report-desktop.png'),fullPage:true});
  await page.evaluate(()=>document.querySelector('.report-section-card:last-child')?.scrollIntoView());
  await page.screenshot({path:path.join(output,'recorded-chinese-report-text.png')});
  assert.deepEqual(errors, [], 'Unexpected browser errors');
  assert.deepEqual(missing, [], 'Unmocked API calls');
  assert.ok(mutations.every(item=>item.csrf==='1'), 'Mutation request lacks the shared CSRF header');
  await writeFile(path.join(output,'result.json'),JSON.stringify({passed:true,viewports:[1440,390],historicalTask:fixture.task_id,errors,mutations},null,2));
  console.log('AttackPilot offline browser smoke passed; artifacts: '+output);
} catch (error) {
  const pages=await browser.pages(); const failed=pages.at(-1);
  await writeFile(path.join(output,'failure.json'),JSON.stringify({error:String(error),errors,missing,mutations,text:await failed.evaluate(()=>document.body.innerText)},null,2));
  await failed.screenshot({path:path.join(output,'failure.png'),fullPage:true});
  throw error;
} finally { await browser.close(); }
