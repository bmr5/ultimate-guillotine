// Pure shaping of recorded evidence. Never infer a missing price or contractual settlement.
const list = (value) => Array.isArray(value) ? value : [];
const numeric = (value) => typeof value === 'number' && Number.isFinite(value);
const key = (value) => value == null ? null : String(value);

function finances(assets, terms = {}) {
  const result = { rental_fees: [], deposits: [], refunds: [], other_payments: [], unclassified_payments: [] };
  const issues = [];
  for (const [index, asset] of list(assets).entries()) {
    if (!['faab', 'usd', 'draft_dollars'].includes(asset.kind)) continue;
    const description = asset.description || '';
    const component = {
      asset_index: index, amount: numeric(asset.amount) ? asset.amount : null,
      currency: asset.unit || (asset.kind === 'faab' ? 'faab' : asset.kind === 'usd' ? 'usd' : 'draft_dollars'),
      from_member_id: asset.from_member_id ?? null, to_member_id: asset.to_member_id ?? null,
      recorded_description: description || null,
      payment_status: /\bif\b|\bunless\b|\bupon\b|\bprovided\b/i.test(description) ? 'conditional_not_verified' : 'not_verified', source: 'recorded_asset',
    };
    const labels = [];
    if (/\bdeposit\b|\bcollateral\b/i.test(description)) labels.push('deposits');
    if (/\brefund(?:ed)?\b|\breturned\b/i.test(description)) labels.push('refunds');
    if (/\brental fee\b|\brent(?:al)?\b.*\bfee\b/i.test(description) ||
        (terms.kind === 'rental' && /\bfee\b/i.test(description) && !/\bhold|\boption/i.test(description))) labels.push('rental_fees');
    if (/\b(?:purchase|sale) price\b|\boption fee\b|\bhold(?:ing)? fee\b/i.test(description)) labels.push('other_payments');
    if (labels.includes('deposits') && /\bfee\b/i.test(description) && !labels.includes('rental_fees')) labels.push('combined_fee');
    const bucket = labels.length === 1 ? labels[0] : 'unclassified_payments';
    result[bucket].push(component);
    if (component.amount === null) issues.push({ asset_index: index, issue: 'amount_unresolved' });
    if (bucket === 'unclassified_payments') issues.push({ asset_index: index, issue: labels.length > 1 ? 'combined_or_ambiguous_components' : 'payment_purpose_unresolved' });
  }
  // Only expose a conditional refund amount when the exact deposit amount is explicitly
  // quoted in the return condition. A refundable deposit is not an executed refund.
  const condition = typeof terms.rental_return_condition === 'string' ? terms.rental_return_condition : '';
  for (const deposit of result.deposits) {
    if (deposit.amount === null || !/\bback\b|\breturn(?:ed|s)?\b|\brefund/i.test(condition)) continue;
    const amount = String(deposit.amount).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    if (!new RegExp(`\\$${amount}(?![\\d.])\\s+(?:FAAB\\s+)?deposit`, 'i').test(condition)) continue;
    result.refunds.push({ ...deposit, from_member_id: deposit.to_member_id,
      to_member_id: deposit.from_member_id, source: 'explicit_return_condition',
      payment_status: 'conditional_not_verified', recorded_description: condition });
  }
  return {
    ...result, price_resolution: issues.length ? 'unresolved_components' :
      Object.values(result).some(x => x.length) ? 'recorded_components_only' : 'no_numeric_price_recorded',
    unresolved: issues, rental_return_condition: terms.rental_return_condition ?? null,
    extraction_completeness: 'not_verified_against_every_clause; original terms remain authoritative evidence',
    special_terms: list(terms.special_terms),
    empty_categories_mean: 'not separately recorded, not zero; no prices estimated',
  };
}

function shapeData({ registered, catalog, members, teams, players, executions, moves }) {
  const teamByMember = new Map(teams.map(t => [`${t.season}:${t.member_id}`, t]));
  const playerById = new Map(players.map(p => [key(p.sleeper_player_id), p]));
  const party = (season, memberId) => {
    const team = teamByMember.get(`${season}:${memberId}`);
    return { member_id: memberId ?? null, team_id: team?.id ?? null, sleeper_roster_id: team?.sleeper_roster_id ?? null };
  };
  const normalizedAsset = (season, asset) => ({ ...asset,
    sleeper_player_id: key(asset.player_id ?? asset.sleeper_player_id),
    from: party(season, asset.from_member_id), to: party(season, asset.to_member_id),
    player_identity_status: (asset.player_id ?? asset.sleeper_player_id) == null ? 'not_recorded' : 'recorded_id',
  });
  const registeredTrades = registered.map(t => ({ ...t,
    deal_id: `registered:${t.trade_code}`, source: 'registered_announcement',
    registration_status: t.status, completion_status: 'not_established_from_announcement',
    parties: list(t.terms?.parties).map(p => party(t.season, p.member_id)),
    assets: list(t.terms?.assets).map(a => normalizedAsset(t.season, a)),
    finances: finances(t.terms?.assets, t.terms),
    execution_links: [],
  }));
  const registeredByCode = new Map(registeredTrades.map(t => [t.trade_code, t]));
  const historical = catalog.map(t => ({ ...t, source: 'historical_catalog',
    deal_id: registeredByCode.get(t.catalog_id)?.deal_id ?? `catalog:${t.catalog_id}`,
    duplicates_registration: registeredByCode.has(t.catalog_id),
    completion_status: 'not_established_from_catalog',
    parties: list(t.party_member_ids).map(id => party(t.season, id)),
    assets: list(t.assets).map(a => {
      // Historical asset directions may be party indexes, not member IDs.
      const from = Number.isInteger(a.from_party) ? t.party_member_ids?.[a.from_party] : a.from_member_id;
      const to = Number.isInteger(a.to_party) ? t.party_member_ids?.[a.to_party] : a.to_member_id;
      return normalizedAsset(t.season, { ...a, from_member_id: from ?? null, to_member_id: to ?? null });
    }),
    finances: finances(t.assets),
  }));
  const platform = executions.map(e => {
    const events = moves.filter(m => key(m.transaction_id) === key(e.id));
    const ids = [...new Set(events.map(m => key(m.sleeper_player_id)))];
    const playerTransfers = ids.map(id => ({ sleeper_player_id: id,
      from_team_id: events.find(m => key(m.sleeper_player_id) === id && m.action === 'drop')?.team_id ?? null,
      to_team_id: events.find(m => key(m.sleeper_player_id) === id && m.action === 'add')?.team_id ?? null,
    }));
    return { ...e, source: 'sleeper_execution', execution_id: `sleeper:${e.sleeper_transaction_id}`,
      player_transfers: playerTransfers, cash_transfers: list(e.faab_moves).map(m => ({ ...m,
        currency: 'faab', purpose: 'unclassified_transfer',
        rental_fee: null, deposit: null, refund: null,
        price_resolution: 'amount_recorded_purpose_unresolved',
      })), candidate_deal_ids: [], count_as_additional_deal: false,
      note: 'Execution evidence only. Cash movements do not establish fee/deposit/refund purpose or settlement of all rental obligations.' };
  });
  // A candidate requires identical full player directions, participants, season and FAAB
  // movements within 72 hours of a recorded announcement. It is not a confirmed contract link.
  const signature = (edges) => edges.map(e => `${e.sleeper_player_id}:${e.from_team_id}:${e.to_team_id}`).sort().join('|');
  const cashSignature = (payments) => {
    const totals = new Map();
    for (const p of payments) {
      if (!numeric(p.amount) || p.from_team_id == null || p.to_team_id == null) return null;
      const k = `${p.from_team_id}:${p.to_team_id}`; totals.set(k, (totals.get(k) || 0) + p.amount);
    }
    return [...totals].sort(([a],[b]) => a.localeCompare(b)).map(([k,a]) => `${k}:${a}`).join('|');
  };
  for (const deal of registeredTrades) {
    const assets = deal.assets.filter(a => a.kind === 'player');
    if (!assets.length || !Number.isFinite(Date.parse(deal.announced_at)) || deal.status !== 'accepted' ||
        assets.some(a => !a.sleeper_player_id || !a.from.team_id || !a.to.team_id)) continue;
    const edges = assets.map(a => ({ sleeper_player_id: a.sleeper_player_id, from_team_id: a.from.team_id, to_team_id: a.to.team_id }));
    const payments = deal.assets.filter(a => a.kind === 'faab').map(a => ({ amount: a.amount, from_team_id: a.from.team_id, to_team_id: a.to.team_id }));
    const cash = cashSignature(payments);
    if (cash === null) continue;
    const parties = deal.parties.map(p => key(p.team_id)).sort().join('|');
    for (const execution of platform) {
      if (execution.season !== deal.season || !Number.isFinite(Date.parse(execution.occurred_at)) ||
          Math.abs(Date.parse(execution.occurred_at) - Date.parse(deal.announced_at)) > 72*3600000 ||
          list(execution.team_ids).map(key).sort().join('|') !== parties ||
          signature(execution.player_transfers) !== signature(edges) || cashSignature(execution.faab_moves || []) !== cash) continue;
      deal.execution_links.push({ execution_id: execution.execution_id, relationship: 'candidate_only',
        basis: 'same season, parties, full player directions and FAAB amounts within 72 hours',
        verification_status: 'not_manually_verified', execution_status: execution.status });
      execution.candidate_deal_ids.push(deal.deal_id);
    }
  }
  const referencedPlayers = new Set([
    ...registeredTrades.flatMap(t => t.assets.map(a => a.sleeper_player_id)),
    ...historical.flatMap(t => t.assets.map(a => a.sleeper_player_id)),
    ...platform.flatMap(t => t.player_transfers.map(a => a.sleeper_player_id)),
  ].filter(Boolean));
  return { registered_trades: registeredTrades, historical_catalog: historical,
    deals: [...registeredTrades, ...historical.filter(t => !t.duplicates_registration)],
    sleeper_executions: platform, members, teams,
    players: [...referencedPlayers].map(id => playerById.get(id) ?? { sleeper_player_id: id, full_name: null, position: null }),
    identity_notes: 'Player IDs are Sleeper IDs. team_id is internal; sleeper_roster_id is platform-specific and season-scoped. Missing historical IDs/directions are null, not name-matched guesses. Player directory names reflect the current directory.',
    deduplication: { rule: 'deals excludes historical catalog IDs identical to registered trade codes. Executions are evidence, not additional deals. Candidate links are not confirmed settlement. Other duplicates or unannounced executions can remain unresolved.',
      execution_relationships: 'candidate_only or unlinked; no speculative links are promoted to confirmed',
      unlinked_execution_ids: platform.filter(e => !e.candidate_deal_ids.length).map(e => e.execution_id),
      catalog_registration_overlaps: historical.filter(t => t.duplicates_registration).map(t => t.catalog_id),
    },
  };
}

module.exports = { finances, shapeData };
