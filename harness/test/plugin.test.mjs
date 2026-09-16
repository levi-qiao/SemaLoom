import test from 'node:test';
import assert from 'node:assert/strict';
import { createSemanticPlugin } from '../semantic-plugin.mjs';

test('pi preflight blocks unknown tools, limits calls, and terminates only accepted evidence', async () => {
  let invoked = 0;
  const plugin = createSemanticPlugin({catalog:[{name:'present_answer',description:'finish',inputSchema:{type:'object'}}],
    releaseDigest:'d1',maxCalls:1,invoke:async()=>{invoked++;return {accepted:true,releaseDigest:'d1'};}});
  assert.equal((await plugin.beforeToolCall({toolCall:{name:'bash'}})).block,true);
  assert.equal(await plugin.beforeToolCall({toolCall:{name:'present_answer'}}),undefined);
  const result=await plugin.tools[0].execute('c1',{});
  assert.equal(invoked,1);
  assert.deepEqual(await plugin.afterToolCall({toolCall:{name:'present_answer'},result,isError:false}),{terminate:true});
  assert.equal(plugin.completed,true);
  assert.equal((await plugin.beforeToolCall({toolCall:{name:'present_answer'}})).block,true);
});

test('mismatched release and error never count as successful answer',async()=>{
  const plugin=createSemanticPlugin({catalog:[],releaseDigest:'d1',invoke:()=>{},maxCalls:0});
  const mismatch=await plugin.afterToolCall({toolCall:{name:'present_answer'},result:{details:{accepted:true,releaseDigest:'d2'}},isError:false});
  assert.equal(mismatch.isError,true);assert.equal(plugin.completed,false);
  assert.equal((await plugin.afterToolCall({toolCall:{name:'present_answer'},result:{details:{error:'BAD'}},isError:false})).isError,true);
});

test('official pi Agent uses native hooks and stops after accepted answer',async()=>{
  const {Agent}=await import('@earendil-works/pi-agent-core');
  const {createModels,fauxProvider,fauxAssistantMessage,fauxToolCall}=await import('@earendil-works/pi-ai');
  const faux=fauxProvider();const models=createModels();models.setProvider(faux.provider);
  faux.setResponses([fauxAssistantMessage([fauxToolCall('present_answer',{kind:'answer',text:'See evidence',evidenceIds:['e1']})],{stopReason:'toolUse'})]);
  const plugin=createSemanticPlugin({catalog:[{name:'present_answer',description:'finish',inputSchema:{type:'object',properties:{kind:{type:'string'},text:{type:'string'},evidenceIds:{type:'array',items:{type:'string'}}},required:['kind','text','evidenceIds'],additionalProperties:false}}],
    releaseDigest:'release1',invoke:async()=>({accepted:true,releaseDigest:'release1'})});
  const agent=new Agent({initialState:{model:faux.getModel(),tools:plugin.tools},
    streamFn:models.streamSimple.bind(models),beforeToolCall:plugin.beforeToolCall,afterToolCall:plugin.afterToolCall});
  await agent.prompt('test');
  assert.equal(plugin.completed,true);assert.equal(plugin.calls,1);assert.equal(agent.state.isStreaming,false);
});


test('official pi terminates on server-owned population answer without another model arithmetic turn', async()=>{
  const {Agent}=await import('@earendil-works/pi-agent-core');
  const {createModels,fauxProvider,fauxAssistantMessage,fauxToolCall}=await import('@earendil-works/pi-ai');
  const faux=fauxProvider(); const models=createModels(); models.setProvider(faux.provider);
  faux.setResponses([fauxAssistantMessage([fauxToolCall('analyze_population',{})],{stopReason:'toolUse'})]);
  const plugin=createSemanticPlugin({catalog:[{name:'analyze_population',description:'stats',inputSchema:{type:'object'}}],
    releaseDigest:'release1',invoke:async()=>({answerReady:true,releaseDigest:'release1'})});
  const agent=new Agent({initialState:{model:faux.getModel(),tools:plugin.tools},streamFn:models.streamSimple.bind(models),
    beforeToolCall:plugin.beforeToolCall,afterToolCall:plugin.afterToolCall});
  await agent.prompt('mean');
  assert.equal(plugin.completed,true); assert.equal(plugin.calls,1);
});

test('official pi terminates on NEEDS_INPUT without waiting on a live process', async()=>{
  const {Agent}=await import('@earendil-works/pi-agent-core');
  const {createModels,fauxProvider,fauxAssistantMessage,fauxToolCall}=await import('@earendil-works/pi-ai');
  const faux=fauxProvider(); const models=createModels(); models.setProvider(faux.provider);
  faux.setResponses([fauxAssistantMessage([fauxToolCall('prepare_semantic_query',{question:'收入多少'})],{stopReason:'toolUse'})]);
  const plugin=createSemanticPlugin({catalog:[{name:'prepare_semantic_query',description:'prepare',inputSchema:{type:'object'}}],
    releaseDigest:'release1',invoke:async()=>({status:'NEEDS_INPUT',waiting:true,releaseDigest:'release1'})});
  const agent=new Agent({initialState:{model:faux.getModel(),tools:plugin.tools},streamFn:models.streamSimple.bind(models),
    beforeToolCall:plugin.beforeToolCall,afterToolCall:plugin.afterToolCall});
  await agent.prompt('收入多少');
  assert.equal(plugin.completed,true); assert.equal(agent.state.isStreaming,false);
});

test('NEEDS_INPUT without releaseDigest is a mismatch not a wait', async()=>{
  const plugin=createSemanticPlugin({catalog:[],releaseDigest:'release1',invoke:()=>{},maxCalls:0});
  const blocked=await plugin.afterToolCall({toolCall:{name:'prepare_semantic_query'},result:{details:{status:'NEEDS_INPUT',waiting:true}},isError:false});
  assert.equal(blocked.isError,true); assert.equal(plugin.completed,false);
});

test('server converts prose clarification into a persisted choice and pi stops immediately', async()=>{
  const plugin=createSemanticPlugin({
    catalog:[{name:'present_answer',description:'finish',inputSchema:{type:'object'}}],
    releaseDigest:'d1',invoke:async()=>({releaseDigest:'d1',status:'NEEDS_INPUT',waiting:true}),
  });
  const result=await plugin.tools[0].execute('choice',{});
  assert.deepEqual(await plugin.afterToolCall({toolCall:{name:'present_answer'},result,isError:false}),{terminate:true});
  assert.equal(plugin.completed,true);
});
