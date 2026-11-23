-- Grants for the welcome app's table on the Firebird database (demo requests from the public welcome page).
-- Hand-written, not generated: the welcome app is loaded only when PUBLIC_WELCOME=true, so
-- scripts/grant_macs_fb.sql (generated from the installed models) does not contain these lines.
-- Use this file only on InfoSystems' own server, where PUBLIC_WELCOME=true is set.
--
-- Nothing in this file is a password. The password is set on the server, never here.
--
-- WHO RUNS THIS, AND WHEN
--   The database administrator, once, as SYSDBA, after "manage.py migrate welcome" has created
--   the IHR_WELCOME_DEMOREQUEST table and its generator. Run it against the database file
--   (for example with isql, connected as SYSDBA). Run it after scripts/grant_macs_fb.sql.
--   The user MACS_HR_RT must already exist (see scripts/grant_macs_fb.sql, "HOW TO CREATE THE USER").
--
-- WHAT IS GRANTED
--   1. The demo-request table: SELECT, INSERT, UPDATE, DELETE, all for the runtime login MACS_HR_RT
--      (the login the Django app connects with, including the Django admin site):
--      SELECT and INSERT for the public form that saves a request; UPDATE because welcome/service.py
--      sets mail_status and mail_error after the row is saved; DELETE so a superuser can delete a
--      request in the Django admin.
--   2. USAGE on the table's generator (its auto id).
--
-- After the script, COMMIT is issued.

-- 1. Demo-request table and its generator
GRANT SELECT, INSERT, UPDATE, DELETE ON IHR_WELCOME_DEMOREQUEST TO MACS_HR_RT;
GRANT USAGE ON SEQUENCE IHR_WELCOME_DEMOREQUEST_SQ TO MACS_HR_RT;
COMMIT;
