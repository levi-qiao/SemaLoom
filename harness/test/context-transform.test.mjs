import test from 'node:test';
import assert from 'node:assert/strict';
import {
  convertToLlm,
  estimateContextTokens,
} from '@earendil-works/pi-agent-core';
import {
  transformContext,
  extractContentText,
} from '../context-transform.mjs';

test('extractContentText handles string and array content', () => {
  assert.equal(extractContentText('hello world'), 'hello world');
  assert.equal(
    extractContentText([
      { type: 'text', text: 'line 1' },
      { type: 'text', text: 'line 2' },
    ]),
    'line 1\nline 2'
  );
  assert.equal(extractContentText(null), '');
  assert.equal(extractContentText([]), '');
});

test('transformContext preserves single turn without past turns', () => {
  const messages = [{ role: 'user', content: 'hello' }];
  const transformed = transformContext(messages);
  assert.deepEqual(transformed, messages);
});

test('transformContext prunes bulky historical toolResult while preserving active turn', () => {
  const messages = [
    { role: 'user', content: 'Turn 1 question' },
    {
      role: 'assistant',
      content: [{ type: 'toolCall', id: 'call_1', name: 'query', args: {} }],
    },
    {
      role: 'toolResult',
      toolCallId: 'call_1',
      content: [{ type: 'text', text: 'Very long json result '.repeat(30) }],
    },
    { role: 'assistant', content: [{ type: 'text', text: 'Turn 1 answer' }] },
    // Active turn (Turn 2)
    { role: 'user', content: 'Turn 2 question' },
    {
      role: 'assistant',
      content: [{ type: 'toolCall', id: 'call_2', name: 'query', args: {} }],
    },
    {
      role: 'toolResult',
      toolCallId: 'call_2',
      content: [{ type: 'text', text: 'Active turn unpruned result '.repeat(30) }],
    },
  ];

  const transformed = transformContext(messages);
  assert.equal(transformed.length, 7);
  // Turn 1 tool result should be pruned
  assert.match(
    extractContentText(transformed[2].content),
    /历史语义工具结果已核对并归档/
  );
  // Active turn tool result must NOT be pruned
  assert.match(
    extractContentText(transformed[6].content),
    /Active turn unpruned result/
  );
});

test('transformContext compacts older turns into Pi-native compactionSummary when threshold met', () => {
  const messages = [
    // Turn 1
    { role: 'user', content: 'Turn 1 question' },
    { role: 'assistant', content: [{ type: 'text', text: 'Turn 1 answer' }] },
    // Turn 2
    { role: 'user', content: 'Turn 2 question' },
    { role: 'assistant', content: [{ type: 'text', text: 'Turn 2 answer' }] },
    // Turn 3
    { role: 'user', content: 'Turn 3 question' },
    { role: 'assistant', content: [{ type: 'text', text: 'Turn 3 answer' }] },
    // Turn 4 (Active turn)
    { role: 'user', content: 'Turn 4 question' },
  ];

  // maxPastTurns = 1, so Turn 1 and Turn 2 should be compacted into compactionSummary,
  // Turn 3 is kept as recent, Turn 4 is the active turn.
  const transformed = transformContext(messages, { maxPastTurns: 1 });
  assert.equal(transformed[0].role, 'compactionSummary');
  assert.match(transformed[0].summary, /Turn 1 question/);
  assert.match(transformed[0].summary, /Turn 1 answer/);
  assert.match(transformed[0].summary, /Turn 2 question/);
  assert.match(transformed[0].summary, /Turn 2 answer/);

  // Turn 3 and Turn 4 must remain
  assert.equal(transformed[1].content, 'Turn 3 question');
  assert.equal(transformed[3].content, 'Turn 4 question');

  // Verify Pi native convertToLlm recognizes compactionSummary
  const llm = convertToLlm(transformed);
  assert.equal(llm[0].role, 'user');
  assert.match(llm[0].content[0].text, /The conversation history before this point was compacted into the following summary/);
  assert.match(llm[0].content[0].text, /<summary>/);
  assert.match(llm[0].content[0].text, /Turn 1 question/);
});

test('repeated compaction accumulates existing summaries cleanly', () => {
  let messages = [];
  for (let turn = 1; turn <= 5; turn++) {
    messages.push({ role: 'user', content: `Q${turn}` });
    messages = transformContext(messages, { maxPastTurns: 2 });
    messages.push({
      role: 'assistant',
      content: [{ type: 'text', text: `A${turn}` }],
    });
  }

  const finalTransformed = transformContext(messages, { maxPastTurns: 2 });
  const summaryMsg = finalTransformed.find(m => m.role === 'compactionSummary');
  assert.ok(summaryMsg, 'Should have compactionSummary');
  assert.match(summaryMsg.summary, /Q1/);
  assert.match(summaryMsg.summary, /A1/);
  assert.match(summaryMsg.summary, /Q2/);
  assert.match(summaryMsg.summary, /A2/);

  // Token estimate should remain bounded
  const tokens = estimateContextTokens(finalTransformed).tokens;
  assert.ok(tokens < 1000, `Token count ${tokens} should be tightly bounded`);
});
