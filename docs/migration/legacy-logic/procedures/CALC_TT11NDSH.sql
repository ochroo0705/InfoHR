ALTER PROCEDURE CALC_TT11NDSH (YY SMALLINT,
MM1 SMALLINT,
MM2 SMALLINT)
RETURNS (NDSH_SUM NUMERIC(15, 10))
AS 
declare variable COLCODE char(4);
declare variable TMPSUM numeric(15,10);
begin
  ndsh_sum=0;
  for select colcode from colnames
  where (colstatus in ('IEH','IEP','IES','IEU')) and (colnames_version_id = -1)
  into :colcode
  do begin
    select salsum from CALC_TT11NDSHCOL(:yy,:mm1,:mm2,:colcode)
    into :tmpsum;
    ndsh_sum=ndsh_sum+:tmpsum;
  end
  suspend;
end ^
