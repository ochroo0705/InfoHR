ALTER PROCEDURE INS_INSURCOL (INSUR_ID INTEGER)
AS 
declare variable COLID integer;
declare variable COLEXPR varchar(100);
declare variable CC integer;
begin
  for select col_id,colexpr from colnames
  where  (colnames_version_id = -1)
  into :colid,:colexpr
  do begin
    select col_id from insur_colnames
    where (insurtype_ident=:insur_id) and (col_id=:colid)
    rows 1
    into :cc;
    if (cc is  null) then
      cc=0;
    if (:cc=0) then
      insert into insur_colnames(INSURTYPE_IDENT,COL_ID,COLEXPR,WITH_JOURNAL)
      values (:insur_id,:colid,:colexpr,1);
  end
end ^
