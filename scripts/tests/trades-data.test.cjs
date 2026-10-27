const { test } = require('node:test');
const assert = require('node:assert/strict');
const { finances, shapeData } = require('../../api-data/trades.cjs');
test('separates explicit rental fee and deposit; conditional refund is not settlement',()=>{
 const result=finances([
  {kind:'faab',amount:25,unit:'faab',from_member_id:5,to_member_id:9,description:'$25 nonrefundable rental fee'},
  {kind:'faab',amount:85,unit:'faab',from_member_id:5,to_member_id:9,description:'an $85 deposit'},
 ],{rental_return_condition:'If Kyle returns Ladd, David sends Diggs and the $85 deposit back.'});
 assert.equal(result.rental_fees[0].amount,25);assert.equal(result.deposits[0].amount,85);
 assert.equal(result.refunds[0].amount,85);assert.equal(result.refunds[0].from_member_id,9);
 assert.equal(result.refunds[0].payment_status,'conditional_not_verified');
});
test('never estimates unpriced components or splits combined prices',()=>{
 const r=finances([{kind:'faab',amount:110,description:'fee plus deposit'}, {kind:'faab',amount:null,description:'rental fee'}]);
 assert.equal(r.unclassified_payments[0].amount,110);assert.equal(r.rental_fees[0].amount,null);
 assert.equal(r.deposits.length,0);assert.equal(r.refunds.length,0);
 assert.equal(r.price_resolution,'unresolved_components');
 const option=finances([{kind:'faab',amount:5,description:'option fee'}]);
 assert.equal(option.rental_fees.length,0);assert.equal(option.other_payments.length,1);
});
function fixture(){return {registered:[{trade_code:'T-2026-001',season:2026,status:'accepted',announced_at:'2026-10-20T12:00:00Z',terms:{parties:[{member_id:1},{member_id:2}],assets:[{kind:'player',player_id:'p1',from_member_id:1,to_member_id:2},{kind:'faab',amount:10,from_member_id:2,to_member_id:1}]}}],catalog:[{catalog_id:'T-2026-001',season:2026,assets:[],party_member_ids:[1,2]}],members:[],teams:[{id:11,member_id:1,sleeper_roster_id:3,season:2026},{id:22,member_id:2,sleeper_roster_id:4,season:2026}],players:[],executions:[{id:100,season:2026,sleeper_transaction_id:'s1',occurred_at:'2026-10-20T13:00:00Z',status:'complete',team_ids:[11,22],faab_moves:[{amount:10,from_team_id:22,to_team_id:11}]}],moves:[{transaction_id:100,sleeper_player_id:'p1',team_id:11,action:'drop'},{transaction_id:100,sleeper_player_id:'p1',team_id:22,action:'add'}]};}
test('announcement and execution remain separate, exact ID catalog overlap is one deal',()=>{
 const r=shapeData(fixture());assert.equal(r.deals.length,1);
 assert.equal(r.sleeper_executions[0].status,'complete');assert.equal(r.sleeper_executions[0].count_as_additional_deal,false);
 assert.equal(r.registered_trades[0].completion_status,'not_established_from_announcement');
 assert.equal(r.registered_trades[0].execution_links[0].relationship,'candidate_only');
 assert.equal(r.registered_trades[0].assets[0].from.sleeper_roster_id,3);
 assert.equal(r.sleeper_executions[0].cash_transfers[0].rental_fee,null);
});
test('wrong cash amounts, reversed players, or missing announcement dates are not linked',()=>{
 for(const mutate of [f=>f.executions[0].faab_moves[0].amount=11,f=>f.moves[0].team_id=22,f=>f.registered[0].announced_at=null]){
  const f=fixture();mutate(f);const r=shapeData(f);assert.equal(r.registered_trades[0].execution_links.length,0);assert.equal(r.deduplication.unlinked_execution_ids.length,1);
 }
});
