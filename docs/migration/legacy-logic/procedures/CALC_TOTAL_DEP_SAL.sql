ALTER PROCEDURE CALC_TOTAL_DEP_SAL (Y1 SMALLINT,
M1 SMALLINT,
Y2 SMALLINT,
M2 SMALLINT,
OCCUP_ID INTEGER,
DEP_ID INTEGER)
RETURNS (SUMB01 NUMERIC(15, 2),
SUMB02 NUMERIC(15, 2),
SUMB03 NUMERIC(15, 2),
SUMB04 NUMERIC(15, 2),
SUMB05 NUMERIC(15, 2),
SUMB06 NUMERIC(15, 2),
SUMB07 NUMERIC(15, 2),
SUMB08 NUMERIC(15, 2),
SUMB09 NUMERIC(15, 2),
SUMB10 NUMERIC(15, 2),
SUMB11 NUMERIC(15, 2),
SUMB12 NUMERIC(15, 2),
SUMB13 NUMERIC(15, 2),
SUMB14 NUMERIC(15, 2),
SUMB15 NUMERIC(15, 2),
SUMB16 NUMERIC(15, 2),
SUMB17 NUMERIC(15, 2),
SUMB18 NUMERIC(15, 2),
SUMB19 NUMERIC(15, 2),
SUMB20 NUMERIC(15, 2),
SUMB21 NUMERIC(15, 2),
SUMB22 NUMERIC(15, 2),
SUMB23 NUMERIC(15, 2),
SUMB24 NUMERIC(15, 2),
SUMB25 NUMERIC(15, 2),
SUMB26 NUMERIC(15, 2),
SUMB27 NUMERIC(15, 2),
SUMB28 NUMERIC(15, 2),
SUMB29 NUMERIC(15, 2),
SUMB30 NUMERIC(15, 2),
SUMB31 NUMERIC(15, 2),
SUMB32 NUMERIC(15, 2),
SUMB33 NUMERIC(15, 2),
SUMB34 NUMERIC(15, 2),
SUMB35 NUMERIC(15, 2),
SUMB36 NUMERIC(15, 2),
SUMB37 NUMERIC(15, 2),
SUMB38 NUMERIC(15, 2),
SUMB39 NUMERIC(15, 2),
SUMB40 NUMERIC(15, 2),
SUMB41 NUMERIC(15, 2),
SUMB42 NUMERIC(15, 2),
SUMB43 NUMERIC(15, 2),
SUMB44 NUMERIC(15, 2),
SUMB45 NUMERIC(15, 2),
SUMB46 NUMERIC(15, 2),
SUMB47 NUMERIC(15, 2),
SUMB48 NUMERIC(15, 2),
SUMB49 NUMERIC(15, 2),
SUMB50 NUMERIC(15, 2),
SUMB51 NUMERIC(15, 2),
SUMB52 NUMERIC(15, 2),
SUMB53 NUMERIC(15, 2),
SUMB54 NUMERIC(15, 2),
SUMB55 NUMERIC(15, 2),
SUMB56 NUMERIC(15, 2),
SUMB57 NUMERIC(15, 2),
SUMB58 NUMERIC(15, 2),
SUMB59 NUMERIC(15, 2),
SUMB60 NUMERIC(15, 2),
SUMB61 NUMERIC(15, 2),
SUMB62 NUMERIC(15, 2),
SUMB63 NUMERIC(15, 2),
SUMB64 NUMERIC(15, 2),
SUMB65 NUMERIC(15, 2),
SUMB66 NUMERIC(15, 2),
SUMB67 NUMERIC(15, 2),
SUMB68 NUMERIC(15, 2),
SUMB69 NUMERIC(15, 2),
SUMB70 NUMERIC(15, 2),
SUMB71 NUMERIC(15, 2),
SUMB72 NUMERIC(15, 2),
SUMB73 NUMERIC(15, 2),
SUMB74 NUMERIC(15, 2),
SUMB75 NUMERIC(15, 2),
SUMB76 NUMERIC(15, 2),
SUMB77 NUMERIC(15, 2),
SUMB78 NUMERIC(15, 2),
SUMB79 NUMERIC(15, 2),
SUMB80 NUMERIC(15, 2),
SUMB81 NUMERIC(15, 2),
SUMB82 NUMERIC(15, 2),
SUMB83 NUMERIC(15, 2),
SUMB84 NUMERIC(15, 2),
SUMB85 NUMERIC(15, 2),
SUMB86 NUMERIC(15, 2),
SUMB87 NUMERIC(15, 2),
SUMB88 NUMERIC(15, 2),
SUMB89 NUMERIC(15, 2),
SUMB90 NUMERIC(15, 2),
SUMB91 NUMERIC(15, 2),
SUMB92 NUMERIC(15, 2),
SUMB93 NUMERIC(15, 2),
SUMB94 NUMERIC(15, 2),
SUMB95 NUMERIC(15, 2),
SUMB96 NUMERIC(15, 2),
SUMB97 NUMERIC(15, 2),
SUMB98 NUMERIC(15, 2),
SUMB99 NUMERIC(15, 2),
SUMB100 NUMERIC(15, 2))
AS 
begin
  Select
         Sum(b01),Sum(b02),Sum(b03),Sum(b04),Sum(b05),Sum(b06),Sum(b07),Sum(b08),Sum(b09),Sum(b10),Sum(b11),Sum(b12),
         Sum(b13),Sum(b14),Sum(b15),Sum(b16),Sum(b17),Sum(b18),Sum(b19),Sum(b20),Sum(b21),Sum(b22),Sum(b23),Sum(b24),
         Sum(b25),Sum(b26),Sum(b27),Sum(b28),Sum(b29),Sum(b30),Sum(b31),Sum(b32),Sum(b33),Sum(b34),Sum(b35),Sum(b36),
         Sum(b37),Sum(b38),Sum(b39),Sum(b40),Sum(b41),Sum(b42),Sum(b43),Sum(b44),Sum(b45),Sum(b46),Sum(b47),Sum(b48),
         Sum(b49),
         Sum(b50),Sum(b51),Sum(b52),Sum(b53),Sum(b54),Sum(b55),Sum(b56),Sum(b57),Sum(b58),Sum(b59),
         Sum(B60),Sum(B61),Sum(B62),Sum(B63),Sum(B64),Sum(B65),Sum(B66),Sum(B67),Sum(B68),Sum(B69),
         Sum(B70),Sum(B71),Sum(B72),Sum(B73),Sum(B74),Sum(B75),Sum(B76),Sum(B77),Sum(B78),Sum(B79),
         Sum(B80),Sum(B81),Sum(B82),Sum(B83),Sum(B84),Sum(B85),Sum(B86),Sum(B87),Sum(B88),Sum(B89),
         Sum(B90),Sum(B91),Sum(B92),Sum(B93),Sum(B94),Sum(B95),Sum(B96),Sum(B97),Sum(B98),Sum(B99),Sum(B100)
  from MonthSalary M, (Customer C
  Left join Employee E on (E.Employee_ID=C.Employee_Ident)
  Left join Occupation O on (E.Occupation_Ident=O.Occupation_ID))
  where (M.Emp_Ident=C.Cust_ID) and (M.dep_ident=:dep_id) and (((:occup_id is null) and (E.occupation_ident is null)) or (E.occupation_ident=:occup_id))  and
  (M.MYear*12+M.MMonth>=12 * :Y1 + :M1) and
  (M.MYear*12+M.MMonth<12 * :Y2 + :M2) and
  ((b01>0) or (b02>0) or (b03>0) or (b04>0) or (b05>0) or (b06>0) or (b07>0) or (b08>0) or (b09>0) or (b10>0) or
   (b11>0) or (b12>0) or (b13>0) or (b14>0) or (b15>0) or (b16>0) or (b17>0) or (b18>0) or (b19>0) or (b20>0) or
   (b21>0) or (b22>0) or (b23>0) or (b24>0) or (b25>0) or (b26>0) or (b27>0) or (b28>0) or (b29>0) or (b30>0) or
   (b31>0) or (b32>0) or (b33>0) or (b34>0) or (b35>0) or (b36>0) or (b37>0) or (b38>0) or (b39>0) or (b40>0) or
   (b41>0) or (b42>0) or (b43>0) or (b44>0) or (b45>0) or (b46>0) or (b47>0) or (b48>0) or (b49>0) or
   (b50>0) or (b51>0) or (b52>0) or (b53>0) or (b54>0) or (b55>0) or (b56>0) or (b57>0) or (b58>0) or (b59>0) or
   (b60>0) or (B61>0) or (B62>0) or (B63>0) or (B64>0) or (B65>0) or (B66>0) or (B67>0) or (B68>0) or (B69>0) or
   (B70>0) or (B71>0) or (B72>0) or (B73>0) or (B74>0) or (B75>0) or (B76>0) or (B77>0) or (B78>0) or (B79>0) or
   (B80>0) or (B81>0) or (B82>0) or (B83>0) or (B84>0) or (B85>0) or (B86>0) or (B87>0) or (B88>0) or (B89>0) or
   (B90>0) or (B91>0) or (B92>0) or (B93>0) or (B94>0) or (B95>0) or (B96>0) or (B97>0) or (B98>0) or (B99>0) or
   (B100>0))
  into :sumb01,:sumb02,:sumb03,:sumb04,:sumb05,:sumb06,:sumb07,:sumb08,:sumb09,:sumb10,
       :sumb11,:sumb12,:sumb13,:sumb14,:sumb15,:sumb16,:sumb17,:sumb18,:sumb19,:sumb20,
       :sumb21,:sumb22,:sumb23,:sumb24,:sumb25,:sumb26,:sumb27,:sumb28,:sumb29,:sumb30,
       :sumb31,:sumb32,:sumb33,:sumb34,:sumb35,:sumb36,:sumb37,:sumb38,:sumb39,:sumb40,
       :sumb41,:sumb42,:sumb43,:sumb44,:sumb45,:sumb46,:sumb47,:sumb48,:sumb49,
       :sumb50,:sumb51,:sumb52,:sumb53,:sumb54,:sumb55,:sumb56,:sumb57,:sumb58,:sumb59,
       :sumB60,:sumB61,:sumB62,:sumB63,:sumB64,:sumB65,:sumB66,:sumB67,:sumB68,:sumB69,
       :sumB70,:sumB71,:sumB72,:sumB73,:sumB74,:sumB75,:sumB76,:sumB77,:sumB78,:sumB79,
       :sumB80,:sumB81,:sumB82,:sumB83,:sumB84,:sumB85,:sumB86,:sumB87,:sumB88,:sumB89,
       :sumB90,:sumB91,:sumB92,:sumB93,:sumB94,:sumB95,:sumB96,:sumB97,:sumB98,:sumB99,
       :sumb100;
  if (Sumb01 is null) then Sumb01=0;
  if (Sumb02 is null) then Sumb02=0;
  if (Sumb03 is null) then Sumb03=0;
  if (Sumb04 is null) then Sumb04=0;
  if (Sumb05 is null) then Sumb05=0;
  if (Sumb06 is null) then Sumb06=0;
  if (Sumb07 is null) then Sumb07=0;
  if (Sumb08 is null) then Sumb08=0;
  if (Sumb09 is null) then Sumb09=0;
  if (Sumb10 is null) then Sumb10=0;
  if (Sumb11 is null) then Sumb11=0;
  if (Sumb12 is null) then Sumb12=0;
  if (Sumb13 is null) then Sumb13=0;
  if (Sumb14 is null) then Sumb14=0;
  if (Sumb15 is null) then Sumb15=0;
  if (Sumb16 is null) then Sumb16=0;
  if (Sumb17 is null) then Sumb17=0;
  if (Sumb18 is null) then Sumb18=0;
  if (Sumb19 is null) then Sumb19=0;
  if (Sumb20 is null) then Sumb20=0;
  if (Sumb21 is null) then Sumb21=0;
  if (Sumb22 is null) then Sumb22=0;
  if (Sumb23 is null) then Sumb23=0;
  if (Sumb24 is null) then Sumb24=0;
  if (Sumb25 is null) then Sumb25=0;
  if (Sumb26 is null) then Sumb26=0;
  if (Sumb27 is null) then Sumb27=0;
  if (Sumb28 is null) then Sumb28=0;
  if (Sumb29 is null) then Sumb29=0;
  if (Sumb30 is null) then Sumb30=0;
  if (Sumb31 is null) then Sumb31=0;
  if (Sumb32 is null) then Sumb32=0;
  if (Sumb33 is null) then Sumb33=0;
  if (Sumb34 is null) then Sumb34=0;
  if (Sumb35 is null) then Sumb35=0;
  if (Sumb36 is null) then Sumb36=0;
  if (Sumb37 is null) then Sumb37=0;
  if (Sumb38 is null) then Sumb38=0;
  if (Sumb39 is null) then Sumb39=0;
  if (Sumb40 is null) then Sumb40=0;
  if (Sumb41 is null) then Sumb41=0;
  if (Sumb42 is null) then Sumb42=0;
  if (Sumb43 is null) then Sumb43=0;
  if (Sumb44 is null) then Sumb44=0;
  if (Sumb45 is null) then Sumb45=0;
  if (Sumb46 is null) then Sumb46=0;
  if (Sumb47 is null) then Sumb47=0;
  if (Sumb48 is null) then Sumb48=0;
  if (Sumb49 is null) then Sumb49=0;
  if (Sumb50 is null) then Sumb50=0;
  if (Sumb51 is null) then Sumb51=0;
  if (Sumb52 is null) then Sumb52=0;
  if (Sumb53 is null) then Sumb53=0;
  if (Sumb54 is null) then Sumb54=0;
  if (Sumb55 is null) then Sumb55=0;
  if (Sumb56 is null) then Sumb56=0;
  if (Sumb57 is null) then Sumb57=0;
  if (Sumb58 is null) then Sumb58=0;
  if (Sumb59 is null) then Sumb59=0;
  if (SumB60 is null) then SumB60=0;
  if (SumB61 is null) then SumB61=0;
  if (SumB62 is null) then SumB62=0;
  if (SumB63 is null) then SumB63=0;
  if (SumB64 is null) then SumB64=0;
  if (SumB65 is null) then SumB65=0;
  if (SumB66 is null) then SumB66=0;
  if (SumB67 is null) then SumB67=0;
  if (SumB68 is null) then SumB68=0;
  if (SumB69 is null) then SumB69=0;
  if (SumB70 is null) then SumB70=0;
  if (SumB71 is null) then SumB71=0;
  if (SumB72 is null) then SumB72=0;
  if (SumB73 is null) then SumB73=0;
  if (SumB74 is null) then SumB74=0;
  if (SumB75 is null) then SumB75=0;
  if (SumB76 is null) then SumB76=0;
  if (SumB77 is null) then SumB77=0;
  if (SumB78 is null) then SumB78=0;
  if (SumB79 is null) then SumB79=0;
  if (SumB80 is null) then SumB80=0;
  if (SumB81 is null) then SumB81=0;
  if (SumB82 is null) then SumB82=0;
  if (SumB83 is null) then SumB83=0;
  if (SumB84 is null) then SumB84=0;
  if (SumB85 is null) then SumB85=0;
  if (SumB86 is null) then SumB86=0;
  if (SumB87 is null) then SumB87=0;
  if (SumB88 is null) then SumB88=0;
  if (SumB89 is null) then SumB89=0;
  if (SumB90 is null) then SumB90=0;
  if (SumB91 is null) then SumB91=0;
  if (SumB92 is null) then SumB92=0;
  if (SumB93 is null) then SumB93=0;
  if (SumB94 is null) then SumB94=0;
  if (SumB95 is null) then SumB95=0;
  if (SumB96 is null) then SumB96=0;
  if (SumB97 is null) then SumB97=0;
  if (SumB98 is null) then SumB98=0;
  if (SumB99 is null) then SumB99=0;
  if (SumB100 is null) then SumB100=0;
  suspend;
end ^
