import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const lab='G:/AI/WindowsDeploy/apps/strait';
const out='G:/AI/Runs/gullmate-next-20261106/vessel-dispatch';
const importNative=n=>import(pathToFileURL(resolve(lab,'server',n+'.ts')).href);
const hash=x=>createHash('sha256').update(x).digest('hex');
if(process.argv[2]==='existing'){
 process.chdir(lab);
 const active=JSON.parse(readFileSync('reports/core-operations-active.json'));
 const bytes=readFileSync(active.active.reportPath);
 assert.equal(hash(bytes),active.active.sha256);
 const report=JSON.parse(bytes);
 const {loadGroupedCoreDataset}=await importNative('coreOperationsGroupedDataset');
 const {evaluateDeployedCore}=await importNative('coreOperationsFittedRl');
 const {CORE_OPERATIONS_EVALUATION_SCENARIOS,evaluateCorePolicy}=await importNative('coreOperationsRlEngine');
 const dataset=await loadGroupedCoreDataset();
 assert.equal(dataset.fingerprint,active.active.datasetFingerprint);
 const champion=report.training.champion;
 const rows=CORE_OPERATIONS_EVALUATION_SCENARIOS.map((scenario,i)=>{
  const result=evaluateDeployedCore(champion.seedPolicies,dataset.testRecords,scenario);
  const reference=evaluateCorePolicy({kind:'standard-operating-procedure'},dataset.testRecords,scenario);
  assert.deepEqual(result,champion.finalTest.reinforcementLearning[i]);
  assert.deepEqual(reference,champion.finalTest.standardOperatingProcedure[i]);
  return {scenario,result,reference};
 });
 mkdirSync(out,{recursive:true});
 writeFileSync(resolve(out,'native-champion.json'),JSON.stringify({weightReportSha:active.active.sha256,
  data:dataset.fingerprint,models:champion.seedPolicies.length,tests:dataset.testRecords.length,rows},null,2));
 console.log('Exact native aggregate policy and baseline replay',rows.length,'scenarios;',dataset.testRecords.length,'test records each');
}else{
 const {readTrial,planTrial,reviewExternalPlan}=await importNative('shanghaiLabV1');
 const {createInterface}=await import('node:readline');
 for await(const line of createInterface({input:process.stdin,crlfDelay:Infinity})){
  try{
   const req=JSON.parse(line),snapshot=JSON.stringify(req.case);
   const trial=readTrial({snapshot_json:snapshot,snapshot_transport_sha256:hash(snapshot)});
   let plan=req.plan??planTrial(trial);
   const text=JSON.stringify(plan);
   const review=reviewExternalPlan(trial,{plan_json:text,plan_transport_sha256:hash(text)});
   console.log(JSON.stringify({plan,review}));
  }catch(e){console.log(JSON.stringify({error:String(e.message)}))}
 }
}
