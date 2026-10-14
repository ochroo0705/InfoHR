CREATE TRIGGER TR_UPDCUSTOMER FOR CUSTOMER 
ACTIVE BEFORE UPDATE POSITION 0 
AS
DECLARE VARIABLE CORDERS INTEGER;
DECLARE VARIABLE CJOURNAL INTEGER;
BEGIN
  IF (NEW.CUST_ID<>OLD.CUST_ID) THEN BEGIN
    SELECT order_id
      FROM ORDERS
      WHERE (DBCUST_IDENT=OLD.CUST_ID) OR (CRCUST_IDENT=OLD.CUST_ID)
      rows 1
      INTO CORDERS;

    SELECT journal_id
      FROM JOURNAL
      WHERE (DBCUST_IDENT=OLD.CUST_ID) OR (CRCUST_IDENT=OLD.CUST_ID)
      rows 1
      INTO CJOURNAL;
    IF ((CORDERS>0) OR (CJOURNAL>0)) THEN
      EXCEPTION CANNOT_CHANGE_CUSTID;
  END
  if ((new.employee='yes') and
     (((OLD.register IS NULL) AND (NEW.register IS NOT NULL)) OR
     ((OLD.register IS NOT NULL) AND (NEW.register IS NULL)) OR
     ((OLD.register IS NOT NULL) AND (NEW.register IS NOT NULL) AND (OLD.register<>NEW.register))))
   then
    update employee e set e.registerno=new.register where e.employee_id=new.employee_ident;
  new.modified_date  = current_timestamp;
END ^
