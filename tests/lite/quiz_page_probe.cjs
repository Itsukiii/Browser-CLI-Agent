// Pure page-state tests. Does not load Maa or browser automation code.
const assert = require('node:assert/strict');
const {createQuiz} = require('../../src/bca/lite/resources/quiz/quiz.js');
let clock = 0;
const game = createQuiz({seed: 20261127, now:()=>clock});
const samples=[], digits=new Set(), positions=new Set();
for(let i=0;i<500;i++) {
  const before=game.snapshot();
  assert.equal(new Set(before.options).size,4);
  assert.equal(before.options.filter(n=>n===before.question).length,1);
  assert(before.options.every(n=>Number.isInteger(n)&&n>=0&&n<=9));
  digits.add(before.question);positions.add(before.options.indexOf(before.question));
  assert.equal(game.confirm(before.round),false);
  assert(game.select(before.options.indexOf(before.question),before.round));
  assert.equal(game.snapshot().score,before.score);
  clock+=9999;
  assert.equal(game.tick(),false);
  clock+=1;
  assert.equal(game.tick(),true);
  const after=game.snapshot();
  assert.notEqual(before.question,after.question);
  assert.equal(after.selected,null);
  assert.equal(after.score,before.score);
  assert.equal(after.timeLeft,10);
  assert.equal(game.select(0,before.round),false);
  assert.equal(game.confirm(before.round),false);
  samples.push({before,after});
}
assert.equal(digits.size,10);assert.equal(positions.size,4);
const settlements=[];
for(const initial of ['0','-1','-20','-305','12','345','6789','999999999999999999999999999999']) {
  for(const correct of [true,false]) {
    game.testSet({newScore:initial});
    const before=game.snapshot();
    const index=before.options.findIndex(n=>correct?n===before.question:n!==before.question);
    assert(game.select(index,before.round));
    clock+=100;
    assert(game.confirm(before.round));
    const after=game.snapshot();
    assert.equal(BigInt(after.score)-BigInt(before.score),correct?1n:-1n);
    assert.notEqual(after.round,before.round);assert.notEqual(after.question,before.question);
    assert.equal(after.timeLeft,10);
    assert.equal(game.confirm(before.round),false);
    assert.equal(game.confirm(after.round),false);
    settlements.push({correct,before,after});
  }
}
game.testSet({newRound:'999999'});clock+=10000;game.tick();
assert.equal(game.snapshot().round,'1000000');
assert.throws(()=>game.testSet({newRound:'1'}));
const bounded=createQuiz({seed:7,now:()=>0});
for(let i=0;i<500;i++) {
  const s=bounded.snapshot();bounded.select(0,s.round);bounded.confirm(s.round);
  assert(bounded.events.length<=256);
}
const repeat=createQuiz({seed:20261127,now:()=>0});
assert.deepEqual(repeat.snapshot(),samples[0].before);
clock--;assert.throws(()=>game.snapshot(),/monotonic/);
console.log(JSON.stringify({node:process.version,rounds:500,digits:[...digits].sort(),
  positions:[...positions].sort(),samples,settlements,round_capacity:'1000000',status:'passed'},null,2));
