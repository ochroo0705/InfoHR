CREATE TRIGGER HR_LEGALHOLIDAYS_BI FOR HR_LEGALHOLIDAYS 
ACTIVE BEFORE INSERT POSITION 0 
as
begin
  if (new.holiday_id is null) then
    new.holiday_id = gen_id(gen_hr_legalholidays_id,1);
end ^
