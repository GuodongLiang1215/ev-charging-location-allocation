"use strict";

const R_EARTH = 6371000;
const R2 = R_EARTH * R_EARTH;

function num(x, fb = 0){ const v = Number(x); return Number.isFinite(v) ? v : fb; }
function clamp01(x){ return Math.max(0, Math.min(1, x)); }
function randInt(n){ return Math.floor(Math.random() * n); }
function distSqFast(a, b){
  const dLat = b.latRad - a.latRad;
  const dLng = b.lngRad - a.lngRad;
  const cosAvg = (a.cosLat + b.cosLat) * 0.5;
  const x = dLng * cosAvg;
  return R2 * (x*x + dLat*dLat);
}
function distFast(a, b){ return Math.sqrt(distSqFast(a, b)); }

const KPI_DEFS = [
  { key:"cov",       higherIsBetter:true },
  { key:"wsMin",     higherIsBetter:true },
  { key:"wsAvg",     higherIsBetter:true },
  { key:"avgScore",  higherIsBetter:true },
  { key:"dex",       higherIsBetter:true },
  { key:"red",       higherIsBetter:true },
  { key:"eqCov",     higherIsBetter:true },
  { key:"eqDisp",    higherIsBetter:false },
  { key:"dwAvgDist", higherIsBetter:false },
  { key:"p90Access", higherIsBetter:false },
  { key:"maxAccess", higherIsBetter:false },
];

function pickBestFromMetrics(entriesArr){
  const scores = entriesArr.map(() => 0);
  const EPS = 1e-6;
  for(const kpi of KPI_DEFS){
    const vals = entriesArr.map(e => e.metrics ? e.metrics[kpi.key] : NaN);
    const finite = vals.filter(Number.isFinite);
    if(!finite.length) continue;
    const allEqual = finite.every(v => Math.abs(v - finite[0]) < EPS);
    if(allEqual) continue;
    let bestIdx = -1, bestVal = kpi.higherIsBetter ? -Infinity : Infinity;
    for(let i = 0; i < vals.length; i++){
      if(!Number.isFinite(vals[i])) continue;
      if(kpi.higherIsBetter ? (vals[i] > bestVal + EPS) : (vals[i] < bestVal - EPS)){
        bestVal = vals[i];
        bestIdx = i;
      }
    }
    if(bestIdx >= 0) scores[bestIdx]++;
  }
  const maxScore = Math.max(...scores);
  const winners = scores.reduce((acc, s, i) => s === maxScore ? acc.concat(i) : acc, []);
  const isTie = (maxScore === 0) || (winners.length > 1);
  const bestIdx = isTie ? (entriesArr.length - 1) : winners[0];
  return { bestIdx };
}

function equityNeed01FromE01(e01, eqDir){
  const v = clamp01(num(e01, 0.5));
  return (eqDir === "highNeedLow") ? (1 - v) : v;
}

function violatesSpread(listIdx, candidates, cfg){
  if(!cfg.spreadEnabled) return false;
  const minM = Math.max(0, num(cfg.minSpacingM, 700));
  if(minM <= 0) return false;
  for(let i = 0; i < listIdx.length; i++){
    const a = candidates[listIdx[i]];
    for(let j = i + 1; j < listIdx.length; j++){
      const b = candidates[listIdx[j]];
      if(distFast(a, b) < minM) return true;
    }
  }
  return false;
}

function repairSolution(solIdx, P, candidates, lockedIdx, cfg){
  const out = [];
  const used = new Set();
  for(const lk of lockedIdx){
    if(!Number.isInteger(lk) || lk < 0 || lk >= candidates.length || used.has(lk)) continue;
    out.push(lk); used.add(lk);
    if(out.length >= P) return out.slice(0, P);
  }
  for(const x of (solIdx || [])){
    if(!Number.isInteger(x) || x < 0 || x >= candidates.length || used.has(x)) continue;
    const t = out.concat([x]);
    if(violatesSpread(t, candidates, cfg)) continue;
    out.push(x); used.add(x);
    if(out.length >= P) break;
  }
  let guard = 0;
  while(out.length < P && guard++ < 50000){
    const c = randInt(candidates.length);
    if(used.has(c)) continue;
    const t = out.concat([c]);
    if(violatesSpread(t, candidates, cfg)) continue;
    out.push(c); used.add(c);
  }
  return out.slice(0, P);
}

function applyClusterCosts(selIdx, candidates, cfg){
  const minM = Math.max(1, num(cfg.minSpacingM, 700));
  const wc = num(cfg.wc, 0.25);
  const scores = [];
  for(const idx of selIdx){
    const c = candidates[idx];
    let bestSq = Infinity;
    for(const j of selIdx){
      if(j === idx) continue;
      const dSq = distSqFast(c, candidates[j]);
      if(dSq < bestSq) bestSq = dSq;
    }
    const bestD = Number.isFinite(bestSq) ? Math.sqrt(bestSq) : NaN;
    const costCluster01 = (selIdx.length <= 1 || !Number.isFinite(bestD)) ? 0 : clamp01(1 - (bestD / minM));
    const cost = clamp01(num(c.costBase, 0) + wc * costCluster01);
    scores.push(num(c.benefit, 0) - cost);
  }
  return scores;
}

function computePlanMetrics(selIdx, demand, cache, candidates, cfg){
  const thrSq = Math.pow(num(cfg.coverageThresholdDistM, 1000), 2);
  let totalW = 0, coveredW = 0;
  const afterCovW = new Map();
  for(const d of demand){
    const w = Math.max(0, num(d.demandRaw, 1));
    totalW += w;
    const exSq = Number.isFinite(d.distToExistingSq) ? d.distToExistingSq : Infinity;
    let bestNewSq = Infinity;
    for(const i of selIdx){
      const dsq = distSqFast(d, candidates[i]);
      if(dsq < bestNewSq) bestNewSq = dsq;
    }
    const bestSq = Math.min(exSq, bestNewSq);
    if(bestSq <= thrSq) coveredW += w;
    const code = String(d.lsoaCode || "");
    if(code && cache.codesSet.has(code)){
      if(!afterCovW.has(code)) afterCovW.set(code, 0);
      if(bestSq <= thrSq) afterCovW.set(code, afterCovW.get(code) + w);
    }
  }
  const covAfter01 = totalW > 0 ? coveredW / totalW : 0;
  let minImp = Infinity, avgImpSum = 0, cnt = 0;
  for(const code of cache.codes){
    const cur = cache.currentAgg[code];
    if(!cur || cur.totW <= 0) continue;
    const imp = (afterCovW.get(code) || 0) / cur.totW - cur.covCur01;
    minImp = Math.min(minImp, imp);
    avgImpSum += imp;
    cnt++;
  }
  if(!Number.isFinite(minImp)) minImp = 0;
  return { covAfter01, minImprove:minImp, avgImprove:cnt > 0 ? avgImpSum / cnt : 0 };
}

function computeEquityWeightedCoverage(selIdx, demand, candidates, cfg){
  if(!selIdx.length || !demand.length) return 0;
  const thrSq = Math.pow(num(cfg.coverageThresholdDistM, 1000), 2);
  let covW = 0, totW = 0;
  for(const d of demand){
    const dW = Math.max(0, num(d.demandRaw, 1));
    const eqW = (0.2 + 0.8 * equityNeed01FromE01(d.e01, cfg.eqDir));
    const w = dW * eqW;
    totW += w;
    const exSq = Number.isFinite(d.distToExistingSq) ? d.distToExistingSq : Infinity;
    let bestSq = Infinity;
    for(const i of selIdx){
      const dsq = distSqFast(d, candidates[i]);
      if(dsq < bestSq) bestSq = dsq;
    }
    if(Math.min(exSq, bestSq) <= thrSq) covW += w;
  }
  return totW > 0 ? covW / totW : 0;
}

function computeEquityDisparityQ5Q1(selIdx, demand, candidates, cfg){
  if(!selIdx.length || !demand.length) return NaN;
  const thrSq = Math.pow(num(cfg.coverageThresholdDistM, 1000), 2);
  const total = Array(6).fill(0), covered = Array(6).fill(0);
  for(const d of demand){
    const g = Math.max(1, Math.min(5, Math.floor(num(d.equityGroup, 3))));
    const w = Math.max(0, num(d.demandRaw, 1));
    total[g] += w;
    const exSq = Number.isFinite(d.distToExistingSq) ? d.distToExistingSq : Infinity;
    let bestSq = Infinity;
    for(const i of selIdx){
      const dsq = distSqFast(d, candidates[i]);
      if(dsq < bestSq) bestSq = dsq;
    }
    if(Math.min(exSq, bestSq) <= thrSq) covered[g] += w;
  }
  const mostDeprived = total[5] > 0 ? covered[5] / total[5] : NaN;
  const leastDeprived = total[1] > 0 ? covered[1] / total[1] : NaN;
  return (Number.isFinite(mostDeprived) && Number.isFinite(leastDeprived)) ? (leastDeprived - mostDeprived) : NaN;
}

function computeDemandWeightedAvgDist(selIdx, demand, candidates){
  if(!selIdx.length || !demand.length) return NaN;
  let totalW = 0, distWSum = 0;
  for(const d of demand){
    const w = Math.max(0, num(d.demandRaw, 1));
    totalW += w;
    const exSq = Number.isFinite(d.distToExistingSq) ? d.distToExistingSq : Infinity;
    let bestSq = exSq;
    for(const i of selIdx){
      const dsq = distSqFast(d, candidates[i]);
      if(dsq < bestSq) bestSq = dsq;
    }
    distWSum += w * Math.sqrt(bestSq);
  }
  return totalW > 0 ? distWSum / totalW : NaN;
}

function computeMaxAccessDist(selIdx, demand, candidates){
  if(!selIdx.length || !demand.length) return NaN;
  let maxDist = 0;
  for(const d of demand){
    const exSq = Number.isFinite(d.distToExistingSq) ? d.distToExistingSq : Infinity;
    let bestSq = exSq;
    for(const i of selIdx){
      const dsq = distSqFast(d, candidates[i]);
      if(dsq < bestSq) bestSq = dsq;
    }
    const dist = Math.sqrt(bestSq);
    if(dist > maxDist) maxDist = dist;
  }
  return maxDist;
}

function computeP90AccessDist(selIdx, demand, candidates){
  if(!selIdx.length || !demand.length) return NaN;
  const rows = [];
  let totalW = 0;
  for(const d of demand){
    const exSq = Number.isFinite(d.distToExistingSq) ? d.distToExistingSq : Infinity;
    let bestSq = exSq;
    for(const i of selIdx){
      const dsq = distSqFast(d, candidates[i]);
      if(dsq < bestSq) bestSq = dsq;
    }
    const w = Math.max(0, num(d.demandRaw, 1));
    const dist = Math.sqrt(bestSq);
    if(Number.isFinite(dist) && w > 0){
      rows.push({dist, w});
      totalW += w;
    }
  }
  if(!rows.length || totalW <= 0) return NaN;
  rows.sort((a,b) => a.dist - b.dist);
  const target = 0.9 * totalW;
  let acc = 0;
  for(const r of rows){
    acc += r.w;
    if(acc >= target) return r.dist;
  }
  return rows[rows.length - 1].dist;
}

function redundancyAvgNearestSelected(selIdx, candidates){
  if(selIdx.length < 2) return NaN;
  const ds = [];
  for(const ia of selIdx){
    let b2 = Infinity;
    for(const ib of selIdx){
      if(ia === ib) continue;
      const dSq = distSqFast(candidates[ia], candidates[ib]);
      if(dSq < b2) b2 = dSq;
    }
    if(Number.isFinite(b2)) ds.push(Math.sqrt(b2));
  }
  return ds.length ? ds.reduce((a,b) => a+b, 0) / ds.length : NaN;
}

function avgDistToExisting(selIdx, candidates){
  const arr = selIdx
    .map(i => candidates[i].distToExistingSq)
    .filter(Number.isFinite)
    .map(Math.sqrt);
  return arr.length ? arr.reduce((a,b) => a+b, 0) / arr.length : NaN;
}

function computeFullMetrics(selIdx, demand, cache, candidates, cfg){
  if(!selIdx || !selIdx.length) return null;
  const m = computePlanMetrics(selIdx, demand, cache, candidates, cfg);
  const scores = applyClusterCosts(selIdx, candidates, cfg);
  const avgScore = scores.length ? scores.reduce((a,b)=>a+b,0)/scores.length : NaN;
  return {
    cov: m.covAfter01,
    wsMin: m.minImprove,
    wsAvg: m.avgImprove,
    avgScore,
    dex: avgDistToExisting(selIdx, candidates),
    red: redundancyAvgNearestSelected(selIdx, candidates),
    eqCov: computeEquityWeightedCoverage(selIdx, demand, candidates, cfg),
    eqDisp: computeEquityDisparityQ5Q1(selIdx, demand, candidates, cfg),
    dwAvgDist: computeDemandWeightedAvgDist(selIdx, demand, candidates),
    p90Access: computeP90AccessDist(selIdx, demand, candidates),
    maxAccess: computeMaxAccessDist(selIdx, demand, candidates),
  };
}

function evalGA(solIdx, demand, cache, candidates, cfg, mode){
  const m = computePlanMetrics(solIdx, demand, cache, candidates, cfg);
  const scores = applyClusterCosts(solIdx, candidates, cfg);
  const meanScore = scores.length ? scores.reduce((a,b)=>a+b,0)/scores.length : 0;
  if(mode === "score") return {solIdx, keys:[meanScore]};
  if(mode === "covScore") return {solIdx, keys:[m.covAfter01, meanScore]};
  return {solIdx, keys:[m.covAfter01, m.minImprove, meanScore]};
}

function lexIsBetter(a, b){
  const eps = [1e-4, 1e-4, 1e-4];
  const L = Math.max(a.keys.length, b.keys.length);
  for(let i = 0; i < L; i++){
    const da = (a.keys[i] ?? -Infinity), db = (b.keys[i] ?? -Infinity);
    if(Math.abs(da - db) > (eps[i] ?? 1e-6)) return da > db;
  }
  return false;
}
function lexSortDesc(a,b){ if(lexIsBetter(a,b)) return -1; if(lexIsBetter(b,a)) return 1; return 0; }

function makeRandomSolution(P, candidates, lockedIdx, cfg){
  return repairSolution([], P, candidates, lockedIdx, cfg);
}

function crossover(a, b, P, candidates, lockedIdx, cfg){
  const pool = [];
  const seen = new Set();
  for(const x of a){ if(!seen.has(x)){ pool.push(x); seen.add(x); } }
  for(const x of b){ if(!seen.has(x)){ pool.push(x); seen.add(x); } }
  for(let i = pool.length - 1; i > 0; i--){
    const j = randInt(i + 1);
    const t = pool[i]; pool[i] = pool[j]; pool[j] = t;
  }
  return repairSolution(pool, P, candidates, lockedIdx, cfg);
}

function mutate(solIdx, P, candidates, lockedIdx, cfg){
  const out = (solIdx || []).slice();
  for(let i = 0; i < out.length; i++){
    if(Math.random() > cfg.gaMut) continue;
    let guard = 0;
    while(guard++ < 2000){
      const c = randInt(candidates.length);
      if(out.includes(c)) continue;
      const trial = out.slice();
      trial[i] = c;
      const rep = repairSolution(trial, P, candidates, lockedIdx, cfg);
      if(rep.length === P) return rep;
    }
  }
  return repairSolution(out, P, candidates, lockedIdx, cfg);
}

function buildSeededPopulation(P, popSize, seedIdx, candidates, lockedIdx, cfg){
  const seedCount = Math.max(0, Math.floor(popSize * num(cfg.gaSeedPct, 0.15)));
  const pop = [];
  if(seedCount > 0 && seedIdx && seedIdx.length){
    const base = repairSolution(seedIdx, P, candidates, lockedIdx, cfg);
    pop.push(base);
    const baseMut = Math.min(0.8, Math.max(0.3, num(cfg.gaMut, 0.45) + 0.1));
    for(let i = 1; i < seedCount; i++){
      const mutCfg = Object.assign({}, cfg, {gaMut: baseMut});
      pop.push(mutate(base, P, candidates, lockedIdx, mutCfg));
    }
  }
  while(pop.length < popSize) pop.push(makeRandomSolution(P, candidates, lockedIdx, cfg));
  return pop;
}

function runGA(P, seedIdx, demand, cache, candidates, lockedIdx, cfg, mode){
  let popSize = Math.max(10, Math.floor(num(cfg.gaPop, 120)));
  let gens = Math.max(10, Math.floor(num(cfg.gaGen, 240)));
  let evalSample = Math.max(10, Math.floor(num(cfg.gaEvalSample, 80)));

  const candN = candidates.length;
  if(P > 30 || candN > 350){
    popSize = Math.max(10, Math.min(popSize, 24));
    gens = Math.max(20, Math.min(gens, 90));
    evalSample = Math.max(10, Math.min(evalSample, 36, popSize));
  }
  if(P > 45 || candN > 500){
    popSize = Math.max(10, Math.min(popSize, 18));
    gens = Math.max(15, Math.min(gens, 70));
    evalSample = Math.max(10, Math.min(evalSample, 28, popSize));
  }
  evalSample = Math.max(10, Math.min(popSize, evalSample));
  const eliteRate = Math.max(0, Math.min(0.5, num(cfg.gaElite, 0.08)));

  let pop = buildSeededPopulation(P, popSize, seedIdx, candidates, lockedIdx, cfg);
  let bestEval = evalGA(pop[0], demand, cache, candidates, cfg, mode);
  let stale = 0;
  const patience = Math.max(10, Math.min(30, Math.floor(gens * 0.25)));

  for(let g = 0; g < gens; g++){
    const subLen = Math.min(evalSample, pop.length);
    const subset = pop.length <= subLen ? pop : (() => {
      const o = pop.slice(0, Math.min(10, pop.length));
      while(o.length < subLen) o.push(pop[randInt(pop.length)]);
      return o;
    })();
    const scored = subset.map(sol => evalGA(sol, demand, cache, candidates, cfg, mode)).sort(lexSortDesc);
    if(scored.length && lexIsBetter(scored[0], bestEval)){ bestEval = {solIdx:scored[0].solIdx.slice(), keys:scored[0].keys.slice()}; stale = 0; }
    else stale++;

    const eliteCount = Math.max(1, Math.floor(eliteRate * popSize));
    const elites = scored.slice(0, Math.min(eliteCount, scored.length)).map(x => x.solIdx);
    const pickOne = () => {
      let best = null;
      for(let i = 0; i < 4; i++){
        const c = scored[randInt(scored.length)];
        if(!best || lexIsBetter(c, best)) best = c;
      }
      return best.solIdx;
    };
    const next = elites.slice();
    while(next.length < popSize){
      const p1 = scored.length ? pickOne() : pop[randInt(pop.length)];
      const p2 = scored.length ? pickOne() : pop[randInt(pop.length)];
      next.push(mutate(crossover(p1, p2, P, candidates, lockedIdx, cfg), P, candidates, lockedIdx, cfg));
    }
    pop = next;
    if(stale >= patience) break;
  }
  return repairSolution(bestEval.solIdx, P, candidates, lockedIdx, cfg);
}

function computeMedian(arr){
  if(!arr.length) return NaN;
  const sorted = arr.slice().sort((a,b)=>a-b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid-1] + sorted[mid]) / 2 : sorted[mid];
}
function computeStd(arr){
  if(arr.length < 2) return 0;
  const mean = arr.reduce((a,b)=>a+b,0) / arr.length;
  const sqDiffs = arr.map(v => (v - mean) * (v - mean));
  return Math.sqrt(sqDiffs.reduce((a,b)=>a+b,0) / (arr.length - 1));
}

function runGAMultiple(payload){
  const P = payload.P;
  const mode = payload.mode;
  const N = Math.max(1, Math.floor(payload.N || 1));
  const candidates = payload.candidates || [];
  const demand = payload.demand || [];
  const lockedIdx = payload.lockedIdx || [];
  const seedIdx = payload.seedIdx || [];
  const cfg = payload.cfg || {};
  const cache = {
    codes: (payload.cache && payload.cache.codes) ? payload.cache.codes.slice() : [],
    currentAgg: (payload.cache && payload.cache.currentAgg) ? payload.cache.currentAgg : {},
    codesSet: new Set((payload.cache && payload.cache.codes) ? payload.cache.codes : [])
  };

  const allSolIdx = [];
  const allMetrics = [];
  for(let r = 0; r < N; r++){
    const solIdx = runGA(P, seedIdx, demand, cache, candidates, lockedIdx, cfg, mode);
    const m = computeFullMetrics(solIdx, demand, cache, candidates, cfg);
    allSolIdx.push(solIdx);
    allMetrics.push(m);
  }

  const entries = allMetrics.map((m,i) => ({label:String(i), metrics:m}));
  const bestIdx = pickBestFromMetrics(entries).bestIdx;
  const medianMetrics = {};
  const stdMetrics = {};
  for(const kpi of KPI_DEFS){
    const vals = allMetrics.map(m => m ? m[kpi.key] : NaN).filter(Number.isFinite);
    medianMetrics[kpi.key] = computeMedian(vals);
    stdMetrics[kpi.key] = computeStd(vals);
  }

  return {
    bestSolIdx: allSolIdx[bestIdx] || [],
    bestMetrics: allMetrics[bestIdx] || null,
    allMetrics,
    medianMetrics,
    stdMetrics,
    N
  };
}

self.onmessage = function(ev){
  const d = ev && ev.data ? ev.data : {};
  const id = d.id;
  try{
    if(d.type !== "runGAMultiple") throw new Error("Unsupported worker request");
    const result = runGAMultiple(d.payload || {});
    self.postMessage({id, ok:true, result});
  }catch(err){
    self.postMessage({id, ok:false, error:(err && err.message) ? err.message : String(err)});
  }
};
