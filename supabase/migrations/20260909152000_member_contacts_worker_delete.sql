-- Grant-only: let the automation_worker login replace a member's hashed handles.
--
-- `ug members handles load` rewrites each member's contact rows wholesale, the
-- same way `ug members aliases load` rewrites their aliases, so the worker needs
-- DELETE here for the same reason it has it on private.member_aliases: this
-- table is installer-managed mapping configuration, not a league fact. Nothing
-- else about the table changes -- it still holds hashes only, and anon still
-- holds nothing on it.
grant delete on private.member_contacts to automation_worker;
