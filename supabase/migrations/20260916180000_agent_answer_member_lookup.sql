-- Keep recent-question context scoped to one member and one authorized chat.
create index agent_answers_chat_member_recent_idx
  on private.agent_answers (chat_guid_hash, asker_member_id, id desc);
