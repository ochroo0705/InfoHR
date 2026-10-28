ALTER PROCEDURE CALC_WORKEDYEAR (DATE1 TIMESTAMP,
DATE2 TIMESTAMP,
PREV_YY INTEGER)
RETURNS (AGE INTEGER)
AS 
declare variable YY integer;
declare variable MM integer;
declare variable DD integer;
declare variable YY2 integer;
declare variable MM2 integer;
declare variable DD2 integer;
begin
  if (PREV_YY is null) then
    PREV_YY=0;
  YY=extract(year from :date1);
  MM=extract(month from :date1);
  DD=extract(day from :date1);
  YY2=extract(year from :date2);
  MM2=extract(month from :date2);
  DD2=extract(day from :date2);

  AGE=YY2-YY;
  if (MM>MM2) then
    AGE=AGE-1;
  else if (MM=MM2) then begin
    if (DD>DD2) then
      AGE=AGE-1;
  end
  if (AGE<0) then
    AGE=0;
  AGE=AGE+PREV_YY;
  suspend;
end ^
