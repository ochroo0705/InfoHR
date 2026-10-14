ALTER PROCEDURE MERGE_CUSTOMER (DATE1 TIMESTAMP,
DATE2 TIMESTAMP,
NEWCUST INTEGER,
OLDCUST INTEGER,
DELETE_OLDCUST SMALLINT)
AS 
declare variable YY1 integer;
declare variable MM1 integer;
declare variable YY2 integer;
declare variable MM2 integer;
begin
    IF (:DATE1 IS NULL) THEN
      SELECT DAT FROM CONVTODATE(100,1,1,3) INTO :DATE1;
    IF (:DATE2 IS NULL) THEN
      SELECT DAT FROM CONVTODATE(5941,1,1,3) INTO :DATE2;

    update journal set dbcust_ident = :newcust
    where (journalcode='GEN') and (dbcust_ident= : oldcust) and (jdate>=:date1) and (jdate<:date2);

    update journal set crcust_ident = :newcust
    where (journalcode='GEN') and (crcust_ident= : oldcust) and (jdate>=:date1) and (jdate<:date2);

    update orders set dbcust_ident = :newcust
    where (dbcust_ident= : oldcust) and (odate>=:date1) and (odate<:date2);

    update orders set crcust_ident = :newcust
    where (crcust_ident= : oldcust) and (odate>=:date1) and (odate<:date2);

    update assetrans set cust_ident = :newcust
    where (cust_ident= : oldcust) and (adate>=:date1) and (adate<:date2);

    update assetrans_new set cust_ident = :newcust
    where (cust_ident= : oldcust) and (adate>=:date1) and (adate<:date2);

    yy1 =  extract(year from :date1);
    mm1 =  extract(month from :date1);

    yy2 =  extract(year from :date2);
    mm2 =  extract(month from :date2);

    update monthsalary set emp_ident = :newcust
    where (emp_ident= : oldcust) and (((Myear= :yy1) and (MMonth>=:mm1)) or (myear>:yy1)) and (((myear= :yy2) and (mmonth<:mm2)) or (myear<:yy2));

    update monthsalary_new set emp_ident = :newcust
    where (emp_ident= : oldcust) and (((Myear= :yy1) and (MMonth>=:mm1)) or (myear>:yy1)) and (((myear= :yy2) and (mmonth<:mm2)) or (myear<:yy2));


    update colnames set dbcust_ident = :newcust
    where (dbcust_ident= : oldcust);
    update colnames set crcust_ident = :newcust
    where (crcust_ident= : oldcust);

    update branch_colnames set dbcust_ident = :newcust
    where (dbcust_ident= : oldcust);
    update branch_colnames set crcust_ident = :newcust
    where (crcust_ident= : oldcust);

    update spravc set cust_ident = :newcust
    where (cust_ident= : oldcust);

    update cashtransacc set dbcust_ident = :newcust
    where (dbcust_ident= : oldcust);
    update cashtransacc set crcust_ident = :newcust
    where (crcust_ident= : oldcust);

    update carno set custid = :newcust
    where (custid= : oldcust);

    update cash_temp set cust_ident = :newcust
    where (cust_ident= : oldcust);

    update contract_header set cust_ident = :newcust
    where (cust_ident= : oldcust);

    update cust_bank set cust_ident = :newcust
    where (cust_ident= : oldcust);

    update dhl_importinvoice set cust_ident = :newcust
    where (cust_ident= : oldcust);

    update dis_card set cust_ident = :newcust
    where (cust_ident= : oldcust);

    update emp_workpercent set emp_ident = :newcust
    where (emp_ident= : oldcust);

    update emp_colnames set emp_ident = :newcust
    where (emp_ident= : oldcust);

    update emp_works set emp_ident = :newcust
    where (emp_ident= : oldcust);

    update enquire set cust_ident = :newcust
    where (cust_ident= : oldcust);

    update orders_acc set cust_ident = :newcust
    where (cust_ident= : oldcust);


    update price_vote set reqcust_ident = :newcust
    where (reqcust_ident= : oldcust);

    update security set cust_ident = :newcust
    where (cust_ident= : oldcust);

    update banks set RECCUST_IDENT = :newcust
    where (RECCUST_IDENT= : oldcust);

    update import_banktrans set dbcust_ident = :newcust
    where (dbcust_ident= : oldcust);
    update import_banktrans set crcust_ident = :newcust
    where (crcust_ident= : oldcust);


    execute procedure UPD_RECPAYZ(:oldcust, :newcust);

    if (delete_oldcust = 1) then
      delete from customer
      where cust_id=:oldcust;
end ^
