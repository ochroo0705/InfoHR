ALTER PROCEDURE CALC_COLCODE RETURNS (COLCODE VARCHAR(100) CHARACTER SET UTF8)
AS 
declare variable COL char(4);
begin
  colcode='';
  for Select ColCode from ColNames
  where ColStatus in('PAY','IOP','IOS','IOH','IOE','IOU') and (COLNAMES_VERSION_ID = -1)
  into :col
  do begin
    if (colcode='') then
      colcode=col;
    else
      colcode=colcode||'+'||:col;
  end
  suspend;
end ^
