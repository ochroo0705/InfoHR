CREATE TRIGGER TR_DELEMPLOYEE FOR EMPLOYEE 
ACTIVE BEFORE DELETE POSITION 0 
AS
BEGIN
  DELETE FROM CUSTOMER
    WHERE (EMPLOYEE_IDENT=OLD.EMPLOYEE_ID) AND (EMPLOYEE='yes');

  delete from checkinout
    where (emp_ident=old.employee_id);

  delete from address
    where (employee_ident=old.employee_id);

  delete from army_rank
    where (employee_ident=old.employee_id);

  delete from awards
    where (employee_ident=old.employee_id);

  delete from before_work
    where (employee_ident=old.employee_id);

  delete from birth_place
    where (emp_id=old.employee_id);

  delete from body
    where (employee_ident=old.employee_id);

  delete from command
    where (employee_ident=old.employee_id);

  delete from contacting
    where (employee_ident=old.employee_id);

  delete from driver
    where (employee_ident=old.employee_id);

  delete from emp_photo
    where (emp_id=old.employee_id);

  delete from family
    where (employee_ident=old.employee_id);

  delete from foreign_lang
    where (employee_ident=old.employee_id);

  delete from given_present
    where (empid=old.employee_id);

  delete from holiday
    where (employee_ident=old.employee_id);

  delete from material_help
    where (employee_ident=old.employee_id);

  delete from educ
    where (employee_ident=old.employee_id);

  delete from emp_talents
    where (emp_ident=old.employee_id);

  delete from movement
    where (emp_id=old.employee_id);

  delete from qualification
    where (employee_ident=old.employee_id);

  delete from relative
    where (employee_ident=old.employee_id);

  delete from spec_edu
    where (employee_ident=old.employee_id);
     
  delete from discipline
    where (employee_ident=old.employee_id);

  delete from emp_photo where emp_id=old.employee_id;
  delete from emp_actlist where emp_ident=old.employee_id;
  delete from FACTORY_ACCIDENT where empid=old.employee_id;
  delete from employee_history where employee_ident=old.employee_id;
  delete from leave_assign  where emp_ident=old.employee_id;
END ^
