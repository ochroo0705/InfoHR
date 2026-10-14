ALTER PROCEDURE CALC_REPNAZG (YY SMALLINT,
BRANCHID INTEGER,
TTYPE VARCHAR(10) CHARACTER SET UTF8)
RETURNS (NAZG_TYPE VARCHAR(10) CHARACTER SET UTF8,
OCCUPATION_IDENT INTEGER,
BUDG_QTY INTEGER,
EXEC_QTY INTEGER)
AS 
begin
  for select Z.NAZG_TYPE,Z.OCCUPATION_IDENT,SUM(Z.QTY) from NAZG Z
  where (Z.rep_year=:yy) and ((:branchid is null) or ((:branchid is not null) and (Z.branch_ident=:branchid))) and ((:ttype is null) or ((:ttype is not null) and (Z.nazg_type=:ttype)))
  group by Z.NAZG_TYPE,Z.OCCUPATION_IDENT
  into :nazg_type,:occupation_ident,:budg_qty
  do begin
    if (nazg_type='Main') then begin
      select count(*) from employee e
      where (e.occupation_ident=:occupation_ident) and (((e.status='active') and (e.contract_emp='no')) or (e.status='elder'))
      into :exec_qty;
    end
    else begin
      select count(*) from employee e
      where (e.occupation_ident=:occupation_ident) and (e.contract_emp='yes')
      into :exec_qty;
    end
    suspend;
  end
end ^
