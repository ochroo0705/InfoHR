"""A sqlglot dialect for Firebird 3 (SQL dialect 1), as far as the SQL checker needs it.

Input: Firebird's own row limits (SELECT FIRST n SKIP m, trailing ROWS n / ROWS m TO n) and, for
convenience, the standard FETCH FIRST n ROWS ONLY and OFFSET m ROWS forms.
Output: only Firebird 3 spellings. A row limit is always written as SELECT FIRST n [SKIP m];
FETCH and OFFSET are never written. SUBSTRING uses FROM/FOR and LENGTH is written CHAR_LENGTH.

Plain Python on top of sqlglot. No Django, no HR imports.
"""

from __future__ import annotations

import typing as t

from sqlglot import exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.errors import ParseError, UnsupportedError
from sqlglot.generator import Generator
from sqlglot.parser import Parser
from sqlglot.tokenizer_core import TokenType


class FirebirdParser(Parser):
    # ROWS is reserved in Firebird and starts the trailing row clause, so it must never be read as an alias.
    ID_VAR_TOKENS: t.ClassVar[set[TokenType]] = Parser.ID_VAR_TOKENS - {TokenType.ROWS}
    TABLE_ALIAS_TOKENS: t.ClassVar[set[TokenType]] = Parser.TABLE_ALIAS_TOKENS - {TokenType.ROWS}
    ALIAS_TOKENS: t.ClassVar = ID_VAR_TOKENS

    def _parse_limit(
        self,
        this: exp.Expr | None = None,
        top: bool = False,
        skip_limit_token: bool = False,
    ) -> exp.Expr | None:
        if top:
            # SELECT FIRST n [SKIP m]: sqlglot's TOP slot. Stored as Limit(expression=n, offset=m).
            if not self._match_text_seq("FIRST"):
                return None
            count = self._parse_row_count("FIRST")
            skip = self._parse_row_count("SKIP") if self._match_text_seq("SKIP") else None
            return self.expression(exp.Limit(expression=count, offset=skip))
        return super()._parse_limit(this=this, top=top, skip_limit_token=skip_limit_token)

    def _parse_query_modifiers(self, this: t.Any) -> t.Any:
        this = super()._parse_query_modifiers(this)
        if isinstance(this, (exp.Select, exp.SetOperation)) and self._match_text_seq("ROWS"):
            if this.args.get("limit") or this.args.get("offset"):
                raise ParseError("Found more than one row limit; use one FIRST, ROWS or FETCH clause")
            first = self._parse_row_count("ROWS")
            if self._match_text_seq("TO"):
                last = self._parse_row_count("TO")
                start, end = int(first.name), int(last.name)
                if start < 1 or end < start:
                    raise ParseError("ROWS needs 1 <= m <= n, for example ROWS 2 TO 5")
                this.set("limit", exp.Limit(expression=exp.Literal.number(end - start + 1)))
                if start > 1:
                    this.set("offset", exp.Offset(expression=exp.Literal.number(start - 1)))
            else:
                if int(first.name) < 1:
                    raise ParseError("ROWS needs a number of at least 1, for example ROWS 5")
                this.set("limit", exp.Limit(expression=first))
        return this

    def _parse_row_count(self, word: str) -> exp.Expr:
        token = self._curr
        if token is None or token.token_type != TokenType.NUMBER or not token.text.isdigit():
            raise ParseError(f"{word} must be followed by a whole number, for example {word} 5")
        self._advance()
        return exp.Literal.number(token.text)


class FirebirdGenerator(Generator):
    def select_sql(self, expression: exp.Select) -> str:
        limit = expression.args.get("limit")
        offset = expression.args.get("offset")
        if limit is None and offset is None:
            return super().select_sql(expression)

        window = self._row_window(limit, offset)
        bare = expression.copy()
        bare.set("limit", None)
        bare.set("offset", None)
        sql = super().select_sql(bare)
        if not sql.startswith("SELECT"):
            raise UnsupportedError("Firebird row limit: unexpected SELECT text")
        return f"SELECT{window}{sql[len('SELECT') :]}"

    def query_modifiers(self, expression: exp.Expr, *sqls: str) -> str:
        if isinstance(expression, exp.SetOperation) and (
            expression.args.get("limit") or expression.args.get("offset")
        ):
            raise UnsupportedError(
                "Firebird cannot apply a row limit after UNION; put the limit inside one SELECT"
            )
        return super().query_modifiers(expression, *sqls)

    def substring_sql(self, expression: exp.Substring) -> str:
        this = self.sql(expression, "this")
        start = self.sql(expression, "start")
        length = self.sql(expression, "length")
        if not start:
            raise UnsupportedError("Firebird SUBSTRING needs a start position")
        length_sql = f" FOR {length}" if length else ""
        return f"SUBSTRING({this} FROM {start}{length_sql})"

    def length_sql(self, expression: exp.Length) -> str:
        return f"CHAR_LENGTH({self.sql(expression, 'this')})"

    def currentdate_sql(self, expression: exp.CurrentDate) -> str:
        # CURRENT_DATE is refused by Firebird 3 SQL dialect 1 ("does not support reference to DATE datatype"). In
        # dialect 1 a date is a TIMESTAMP at midnight, so today's date is written as midnight today. CURRENT_TIMESTAMP
        # is not midnight: a leave that ends today would end before the current time and drop out of "on leave today".
        # Checked on Firebird 3 (dialect 1): CAST('TODAY' AS TIMESTAMP) = today 00:00, and it works in WHERE, SELECT,
        # DATEDIFF, EXTRACT, CTEs and subqueries. CURRENT_TIMESTAMP typed by the model is rendered unchanged.
        return "CAST('TODAY' AS TIMESTAMP)"

    def currenttimestamp_sql(self, expression: exp.CurrentTimestamp) -> str:
        # Firebird 3 takes CURRENT_TIMESTAMP with no parentheses; sqlglot would write CURRENT_TIMESTAMP(), which
        # Firebird refuses (Dynamic SQL Error). A real timestamp, so it is not turned into midnight.
        return "CURRENT_TIMESTAMP"

    def _row_window(self, limit: exp.Expr | None, offset: exp.Expr | None) -> str:
        count: exp.Expr | None = None
        skip: exp.Expr | None = None
        if isinstance(limit, exp.Fetch):
            self._reject_row_options(limit)
            fetch_count = limit.args.get("count")
            count = exp.Literal.number(1) if fetch_count is None else fetch_count
        elif isinstance(limit, exp.Limit):
            self._reject_row_options(limit)
            count = limit.expression
            skip = limit.args.get("offset")
        elif limit is not None:
            raise UnsupportedError(f"Firebird cannot render {limit.key} as a row limit")

        if isinstance(offset, exp.Offset):
            if skip is not None:
                raise UnsupportedError("Firebird allows one SKIP; use either OFFSET or a second SKIP")
            skip = offset.expression
        elif offset is not None:
            raise UnsupportedError(f"Firebird cannot render {offset.key} as a row offset")

        window = ""
        if count is not None:
            window += f" FIRST {self._row_count(count)}"
        if skip is not None:
            window += f" SKIP {self._row_count(skip)}"
        return window

    def _reject_row_options(self, node: exp.Expr) -> None:
        options = node.args.get("limit_options")
        if isinstance(options, exp.LimitOptions) and (
            options.args.get("percent") or options.args.get("with_ties")
        ):
            raise UnsupportedError("Firebird has no PERCENT or WITH TIES row limit")
        if node.args.get("expressions"):
            raise UnsupportedError("Firebird has no LIMIT ... BY row limit")

    def _row_count(self, value: exp.Expr | None) -> str:
        if not isinstance(value, exp.Literal) or not value.is_int:
            raise UnsupportedError("Firebird row counts must be whole numbers")
        return value.name


class Firebird(Dialect):
    Parser = FirebirdParser
    Generator = FirebirdGenerator
