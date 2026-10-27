const { createHash, timingSafeEqual } = require('node:crypto');
const { Pool } = require('pg');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

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
      await client.query('COMMIT');
      return res.status(200).json({
        generated_at: new Date().toISOString(), season,
        counts: { registered: registered.rows.length, historical_catalog: catalog.rows.length },
        notes: 'Registered trades contain their current revision, including rescinded records. The historical catalog is a separate source and can overlap; do not add the counts as unique trades. TEST records are excluded. Deposits and refunds are not rental profit.',
        registered_trades: registered.rows,
        historical_catalog: catalog.rows,
        members: members.rows,
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
