-- The chat a video was asked from. In production the league chat is the delivery target,
-- but a request made in the self-test chat is answered there (see DeliveryService's
-- reply_to, 2026-09-10), and the render finishes minutes later in a cron job that has no
-- message to reply to -- so the job carries the chat itself. Null means the mode's target.
alter table private.video_jobs add column chat_guid text;
