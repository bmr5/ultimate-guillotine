const { createHash, timingSafeEqual } = require('node:crypto');
const { Pool } = require('pg');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { shapeData } = require('../api-data/trades.cjs');

let pool;
const digest = (value) => createHash('sha256').update(value).digest();

function createHandler(getPool = () => {
  const url = new URL(process.env.TRADES_DATABASE_URL);
  url.searchParams.delete('sslmode');
  pool ??= new Pool({
    connectionString: url.toString(),
    ssl: { ca: readFileSync(join(__dirname, 'supabase-ca.crt'), 'utf8'), rejectUnauthorized: true },
    max: 1,
    connectionTimeoutMillis: 8000,
    idleTimeoutMillis: 10000,
    statement_timeout: 10000,
  });
  return pool;
}) {
  return async (req, res) => {
    res.setHeader('Cache-Control', 'private, no-store');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    if (req.method !== 'GET') {
      res.setHeader('Allow', 'GET');
      return res.status(405).json({ error: 'Use GET.' });
    }
    const expected = process.env.TRADES_API_KEY;
    if (!expected || !process.env.TRADES_DATABASE_URL) {
      return res.status(503).json({ error: 'Trades service is not configured.' });
    }
    const supplied = req.headers['x-api-key'] ||
      (req.headers.authorization || '').replace(/^Bearer /i, '');
    if (typeof supplied !== 'string' || !timingSafeEqual(digest(supplied), digest(expected))) {
      return res.status(401).json({ error: 'A valid API key is required.' });
    }
    const seasonText = new URL(req.url, 'https://localhost').searchParams.get('season');
    if (seasonText !== null && !/^20\d{2}$/.test(seasonText)) {
      return res.status(400).json({ error: 'season must be a four-digit year, such as 2026.' });
    }
    const season = seasonText === null ? null : Number(seasonText);
    let client;
    try {
      client = await getPool().connect();
      await client.query('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY');
      const registered = await client.query(`
        SELECT t.trade_code, s.year AS season, t.status, t.created_at,
               t.announced_at, t.announced_by, r.revision, r.effective_week,
               r.terms - 'source_message_guid' - 'model' - 'prompt_version' AS terms
        FROM public.trades t JOIN public.seasons s ON s.id = t.season_id
        LEFT JOIN public.trade_revisions r ON r.id = t.current_revision_id
        WHERE ($1::integer IS NULL OR s.year = $1)
          AND t.trade_code NOT LIKE 'TEST-%'
        ORDER BY s.year DESC, t.announced_at DESC NULLS LAST, t.id DESC
      `, [season]);
      const catalog = await client.query(`
        SELECT catalog_id, season, week, occurred_on, trade_type, structure,
               party_member_ids, assets, confidence, announcement, unresolved_parties
        FROM public.trade_catalog WHERE ($1::integer IS NULL OR season = $1)
        ORDER BY season DESC, occurred_on DESC NULLS LAST, catalog_id
      `, [season]);
      const members = await client.query('SELECT id, nickname, sleeper_display_name FROM public.members ORDER BY id');
      const teams = await client.query(`SELECT t.id, t.member_id, t.sleeper_roster_id, t.team_name,
          s.year AS season, s.sleeper_league_id FROM public.teams t
          JOIN public.seasons s ON s.id=t.season_id WHERE ($1::integer IS NULL OR s.year=$1)
          ORDER BY s.year,t.id`, [season]);
      const executions = await client.query(`SELECT t.id, t.sleeper_transaction_id, s.year AS season,
          s.sleeper_league_id, t.week, t.occurred_at, t.synced_at, t.team_ids, t.faab_moves,
          t.raw->>'status' AS status, t.raw->'draft_picks' AS draft_picks
          FROM public.transactions t JOIN public.seasons s ON s.id=t.season_id
          WHERE t.kind='trade' AND ($1::integer IS NULL OR s.year=$1)
          ORDER BY t.occurred_at DESC, t.id DESC`, [season]);
      const moves = await client.query(`SELECT m.transaction_id,m.sleeper_player_id,m.team_id,m.action
          FROM public.transaction_moves m JOIN public.transactions t ON t.id=m.transaction_id
          JOIN public.seasons s ON s.id=t.season_id
          WHERE t.kind='trade' AND ($1::integer IS NULL OR s.year=$1)`, [season]);
      const playerIds = [...new Set([
        ...registered.rows.flatMap(t => (t.terms?.assets || []).map(a => a.player_id)),
        ...catalog.rows.flatMap(t => (t.assets || []).map(a => a.sleeper_player_id)),
        ...moves.rows.map(m => m.sleeper_player_id),
      ].filter(id => id != null).map(String))];
      const players = await client.query(`SELECT sleeper_player_id, full_name, position FROM public.players
          WHERE sleeper_player_id=ANY($1::text[])`, [playerIds]);
      await client.query('COMMIT');
      const data = shapeData({ registered: registered.rows, catalog: catalog.rows,
        members: members.rows, teams: teams.rows, players: players.rows,
        executions: executions.rows, moves: moves.rows });
      return res.status(200).json({
        schema_version: 2, generated_at: new Date().toISOString(), season,
        counts: { registered: registered.rows.length, historical_catalog: catalog.rows.length,
          deals: data.deals.length, sleeper_executions: data.sleeper_executions.length },
        notes: 'Latest registered terms and original evidence are preserved. Registration acceptance is not execution or rental completion. Empty financial categories mean unrecorded, not zero. Prices are never estimated. TEST registrations are excluded. Use deduplication guidance; counts are not a verified unique economic-trade total.',
        ...data,
      });
    } catch {
      if (client) await client.query('ROLLBACK').catch(() => {});
      console.error('Trades API database request failed');
      return res.status(503).json({ error: 'Trades are temporarily unavailable. Please retry.' });
    } finally {
      client?.release();
    }
  };
}

module.exports = createHandler();
module.exports.createHandler = createHandler;
