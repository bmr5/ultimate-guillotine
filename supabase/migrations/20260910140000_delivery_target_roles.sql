-- A delivery target gains a role, so the listener can hear a chat it never speaks in.
--
-- Until now `private.delivery_targets` answered one question -- "where does this mode post?" --
-- and the listener reused it for a second one it happens to also answer: "which chats may a
-- webhook come from?". In test mode that means the only chat the automation can hear is the
-- self-test chat, so a real trade alert in the league chat is invisible to the Registrar. Shadow
-- mode separates the two: a `listen` row is a chat whose messages are processed and which is
-- never delivered to.
--
-- `mode` becomes nullable and carries the whole meaning of `role`:
--
--   * a `deliver` row has a mode, and `delivery_targets_mode_key` still allows exactly one per
--     mode -- `DeliveryService` resolves its target by mode and must keep finding one row;
--   * a `listen` row has no mode at all, because it is not any mode's destination. A null there
--     is not a missing value; it is the fact that the question does not apply. Nulls are distinct
--     under a unique constraint, so several listen rows coexist without touching the existing
--     index.
--
-- The check constraint ties the two columns together in both directions, so neither a listen row
-- that claims a mode nor a deliver row that has lost one can be written at all.
--
-- Listen rows are unique on `chat_guid_hash` rather than on the GUID: re-registering the same
-- chat has to update in place (nobody wants two rows for one conversation), and the hash is the
-- column already used to compare chats everywhere else, so the index carries no new plaintext.

alter table private.delivery_targets
  add column role text not null default 'deliver'
    check (role in ('deliver', 'listen'));

alter table private.delivery_targets alter column mode drop not null;

alter table private.delivery_targets
  add constraint delivery_targets_mode_matches_role
    check ((role = 'deliver') = (mode is not null));

create unique index delivery_targets_listen_chat_idx
  on private.delivery_targets (chat_guid_hash)
  where role = 'listen';

comment on column private.delivery_targets.role is
  'deliver: the one chat this mode posts to. listen: a chat the listener processes messages '
  'from and never posts to -- shadow mode, where the league chat is heard and the self-test '
  'chat is answered. A listen row carries no mode; it is not any mode''s destination.';

-- No new grants: `automation_worker` already holds the privileges it needs on this table, and a
-- listen row is registered by `ug targets listen` on the installer's own login.
