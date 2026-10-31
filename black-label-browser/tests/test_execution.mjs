import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readFile, writeFile, stat, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {loadExecutionState,saveExecutionState,actionReceipt,clickAndVerify} from '../server/execution.mjs';

test('private receipts are persisted before input and a restart never repeats started actions', async()=>{
  const directory=await mkdtemp(path.join(tmpdir(),'browser-receipt-test-'));
  try {
    const execution=await loadExecutionState(directory), state={directory,execution,cooldowns:execution.cooldowns};
    const page={url:()=> 'https://example.test/form',frames:()=>[],waitForTimeout:async()=>{}};
    let calls=0;
    const input={receipt_id:'one',expect:{condition:'text',text:'Expected outcome'},timeout_ms:1};
    const result=await clickAndVerify(state,page,input,async()=>async()=>{
      calls++;
      const disk=JSON.parse(await readFile(path.join(directory,'execution-state.json'),'utf8'));
      assert.equal(disk.receipts.one.state,'started');
    });
    assert.equal(result.receipt.state,'unconfirmed');assert.equal(calls,1);
    const disk=JSON.parse(await readFile(path.join(directory,'execution-state.json'),'utf8'));
    disk.receipts.one.state='started';await writeFile(path.join(directory,'execution-state.json'),JSON.stringify(disk));
    const resumed=await loadExecutionState(directory);
    const replay=await clickAndVerify({...state,execution:resumed,cooldowns:resumed.cooldowns},page,input,async()=>{throw Error('must not execute');});
    assert.equal(replay.action_attempted,false);assert.equal(replay.receipt.state,'started');
    assert.equal(actionReceipt(state,'toString'),null);
    await assert.rejects(clickAndVerify(state,page,{...input,expect:{condition:'text',text:'Different outcome'}},async()=>{}),/RECEIPT_CONFLICT/);
    assert.equal((await stat(path.join(directory,'execution-state.json'))).mode & 0o777,0o600);
    const saved=await readFile(path.join(directory,'execution-state.json'),'utf8');
    assert.ok(!saved.includes('Expected outcome'));assert.ok(!saved.includes('/form'));
  } finally { await rm(directory,{recursive:true,force:true}); }
});

test('expired cooldowns are removed and corrupted records fail closed',async()=>{
  const directory=await mkdtemp(path.join(tmpdir(),'browser-cooldown-test-'));
  try {
    const execution=await loadExecutionState(directory),state={directory,execution,cooldowns:execution.cooldowns};
    state.cooldowns.set('https://expired.test',{until:1,status:429,source:'server_retry_after'});
    state.cooldowns.set('https://active.test',{until:Date.now()+60000,status:429,source:'server_retry_after'});
    await saveExecutionState(state);
    const loaded=await loadExecutionState(directory);
    assert.equal(loaded.cooldowns.size,1);assert.ok(loaded.cooldowns.has('https://active.test'));
    await writeFile(path.join(directory,'execution-state.json'),'{}');
    await assert.rejects(loadExecutionState(directory),/EXECUTION_STATE_INVALID/);
  } finally { await rm(directory,{recursive:true,force:true}); }
});
