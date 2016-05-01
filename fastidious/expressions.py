import re
from types import UnboundMethodType, MethodType


class ExprMixin(object):
    last_id = 0
    def _attach_to(self, parser):
        m = UnboundMethodType(self, None, parser)
        if hasattr(self, "name"):
            setattr(parser, self.name, m)
            if not self.action and hasattr(parser, "on_{}".format(self.name)):
                self.action = "on_{}".format(self.name)
        # self._attach_children_to(parser)
        return m

    def _attach_children_to(self, parser):
        for name, value in self.__dict__:
            if isinstance(value, ExprMixin):
                parser

    def visit(self, func):
        func(self)
        [child.visit(func) for child in getattr(self, "exprs", [])]
        if hasattr(self, "expr"):
            getattr(self, "expr").visit(func)

    def debug(self, parser, message):
        if parser._debug:
            print("{}{} `{}`".format(parser._debug_indent * " ",
                                     message, parser.input[
                                         parser.pos:parser.pos+5]))

    @property
    def id(self):
        if not hasattr(self, "_id"):
            self._id = ExprMixin.last_id
            ExprMixin.last_id += 1
        return self._id

    def _indent(self, code, space):
        ind = " " * space * 4
        return ind + ("\n" + ind).join([l for l in code.splitlines()])

    def memoize(self, code):
        # I first memoized ALL expressions, but it was actually slower,
        # cache hit ratio was 1/30. Caching only rules has a cache hit ratio
        # of 1/7 and is ~1.3 faster. The test data is fastidious PEG grammar,
        # a real life datum :)
        if not isinstance(self, RuleExpr):
            return code
        pk = hash(self.as_grammar())
        return"""
start_pos_{2}= self.pos
if ({0}, start_pos_{2}) in self._p_memoized:
    result, self.pos = self._p_memoized[({0}, self.pos)]
else:
{1}
    self._p_memoized[({0}, start_pos_{2})] = result, self.pos
        """.format(
            pk,
            self._indent(code, 1),
            self.id,
        )



class AtomicExpr(object):
    """Marker class for atomic expressions"""


class Expression(object):
    def __init__(self, rule, pos, argname=None):
        self.argname = argname
        self.pos = pos
        self.rule = rule

    def method_name(self):
        return "_expr_{}_{}".format(self.rule.name, self.pos)


class RegexExpr(ExprMixin):
    def __init__(self, regexp, ignore=False):
        self.lit = regexp
        self.ignore = ignore
        self.re = re.compile(regexp)

    def __call__(self, parser):
        pass

    def as_grammar(self, atomic=False):
        return "~{}{}".format(repr(self.lit), self.ignore and "i" or "")

    def as_code(self, memoize=False, globals_=[]):
        globals_.append("regex=re.compile({})".format(repr(self.lit)))
        return """
# {0}
m = regex.match(self.p_suffix())
if m:
    result = self.p_suffix(m.end())
    self.pos += m.end()
else:
    result = False
    """.format(self.as_grammar())

class SeqExpr(ExprMixin):
    def __init__(self, *exprs):
        self.exprs = exprs

    def __call__(self, parser):
        self.debug(parser, "SeqExpr")
        parser._debug_indent += 1
        parser.p_save()
        results = []
        for expr in self.exprs:
            res = expr(parser)
            if res is False:
                parser.p_restore()
                parser._debug_indent -= 1
                return False
            results.append(res)
        parser._debug_indent -= 1
        parser.p_discard()
        return results

    def as_grammar(self, atomic=False):
        g = " ".join([e.as_grammar(True) for e in self.exprs])
        if atomic and len(self.exprs) > 1:
            return "( {} )".format(g)
        return g

    def as_code(self, memoize=False, globals_=[]):
        def expressions():
            exprs = []
            for i, expr in enumerate(self.exprs):
                expr_code = """
{0}
if result is False:
    results_{1} = False
    self.p_restore()
else:
    results_{1}.append(result)
                    """.format(expr.as_code(memoize), self.id).strip()
                exprs.append(self._indent(expr_code, i))
            return "\n".join(exprs)


        code = """
# {0}
self.p_save()
results_{1} = []
{2}
if results_{1} is not False:
    self.p_discard()
result = results_{1}
        """.format(
            self.as_grammar(),
            self.id,
            expressions()
        )
        if memoize:
            code = self.memoize(code.strip())
        return code.strip()


class ChoiceExpr(ExprMixin):
    def __init__(self, *exprs):
        self.exprs = exprs

    def __call__(self, parser):
        self.debug(parser, "ChoiceExpr")
        parser._debug_indent += 1
        parser.p_save()
        for expr in self.exprs:
            res = expr(parser)
            if res is not False:
                parser._debug_indent -= 1
                parser.p_discard()
                return res
        parser._debug_indent -= 1
        parser.p_restore()
        return False

    def as_grammar(self, atomic=False):
        g = " / ".join([e.as_grammar(True) for e in self.exprs])
        if atomic and len(self.exprs) > 1:
            return "( {} )".format(g)
        return g

    def as_code(self, memoize=False, globals_=[]):
        def expressions():
            exprs = []
            if len(self.exprs):
                for i, expr in enumerate(self.exprs):
                    expr_code = """
{}
if result is False:
                    """.format(expr.as_code(memoize)).strip()
                    exprs.append(self._indent(expr_code, i ))
                exprs.append(self._indent("pass", i+1))
            return "\n".join(exprs)

        code = """
# {1}
self.p_save()
result = False
{0}
if result is False:
    self.p_restore()
else:
    self.p_discard()
        """.format(
            expressions(),
            self.as_grammar()
        )
        if memoize:
            code = self.memoize(code.strip())
        return code.strip()


class AnyCharExpr(ExprMixin, AtomicExpr):
    def __call__(self, parser):
        self.debug(parser, "AnyCharExpr")
        parser.p_save()
        n = parser.p_next()
        if n is not None:
            parser.p_discard()
            return n
        parser.p_restore()
        return False

    def as_grammar(self, atomic=False):
        return "."

    def as_code(self, memoize=False, globals_=[]):
        code = """
# .
self.p_save()
n = self.p_next()
if n is not None:
    self.p_discard()
    result = n
else:
    self.p_restore()
    result = False
        """
        if memoize:
            code = self.memoize(code.strip())
        return code.strip()


class LiteralExpr(ExprMixin, AtomicExpr):
    def __init__(self, lit, ignore=False):
        self.lit = lit
        self.ignorecase = ignore

    def __call__(self, parser):
        self.debug(parser, "LiteralExpr `{}`".format(self.lit))
        if self.lit == "":
            return ""
        return parser.p_startswith(self.lit,
                                 self.ignorecase)

    def as_grammar(self, atomic=False):
        lit = self.lit.replace("\\", "\\\\")
        lit = lit.replace("\a", r"\a")
        lit = lit.replace("\b", r"\b")
        lit = lit.replace("\t", r"\t")
        lit = lit.replace("\n", r"\n")
        lit = lit.replace("\f", r"\f")
        lit = lit.replace("\r", r"\r")
        lit = lit.replace("\v", r"\v")
        if lit != '"':
            return '"{}"'.format(lit)
        return """'"'"""

    def as_code(self, memoize=False, globals_=[]):
        if self.lit == "":
            return "result = ''"
        code = """
# {2}
result = self.p_startswith({0}, {1})
        """.format(
            repr(self.lit),
            repr(self.ignorecase),
            self.as_grammar()
        )
        if memoize:
            code = self.memoize(code.strip())
        return code.strip()


class CharRangeExpr(ExprMixin, AtomicExpr):
    def __init__(self, chars):
        self.chars = chars

    def __call__(self, parser):
        self.debug(parser, "CharRangeExpr `{}`".format(self.chars))
        parser.p_save()
        n = parser.p_next()
        if n is not None and n in self.chars:
            parser.p_discard()
            return n
        parser.p_restore()
        return False

    def as_grammar(self, atomic=False):
        chars = self.chars.replace("0123456789", "0-9")
        chars = chars.replace("\t", r"\t")
        chars = chars.replace("\n", r"\n")
        chars = chars.replace("\r", r"\r")
        chars = chars.replace("abcdefghijklmnopqrstuvwxyz", "a-z")
        chars = chars.replace("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "A-Z")
        chars = chars.replace("0123456789", "0-9")
        return "[{}]".format(chars)

    def as_code(self, memoize=False, globals_=[]):
        code = """
# {0}
self.p_save()
n = self.p_next()
if n is not None and n in {1}:
    self.p_discard()
    result = n
else:
    self.p_restore()
    result = False
        """.format(
                self.as_grammar(),
                repr(self.chars),
            )
        if memoize:
            code = self.memoize(code.strip())
        return code.strip()


class OneOrMoreExpr(ExprMixin):
    def __init__(self, expr):
        self.expr = expr

    def __call__(self, parser):
        self.debug(parser, "OneOrMoreExpr")
        parser._debug_indent += 1
        parser.p_save()
        results = []
        while 42:
            r = self.expr(parser)
            if r is not False:
                results.append(r)
            else:
                break
        parser._debug_indent -= 1
        if not results:
            parser.p_restore()
            return False
        if isinstance(self.expr, (CharRangeExpr, AnyCharExpr)):
            results = "".join(results)
        parser.p_discard()
        return results

    def as_grammar(self, atomic=False):
        return "{}+".format(self.expr.as_grammar(True))

    def as_code(self, memoize=False, globals_=[]):
        if isinstance(self.expr, (CharRangeExpr, AnyCharExpr)):
            result_line = 'result = "".join(results_{})'.format(self.id)
        else:
            result_line = 'result = results_{}'.format(self.id)
        code = """
# {0}
self.p_save()
results_{3} = []
while 42:
{1}
    if result is not False:
        results_{3}.append(result)
    else:
        break
if not results_{3}:
    self.p_restore()
    result = False
else:
    self.p_discard()
    {2}
        """.format(
            self.as_grammar(),
            self._indent(self.expr.as_code(memoize), 1),
            result_line,
            self.id,
        )
        if memoize:
            code = self.memoize(code.strip())
        return code.strip()


class ZeroOrMoreExpr(ExprMixin):
    def __init__(self, expr):
        self.expr = expr

    def __call__(self, parser):
        self.debug(parser, "ZeroOrMoreExpr")
        parser._debug_indent += 1
        results = []
        while 42:
            r = self.expr(parser)
            if r is not False:
                results.append(r)
            else:
                break
        if isinstance(self.expr, (CharRangeExpr, AnyCharExpr)):
            results = "".join(results)
        parser._debug_indent -= 1
        return results

    def as_grammar(self, atomic=False):
        return "{}*".format(self.expr.as_grammar(True))

    def as_code(self, memoize=False, globals_=[]):
        if isinstance(self.expr, (CharRangeExpr, AnyCharExpr)):
            result_line = 'result = "".join(results_{})'.format(self.id)
        else:
            result_line = 'result = results_{}'.format(self.id)
        code = """
# {0}
results_{3} = []
while 42:
{1}
    if result is not False:
        results_{3}.append(result)
    else:
        break
{2}
        """.format(
            self.as_grammar(),
            self._indent(self.expr.as_code(memoize), 1),
            result_line,
            self.id,
        )
        if memoize:
            code = self.memoize(code.strip())
        return code.strip()


class RuleExpr(ExprMixin, AtomicExpr):
    def __init__(self, rulename):
        self.rulename = rulename

    def __call__(self, parser):
        self.debug(parser, "RuleExpr `{}`".format(self.rulename))
        rule_method = getattr(parser, self.rulename, None)
        if rule_method is None:
            parser.parse_error("Rule `%s` not found" % self.rulename)
        return rule_method()

    def as_grammar(self, atomic=False):
        return self.rulename

    def as_code(self, memoize=False, globals_=[]):
        code = "result = self.{}()".format(self.rulename)
        if memoize:
            code = self.memoize(code.strip())
        return code.strip()


class MaybeExpr(ExprMixin):
    def __init__(self, expr=None):
        self.expr = expr

    def __call__(self, parser):
        self.debug(parser, "MaybeExpr")
        parser._debug_indent += 1
        result = self.expr(parser)
        parser._debug_indent -= 1
        if result is False:
            return ""
        return result

    def as_grammar(self, atomic=False):
        return "{}?".format(self.expr.as_grammar(True))

    def as_code(self, memoize=False, globals_=[]):
        code = """
# {}
{}
result = "" if result is False else result
        """.format(self.as_grammar(), self.expr.as_code(memoize))
        if memoize:
            code = self.memoize(code.strip())
        return code.strip()


class FollowedBy(ExprMixin):
    def __init__(self, expr=None):
        self.expr = expr

    def __call__(self, parser):
        self.debug(parser, "FollowedBy")
        parser._debug_indent += 1
        parser.p_save()
        result = self.expr(parser) is not False
        parser.p_restore()
        parser._debug_indent -= 1
        return result

    def as_grammar(self, atomic=False):
        return "&{}".format(self.expr.as_grammar(True))

    def as_code(self, memoize=False, globals_=[]):
        code = """
# {1}
self.p_save()
{0}
result = result is not False
self.p_restore()
        """.format(
            self.expr.as_code(memoize),
            self.as_grammar(),
        )
        if memoize:
            code = self.memoize(code.strip())
        return code.strip()



class NotFollowedBy(ExprMixin):
    def __init__(self, expr=None):
        self.expr = expr

    def __call__(self, parser):
        self.debug(parser, "NotFollowedBy")
        parser._debug_indent += 1
        parser.p_save()
        result = self.expr(parser) is False and ""
        parser.p_restore()
        parser._debug_indent -= 1
        return result

    def as_grammar(self, atomic=False):
        return "!{}".format(self.expr.as_grammar(True))

    def as_code(self, memoize=False, globals_=[]):
        code = """
# {1}
self.p_save()
{0}
result = result is False and ""
self.p_restore()
        """.format(
            self.expr.as_code(memoize),
            self.as_grammar(),
        )
        if memoize:
            code = self.memoize(code.strip())
        return code.strip()


class LabeledExpr(ExprMixin, AtomicExpr):
    def __init__(self, name, expr, rulename=None):
        self.name = name
        self.expr = expr
        self.rulename = rulename

    def __call__(self, parser):
        self.debug(parser, "LabeledExpr `{}`".format(self.name))
        parser._debug_indent += 1
        rule = getattr(parser, self.rulename)
        result = self.expr(parser)
        rule.args_stack[-1][self.name] = result
        parser._debug_indent -= 1
        return result

    def as_grammar(self, atomic=False):
        return "{}:{}".format(self.name, self.expr.as_grammar(True))

    def as_code(self, memoize=False, globals_=[]):
        code = """
# {}
{}
self.args_stack[{}][-1][{}] = result
        """.format(
            self.as_grammar(),
            self.expr.as_code(memoize),
            repr(self.rulename),
            repr(self.name)
        )
        return code.strip()


class Rule(ExprMixin):
    def __init__(self, name, expr, action=None):
        self.name = name
        self.expr = expr
        self.action = action
        self.args_stack = []

    def __call__(self, parser):
        self.args_stack.append({})
        result = self.expr(parser)
        args = self.args_stack.pop()

        if result is not False:
            if self.action is not None:
                if isinstance(self.action, basestring):
                    if self.action.startswith("@"):
                        return args.get(self.action[1:])
                    action = getattr(parser, self.action)
                    return action(result, **args)
                return self.action(parser, result, **args)
            else:
                return result
        return False

    def _action(self):
        if self.action is not None:
            if isinstance(self.action, basestring):
                if self.action.startswith("@"):
                    return "result = args['{}']".format(self.action[1:])
                if self.action.strip() != "":
                    return "result = self.{}(result, **args)".format(
                        self.action
                    )
        return "pass"

    def as_method(self, parser):
        memoize =  parser.__memoize__
        debug = parser.__debug___
        globals_ = []
        if not self.action:
            default_action = "on_{}".format(self.name)
            if hasattr(parser, default_action):
                self.action = default_action

        code = """
    # {3}
    # -- self.p_debug("{0}")
    # -- self._debug_indent += 1
    self.args_stack.setdefault("{0}",[]).append(dict())
{1}
    args = self.args_stack["{0}"].pop()
    if result is not False:
        {2}
    # -- self._debug_indent -= 1
    return result
        """.format(self.name,
                   self._indent(self.expr.as_code(memoize, globals_), 1),
                   self._action(),
                   self.as_grammar()
                   )
        defline = "def new_method(self, {}):".format(", ".join(globals_))
        code = "\n".join([defline, code])
        if debug:
            code = code.replace("# -- ", "")
        code = code.strip()
        exec(code)
        code = code.replace("new_method", self.name)
        new_method._code = code  # noqa
        new_method.func_name = self.name  # noqa
        if isinstance(parser, type):
            meth = UnboundMethodType(new_method, None, parser)  # noqa
        else:
            meth = MethodType(new_method, parser, type(parser))  # noqa
        setattr(parser, self.name, meth)

    def as_grammar(self):
        if self.action == "on_{}".format(self.name):
            action = ""
        elif isinstance(self.action, basestring) and len(self.action.strip()):
            action = " {%s}" % self.action
        else:
            action = ""
        return "{} <- {}{}".format(
            self.name,
            self.expr.as_grammar(),
            action
        )
