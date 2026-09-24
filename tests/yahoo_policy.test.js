const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const crypto=require('node:crypto'),policy=require('../site/app/yahoo-policy');
const html=fs.readFileSync(__dirname+'/../site/app/index.html','utf8');
const players=Array.from({length:360},(_,i)=>({player_id:String(i),player_name:'Player '+i,position:['WR','RB','QB','TE','K','DEF'][i%6],adp:200,projected_points:999-i}));
const snapshot=()=>({season:2026,scoring:'half_ppr',teams:12,source:'fixture',source_url:'https://example.test/adp',source_sha256:'fixture',snapshot_date:'2026-09-05',players:Object.fromEntries(players.map((p,i)=>[p.player_id,{position:p.position,has_real_adp:true,observed_adp:i+1,adp_source:'fixture',adp_snapshot_date:'2026-09-05'}]))});
const prepare=s=>policy.prepare(players,s||snapshot(),crypto.webcrypto,Date.parse('2026-09-07'));
function control(a,b){const x=policy.price(a),y=policy.price(b);return Number(!x.has_real_adp)-Number(!y.has_real_adp)||(x.has_real_adp?x.observed_adp-y.observed_adp:0)||crypto.createHash('sha256').update(JSON.stringify([policy.seed,a.player_id])).digest('hex').localeCompare(crypto.createHash('sha256').update(JSON.stringify([policy.seed,b.player_id])).digest('hex'));}
test('all ten complete snake slots remain legal through 150 picks',async()=>{
 await prepare();
 for(let slot=0;slot<10;slot++){
  const room=Array.from({length:10},()=>[]);
  for(let pick=0;pick<150;pick++){
   const seat=Math.floor(pick/10)%2?9-pick%10:pick%10,own=room[seat],taken=room.flatMap((r,i)=>i===seat?[]:r);
   const recs=seat===slot?policy.rank(players,own,taken):policy.legal(players,own,taken).sort(control);
   assert(recs.length,`slot ${slot+1} pick ${pick+1}`);own.push(recs[0].player_id);
  }
  for(const r of room){assert.equal(r.length,15);assert(policy.canComplete(policy.counts(players.filter(p=>r.includes(p.player_id))),{QB:0,RB:0,WR:0,TE:0,K:0,DEF:0},15));}
  assert.equal(new Set(room.flat()).size,150);assert.equal(policy.rank(players,room[slot]).length,0);
 }
});
test('four OWN picks prefer RB RB QB WR; WR is not TE; alternatives same pick',async()=>{
 await prepare();const mine=[];
 for(const pos of ['RB','RB','QB','WR']){const r=policy.rank(players,mine);assert.equal(r[0].position,pos);assert(r[0].pick_reason.includes('within 12'));const firstOther=r.findIndex(p=>p.position!==pos);if(firstOther>=0)assert(r.slice(firstOther).every(p=>p.position!==pos));mine.push(r[0].player_id);}
 assert(policy.rank(players,mine)[0].pick_reason.startsWith('Opening complete'));
 const s=snapshot();s.players['3'].observed_adp=.5;await prepare(s);
 assert.equal(policy.rank(players,['1','7','2'])[0].position,'WR');
});
test('inclusive reach limit and explicit fallback preserve first choice',async()=>{
 for(const [price,expected] of [[13,'1'],[13.001,'0']]){
  const s=snapshot();for(const p of players.filter(p=>p.position==='RB'))s.players[p.player_id].observed_adp=300;
  s.players['1'].observed_adp=price;await prepare(s);const r=policy.rank(players,[]);assert.equal(r[0].player_id,expected);
  assert(r[0].pick_reason.includes(expected==='1'?'within 12':'exceeds'));
 }
 const s=snapshot();s.players['4'].observed_adp=.5;await prepare(s);assert.equal(policy.rank(players,[])[0].position,'K');
});
test('observed 200 stays real; no-price sorts last; projections/status irrelevant',async()=>{
 const s=snapshot();s.players={'0':{...s.players['0'],observed_adp:200}};await prepare(s);
 assert.equal(policy.rank(players,[])[0].player_id,'0');assert.equal(policy.price(players[1]).observed_adp,null);
 const a=policy.rank(players,[]).map(p=>p.player_id),changed=players.map(p=>({...p,projected_points:1e9,adp:.01,stream_score:1e9,injury_status:'Out'}));
 assert.deepEqual(policy.rank(changed,[]).map(p=>p.player_id),a);
 s.players['0'].observed_adp=1;assert.equal(policy.price(players[0]).observed_adp,200,'snapshot is copied');
});
test('position caps and late completion guard; no Andre quotas or forced starter-first rule',async()=>{
 await prepare();const sixRB=['1','7','13','19','25','31'];assert(policy.legal(players,sixRB).every(p=>p.position!=='RB'));
 const mine=['1','7','13','0','6','12','2','8','14','20','3','9','15']; // 13 picks; K and DEF still empty
 const legal=policy.legal(players,mine);assert(legal.length);assert(legal.every(p=>['K','DEF'].includes(p.position)));
 assert(policy.legal(players,['1','7']).some(p=>p.position==='RB'),'depth is permitted before all starters');
 assert(policy.legal(players,['3','9','15']).some(p=>p.position==='WR'),'TE does not fill WR starters');
});
test('invalid picks, empty supply and invalid market fail closed',async()=>{
 await prepare();for(const own of [['missing'],['0','0'],['2','8','14','20','26']])assert.equal(policy.rank(players,own).length,0);
 assert.equal(policy.rank(players,['0'],['0']).length,0);assert.equal(policy.rank(players,[],['missing']).length,0);
 assert.equal(policy.rank(players,[],players.filter(p=>p.position==='K').map(p=>p.player_id)).length,0);
 for(const change of [{season:2025},{scoring:'standard'},{teams:10},{snapshot_date:'2027-09-05'},{players:{} }]){await assert.rejects(prepare({...snapshot(),...change}));assert.equal(policy.ready(),false);}
 const s=snapshot();s.players['0'].has_real_adp=false;await assert.rejects(prepare(s));assert.equal(policy.rank(players,[]).length,0);
});
test('production sidecar has real provenance; no board-placeholder inference; scripts parse',()=>{
 const s=JSON.parse(fs.readFileSync(__dirname+'/../site/app/data/yahoo-market.json'));
 assert.equal(s.scoring,'half_ppr');assert.equal(s.teams,12);assert.equal(s.target_format_teams,10);assert.equal(s.matched_rows,s.source_rows);assert(s.matched_rows>=180);
 for(const p of Object.values(s.players)){assert.equal(p.has_real_adp,true);assert(Number.isFinite(p.observed_adp)&&p.observed_adp>0);assert.equal(p.adp_snapshot_date,s.snapshot_date);assert(p.adp_source);}
 for(const m of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))if(!m[0].includes('application/ld+json'))new vm.Script(m[1]);
 assert(html.includes('10-team H2H · Half PPR'));assert(html.includes("s.leaguePreset==='yahoo10'"));
});
test('app uses Yahoo ranking, not study ranking, and renders its evidence label',async()=>{
 await prepare();const element={innerHTML:'',hidden:false,classList:{remove(){},add(){}}};
 let rendered;
 const c=vm.createContext({rosterConfig:{league_preset:'yahoo10',num_teams:10,draft_slot:7,roster_slots:{qb:1,rb:2,wr:2,te:1,flex:1,k:1,defense:1,bench:6},bench_size:6},myTeamIds:[],opponentIds:[],allPlayers:players,playerMap:Object.fromEntries(players.map(p=>[p.player_id,p])),OverADPYahooPolicy:policy,document:{getElementById:()=>element},updateLiveValueVsAdp(){},getStudyRecommendations(){throw Error('Wrong policy');},renderRecommendations(r){rendered=r;}});
 for(const name of ['isYahooLeague','getRosterPlan','getPositionCounts','mandatoryRosterNeeds','formatMandatoryNeeds','getRosterDraftConstraint','getRecommendations','yahooPresetHeader']){
  const m=html.match(new RegExp('^function '+name+'\\([^\\n]*\\)\\{[^\\n]*\\}$|^function '+name+'\\([^\\n]*\\)\\{[\\s\\S]*?^\\}','m'));assert(m,name);vm.runInContext(m[0],c);
 }
 c.getRecommendations();assert.equal(rendered[0].policy_identity,policy.identity);assert.equal(c.getRosterPlan().numTeams,10);assert(c.getRosterDraftConstraint('RB').allowed);
 const header=c.yahooPresetHeader({pickNum:7},c.getRosterPlan(),c.mandatoryRosterNeeds(c.getPositionCounts([])));
 assert(header.includes('10-TEAM H2H'));assert(header.includes('Prefer RB now'));assert(header.includes('FFC 12-team'));assert(!header.includes('ARCHIVED STUDY'));
});
