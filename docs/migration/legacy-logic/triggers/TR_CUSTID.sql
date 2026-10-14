CREATE TRIGGER TR_CUSTID FOR CUSTOMER 
ACTIVE BEFORE INSERT POSITION 0 
AS
BEGIN
  IF (NEW.CUST_ID IS NULL) THEN
    NEW.CUST_ID = GEN_ID(GEN_CUSTID,1);
  if (new.employee='yes') then
    update employee e set e.registerno=new.register where e.employee_id=new.employee_ident;

  new.modified_date  = current_timestamp;
END ^
