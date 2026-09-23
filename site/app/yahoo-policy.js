'use strict';
// Port of yahoo_opening_search.choose and draft_legality.can_complete.
// No projections, outcomes, injuries, or streaming scores enter this ranking.
const YahooPolicy=(()=>{
  const identity='yahoo10-rbrb-qb-wr-v1';
  const sequence=Object.freeze(['RB','RB','QB','WR']);
  const starters=Object.freeze({QB:1,RB:2,WR:2,TE:1,K:1,DEF:1});
  const caps=Object.freeze({QB:4,RB:6,WR:8,TE:4,K:4,DEF:4});
  const positions=Object.keys(caps),flex=['RB','WR','TE'];
  const rosterSize=15,seed=906201;
  let market=null,ties=new Map(),prepared=new Map();
  const emptyPrice=Object.freeze({has_real_adp:false,observed_adp:null});
  function clear(){market=null;ties=new Map();prepared=new Map();}
  async function prepare(players,snapshot,cryptoApi=globalThis.crypto,now=Date.now()){
    clear();
    if(snapshot?.season!==2026||snapshot.scoring!=='half_ppr'||snapshot.teams!==12||
       !snapshot.source||!snapshot.source_url||!snapshot.source_sha256||
       !/^2026-\d{2}-\d{2}$/.test(snapshot.snapshot_date)||!Number.isFinite(Date.parse(snapshot.snapshot_date))||
       Date.parse(snapshot.snapshot_date)>now||!snapshot.players||Array.isArray(snapshot.players))throw Error('Invalid Yahoo half-PPR market');
    const ids=new Map();
    for(const p of players){
      if(typeof p.player_id!=='string'||!p.player_id||ids.has(p.player_id)||!positions.includes(p.position))throw Error('Invalid Yahoo player pool');
      ids.set(p.player_id,p.position);
    }
    const prices={};
    for(const [id,p] of Object.entries(snapshot.players)){
      if(p.has_real_adp!==true||!Number.isFinite(p.observed_adp)||p.observed_adp<=0||
         !p.adp_source||p.adp_snapshot_date!==snapshot.snapshot_date||!positions.includes(p.position)||
         (ids.has(id)&&ids.get(id)!==p.position))throw Error('Invalid observed Yahoo market row');
      prices[id]=Object.freeze({...p});
    }
    if(!Object.keys(prices).length)throw Error('Empty Yahoo market');
    const entries=await Promise.all(players.map(async p=>{
      const hash=await cryptoApi.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify([seed,p.player_id])));
      return [p.player_id,Array.from(new Uint8Array(hash),x=>x.toString(16).padStart(2,'0')).join('')];
    }));
    ties=new Map(entries);prepared=ids;
    market=Object.freeze({...snapshot,players:Object.freeze(prices)});
  }
  function price(p){return market?.players[p.player_id]||emptyPrice;}
  function compare(a,b){
    const x=price(a),y=price(b);
    return Number(!x.has_real_adp)-Number(!y.has_real_adp)||
      (x.has_real_adp&&y.has_real_adp?x.observed_adp-y.observed_adp:0)||
      (ties.get(a.player_id)<ties.get(b.player_id)?-1:ties.get(a.player_id)>ties.get(b.player_id)?1:0)||
      (a.player_id<b.player_id?-1:a.player_id>b.player_id?1:0);
  }
  function counts(players){const c={QB:0,RB:0,WR:0,TE:0,K:0,DEF:0};for(const p of players)c[p.position]++;return c;}
  function canComplete(c,supply,size){
    if(size>rosterSize||positions.some(p=>!Number.isInteger(c[p])||c[p]<0||c[p]>caps[p]))return false;
    const usable={},needs={};
    for(const p of positions){usable[p]=Math.min(supply[p],caps[p]-c[p]);needs[p]=Math.max(0,starters[p]-c[p]);}
    const flexNeed=Math.max(0,1-flex.reduce((n,p)=>n+Math.max(0,c[p]-starters[p]),0));
    const spaces=rosterSize-size;
    return Object.values(needs).reduce((a,b)=>a+b,0)+flexNeed<=spaces&&
      positions.every(p=>usable[p]>=needs[p])&&
      flex.reduce((n,p)=>n+Math.max(0,usable[p]-needs[p]),0)>=flexNeed&&
      Object.values(usable).reduce((a,b)=>a+b,0)>=spaces;
  }
  function legal(players,mine,taken=[]){
    const byId=new Map(players.map(p=>[p.player_id,p])),used=new Set([...mine,...taken]);
    if(byId.size!==players.length||used.size!==mine.length+taken.length||mine.length>=rosterSize||
       players.some(p=>!positions.includes(p.position))||[...used].some(id=>!byId.has(id)))return [];
    const c=counts(mine.map(id=>byId.get(id))),pool=players.filter(p=>!used.has(p.player_id)),supply=counts(pool);
    const allowed=new Set(positions.filter(pos=>supply[pos]>0&&canComplete({...c,[pos]:c[pos]+1},{...supply,[pos]:supply[pos]-1},mine.length+1)));
    return pool.filter(p=>allowed.has(p.position));
  }
  function rank(players,mine,taken=[]){
    if(!market||players.some(p=>prepared.get(p.player_id)!==p.position))return [];
    const pool=legal(players,mine,taken).sort(compare);if(!pool.length)return [];
    const base=pool[0],target=sequence[mine.length],leader=price(base);
    const preferred=target&&leader.has_real_adp&&!['K','DEF'].includes(base.position)?
      pool.filter(p=>p.position===target&&price(p).has_real_adp&&price(p).observed_adp<=leader.observed_adp+12):[];
    const nextPreferred=target?pool.find(p=>p.position===target&&price(p).has_real_adp):null;
    let reason='Opening complete · best legal half-PPR ADP · room preserved for remaining starters';
    if(target){
      reason=preferred.length?`Your pick ${mine.length+1}: prefer ${target} · within 12 ADP spots`:
        ['K','DEF'].includes(base.position)?`Your pick ${mine.length+1}: ${base.position} leads legal ADP · opening preference does not override specialists`:
        nextPreferred&&leader.has_real_adp?`Your pick ${mine.length+1}: prefer ${target}, but ADP ${price(nextPreferred).observed_adp.toFixed(1)} exceeds ${ (leader.observed_adp+12).toFixed(1)} limit · take best legal ADP`:
        `Your pick ${mine.length+1}: priced ${target} preference unavailable · take best legal ADP`;
    }
    // Alternatives are for this pick, not a promise about the following rounds.
    const ordered=preferred.length?[...preferred,...pool.filter(p=>!preferred.includes(p))]:pool;
    return ordered.slice(0,5).map((p,i)=>({...p,yahoo_policy:true,policy_identity:identity,
      policy_adp:price(p).observed_adp,
      pick_reason:(i===0?reason:preferred.includes(p)?`Same-pick ${target} alternative · within 12 ADP spots`:'Other legal alternative · half-PPR ADP')+
        (price(p).has_real_adp?'':' · unpriced, stable identity tie-break')}));
  }
  return {identity,sequence,starters,caps,rosterSize,seed,prepare,clear,price,counts,canComplete,legal,rank,
    ready:()=>!!market,snapshot:()=>market?.snapshot_date};
})();
if(typeof module!=='undefined')module.exports=YahooPolicy;
if(typeof window!=='undefined')window.OverADPYahooPolicy=YahooPolicy;
