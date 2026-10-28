-- Grants for the HR app role on a database with the production MACS structure (D-018).
-- What these enforce in the database:
--   * select, insert, update on every table in public (HR writes production rows).
--   * references on every table in public (HR tables point at production rows).
--   * delete only on the list tables, emp_photo, and movement/employee_history (cancelling an
--     HR event removes the rows it wrote) listed below. employee has no delete grant,
--     so the app role cannot delete employees at database level.
--   * customer: insert and update only (hire row + address copy, D-024); no delete.
-- Not enforced here: which columns or rows HR may change; that is checked in the HR code
-- (employees/services/macs_writes.py, tests_guard).
grant usage on schema public to info_hr_app;
grant select, insert, update on all tables in schema public to info_hr_app;
grant insert, update on customer to info_hr_app;
-- HR tables (schema hr) hold foreign keys to production rows (deps, occupation, employee, lists).
grant references on all tables in schema public to info_hr_app;
grant delete on emp_photo, deps, occupation, marital_status, country, nationality, niigmiin_garal,
  apartment_cond, carown_cond, voting_work, clothes_size_type, citytown, district, education,
  graduate, insur_type, banks, shifts, fired_reason, movement, employee_history to info_hr_app;
grant usage, select on all sequences in schema public to info_hr_app;
-- Leave module (sub-project 3): the app writes these production tables directly.
-- leave_assign is cancelled by status, never deleted; leave_type and hr_legalholidays are deleted
-- by the leave settings and holidays screens (delete only where the screen needs it).
grant select, insert, update on leave_type, leave_assign, entitlement, hr_legalholidays to info_hr_app;
grant delete on leave_type, hr_legalholidays to info_hr_app;
-- emp_vacation: one total row per employee per year for annual leave (Q-13); updated, never deleted.
grant select, insert, update on emp_vacation to info_hr_app;
grant usage, select on sequence gen_leave_type_id, gen_leave_assign_id, gen_entitlement_id,
  gen_hr_legalholidays_id to info_hr_app;
-- Personal lists (sub-project 4): the app writes these production tables directly, and deletes rows
-- when the user removes them. emp_talents has no sequence (its key is emp_ident + talent_ident).
grant select, insert, update, delete on family, relative, before_work, educ, given_present, address, contacting, emp_talents, hr_skillwork, material_help, awards, discipline, hr_complaints, body, driver, military, army_rank
  to info_hr_app;
grant select, insert, update, delete on family_members, edu_type, present_type, contact_type, talents, material_help_type, discipline_type, driver_type
  to info_hr_app;
grant usage, select on sequence gen_family_id, gen_relative_id, gen_before_work_id, gen_educ_id, gen_given_present_id, gen_address_id,
  gen_contacting_id, gen_family_members_id, gen_edu_type_id, gen_talents_id, gen_present_type_id,
  gen_contact_type_id, gen_hr_skillwork_id, gen_material_help_id, gen_material_help_type_id, gen_awards_id,
  gen_discipline_id, gen_discipline_type_id, gen_hr_complaints_id, gen_body_id, gen_driver_id, gen_driver_type_id, gen_military_id,
  gen_army_rank_id to info_hr_app;
-- Qualifications, certificates, training and languages (anketa tabs): rows are edited and deleted
-- from the personal tab; the list tables are edited on the Lists screen.
grant select, insert, update, delete on qualification, spec_edu, hr_training, foreign_lang
  to info_hr_app;
grant select, insert, update, delete on qualification_type, profession_type, spec_edu_type,
  flanguages, lang_level to info_hr_app;
grant usage, select on sequence gen_qualification_id, gen_spec_edu_id, gen_hr_training_id,
  gen_foreign_lang_id, gen_qualification_type_id, gen_profession_type_id, gen_spec_edu_type_id,
  gen_flanguages_id, gen_lang_level_id to info_hr_app;
grant usage, create on schema hr to info_hr_app;
-- The HR date-overlap constraints need btree_gist; only a superuser can install it.
create extension if not exists btree_gist schema hr;
-- HR orders: command rows are inserted and updated, never deleted (cancelled orders keep their row).
grant select, insert, update on command to info_hr_app;
grant usage, select on sequence gen_command_id to info_hr_app;
