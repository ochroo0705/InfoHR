"""Firebird reserved words, for aliases that Django derives from field names (firebird3-foundation Task 11, R28).

Dialect 1 has no quoted identifiers, so a name that is a reserved word cannot be used as it is.
Django writes a many-to-many join as ``SELECT ... AS GROUP`` (the alias comes from the field
name), which Firebird rejects as "Token unknown". ``DatabaseOperations.quote_name`` maps every name
in ``RESERVED_WORDS`` to that name plus ``RESERVED_SUFFIX``.

Provenance (checked on 2026-11-04 against the installed Firebird 3.0 server, SQL dialect 1):

1. Start: the candidate list in the Task 11 brief. No installed package ships a reserved-word list
   (``firebird.driver`` and ``firebird.base`` do not).
2. Server probes: each word was prepared (not run) in four positions: as an alias
   (``select 1 as WORD from rdb$database``), as a column definition (``create table ... (WORD integer)``),
   as a table name, and as a qualified column reference (``select 1 from rdb$database t where t.WORD = 1``),
   which is the form Django emits. A word stays only when Firebird answers "Token unknown".
   MAXIMUM_SEGMENT was accepted and removed. A probe of about 120 further words found LOCALTIME and
   LOCALTIMESTAMP reserved; they were added.
3. Changelog cross-check: the installed file ``doc/sql.extensions/README.keywords.txt`` (Firebird 3.0
   install folder) lists keyword additions and removals for versions 1.0 to 3.0. Replaying it gives the
   words reserved after 3.0 (ignoring names with a ``$``). It showed 13 reserved words missing from the
   candidate list (REGR_*, STDDEV_POP, STDDEV_SAMP, VAR_POP, VAR_SAMP); they were added and probed.
4. Remaining gap: the changelog records only changes after the first release. The words reserved from
   the start (the InterBase 6 / Firebird 1.0 base set) are not listed there, and the Firebird 3.0 Language
   Reference (Appendix A) is not installed, so completeness cannot be proven here. A reserved word that
   this list lacks is not mangled, so Firebird rejects it loudly ("Token unknown") at DDL or query time.
   ``test_reserved_list_covers_firebird_changelog`` checks everything the changelog states.
5. ``RDB$RECORD_VERSION`` is in the changelog. It contains ``$`` and is a pseudo-column that this backend
   never produces as a name, so it is not in the list.
"""

RESERVED_WORDS: frozenset[str] = frozenset(
    """
    ADD ADMIN ALL ALTER AND ANY AS AT AVG BEGIN BETWEEN BIGINT BIT_LENGTH BLOB BOOLEAN BOTH BY CASE CAST
    CHAR CHARACTER CHARACTER_LENGTH CHAR_LENGTH CHECK CLOSE COLLATE COLUMN COMMIT CONNECT CONSTRAINT
    CORR COUNT COVAR_POP COVAR_SAMP CREATE CROSS CURRENT CURRENT_CONNECTION CURRENT_DATE CURRENT_ROLE
    CURRENT_TIME CURRENT_TIMESTAMP CURRENT_TRANSACTION CURRENT_USER CURSOR DATE DAY DEC DECIMAL DECLARE
    DEFAULT DELETE DELETING DETERMINISTIC DISCONNECT DISTINCT DOUBLE DROP ELSE END ESCAPE EXECUTE EXISTS
    EXTERNAL EXTRACT FALSE FETCH FILTER FLOAT FOR FOREIGN FROM FULL FUNCTION GDSCODE GLOBAL GRANT GROUP
    HAVING HOUR IN INDEX INNER INSENSITIVE INSERT INSERTING INT INTEGER INTO IS JOIN LEADING LEFT LIKE
    LOCALTIME LOCALTIMESTAMP LONG LOWER MAX MERGE MIN MINUTE MONTH NATIONAL NATURAL NCHAR NO NOT NULL
    NUMERIC OCTET_LENGTH OF OFFSET ON ONLY OPEN OR ORDER OUTER OVER PARAMETER PLAN POSITION POST_EVENT
    PRECISION PRIMARY PROCEDURE REAL RECORD_VERSION RECREATE RECURSIVE REFERENCES REGR_AVGX REGR_AVGY
    REGR_COUNT REGR_INTERCEPT REGR_R2 REGR_SLOPE REGR_SXX REGR_SXY REGR_SYY RELEASE RETURN
    RETURNING_VALUES RETURNS REVOKE RIGHT ROLLBACK ROW ROWS ROW_COUNT SAVEPOINT SCROLL SECOND SELECT
    SENSITIVE SET SIMILAR SMALLINT SOME SQLCODE SQLSTATE START STDDEV_POP STDDEV_SAMP SUM TABLE THEN
    TIME TIMESTAMP TO TRAILING TRIGGER TRIM TRUE UNION UNIQUE UNKNOWN UPDATE UPDATING UPPER USER USING
    VALUE VALUES VARCHAR VARIABLE VARYING VAR_POP VAR_SAMP VIEW WHEN WHERE WHILE WITH YEAR
    """.split()
)
RESERVED_SUFFIX: str = "_RW"
# Rule R30 (quote_name, operations.py): a name that does not start with A-Z is prefixed with "U",
# after truncation to 30 characters, so the result is at most 31 characters. Firebird rejects an
# identifier that starts with a digit or underscore; Django's COUNT alias "__count" is the case
# that needs it (it becomes "U__COUNT"). Names are upper-cased before the check.
