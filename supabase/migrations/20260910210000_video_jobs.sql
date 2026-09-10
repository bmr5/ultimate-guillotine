-- The queue of requested trade videos. Ben replies to a trade alert with
-- "@bot create trade video"; the listener queues a row here and answers at once, and
-- `ug video jobs run` (a cron job on the mini) claims the next queued row, renders the
-- voiced clip (about twenty minutes and 78 Higgsfield credits), and delivers the file.
-- Runbook: docs/runbooks/trade-video.md.
--
-- Operational state, so it lives in the private schema with the runs and outbound
-- messages: automation_worker gets select/insert/update through the schema's default
-- privileges, nothing is readable from the web. trade_id and trade_code are copied
-- rather than a foreign key: a job is a request about a trade as it stood, and it must
-- keep its history even if the trade row is ever reworked.
create table private.video_jobs (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  trade_id bigint not null,
  trade_code text not null,
  status text not null default 'queued'
    check (status in ('queued', 'running', 'done', 'failed')),
  -- The GUID of the chat message that asked, so a request can be traced to its reply.
  requested_guid text,
  started_at timestamptz,
  finished_at timestamptz,
  attempts int not null default 0,
  output_path text,
  error text
);

-- The worker takes the oldest queued job; requests check for an open one per trade.
create index video_jobs_status_id_idx on private.video_jobs (status, id);
create index video_jobs_trade_id_idx on private.video_jobs (trade_id);
