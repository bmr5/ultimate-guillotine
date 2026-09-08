-- `private.expected_runs` is installer-managed configuration (the cron
-- schedule the Mac mini installer syncs from hermes/guillotine/cron.yaml),
-- not a league fact recorded by a running agent. The installer step that
-- replaces its contents (`ExpectedRunRepository.replace_all`, invoked by
-- `ug ops sync-expected-runs`) runs under the `automation_worker` login, so
-- that role needs DELETE on this one table. Every other private/public
-- table stays insert/update-only for automation_worker: agents never delete
-- league facts or automation history.
grant delete on table private.expected_runs to automation_worker;
