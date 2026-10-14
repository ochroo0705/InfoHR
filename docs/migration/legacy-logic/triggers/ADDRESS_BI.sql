CREATE TRIGGER ADDRESS_BI FOR ADDRESS 
ACTIVE BEFORE INSERT POSITION 0 
AS
BEGIN
  IF (NEW.address_id IS NULL) THEN
    NEW.ADDRESS_ID = GEN_ID(GEN_ADDRESS_ID,1);

  IF (NEW.ADDRESS IS not NULL) THEN
    update customer c set c.address=new.address
    where c.employee_ident=new.employee_ident;
END ^
