ALTER PROCEDURE CALC_NDSHC1C2 (DATE1 TIMESTAMP,
DATE2 TIMESTAMP)
RETURNS (NDSH_SUM1 NUMERIC(15, 2),
NDSH_SUM2 NUMERIC(15, 2),
NDSH_SUM3 NUMERIC(15, 2),
NDSH_SUM4 NUMERIC(15, 2))
AS 
declare variable REC_ACC char(12); /* HDSH-iin avlagiin dans */
declare variable PAY_ACC char(12); /* HDSH-iin uglugiin dans */
declare variable AMOUNT numeric(15,10);
declare variable AMOUNT2 numeric(15,10);
begin
  IF (:DATE1 IS NULL) THEN
    SELECT DAT FROM CONVTODATE(100,1,1,3) INTO :DATE1;
  IF (:DATE2 IS NULL) THEN
    SELECT DAT FROM CONVTODATE(5941,1,1,3) INTO :DATE2;

  /*$$IBE$$ select cast(expression as char(12)) from ndsh_config
  where (rownum=1)
  into :rec_acc;
  select cast(expression as char(12)) from ndsh_config
  where (rownum=2)
  into :pay_acc;

  ndsh_sum1=0;
  ndsh_sum2=0;
  ndsh_sum3=0;
  ndsh_sum4=0;
   $$IBE$$*/ /* C1 iluu */ /*$$IBE$$ 
  select c.dbc1 from calcbalance(:rec_acc,:date1,null,1) c
  into :ndsh_sum1;
  if (ndsh_sum1 is null) then ndsh_sum1=0;
   $$IBE$$*/ /* C1 dutuu */ /*$$IBE$$ 
  select c.crc1 from calcbalance(:pay_acc,:date1,null,1) c
  into :ndsh_sum2;
  if (ndsh_sum2 is null) then ndsh_sum2=0;
   $$IBE$$*/ /* C2 iluu */ /*$$IBE$$ 
  select c.dbc1 from calcbalance(:rec_acc,:date2,null,1) c
  into :ndsh_sum3;
  if (ndsh_sum3 is null) then ndsh_sum3=0;
   $$IBE$$*/ /* C2 dutuu */ /*$$IBE$$ 
  select c.crc1 from calcbalance(:pay_acc,:date2,null,1) c
  into :ndsh_sum4;
  if (ndsh_sum4 is null) then ndsh_sum4=0;
  suspend;
 $$IBE$$*/

 select ND7_ACC from sub_information
  into :pay_acc;
  amount = 0;
  ndsh_sum1=0;
  ndsh_sum2=0;
  ndsh_sum3=0;
  ndsh_sum4=0;

  select c.dbc1,c.crc1 from calcbalance(:pay_acc,:date1,null,1) c
  into :amount,:amount2;
  if (amount is null) then amount=0;
  if (amount2 is null) then amount2=0;

  if (amount2<0) then /* C1 iluu */
    ndsh_sum1 = abs(amount2);
  else
    ndsh_sum2 = amount2; /* C1 dutuu */


  amount = 0;   amount2 = 0;
  /* C2 iluu */
  select dbc1, c.crc1 from calcbalance(:pay_acc,:date2,null,1) c
  into :amount,:amount2;
  if (amount is null) then amount=0;
  if (amount2 is null) then amount2=0;

  if (amount2<0) then /* C2 iluu */
    ndsh_sum3 = abs(amount2);
  else
    ndsh_sum4 = amount2; /* C2 dutuu */

  suspend;

end ^
