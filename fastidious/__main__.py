import sys
import six
import argparse


from fastidious.parser import ParserMeta, Parser
from fastidious.compilers import gendot
from fastidious.modrewrite import rewrite


FASTIDIOUS_MAGIC = ["__grammar__", "__default__"]


def load_class(klass):
    module, classname = klass.rsplit(".", 1)
    mod = __import__(module, fromlist=classname)
    template = getattr(mod, classname)
    return mod, template, classname


def parser_from_template(tmpl):
    if issubclass(tmpl, Parser):
        return tmpl
    else:
        attrs = {}
        for k, v in tmpl.__dict__.items():
            if k.startswith("__") and k not in FASTIDIOUS_MAGIC:
                continue
            attrs[k] = v
        return ParserMeta("ThrowawayParser", (Parser,), attrs)


def load_parser(klass):
    return parser_from_template(load_class(klass)[1])


def generate(klass, executable, output):
    module, template, classname = load_class(klass)
    if not hasattr(template.p_compiler, "gen_py_code"):
        raise NotImplementedError(
            "%s's compiler doesn't expose gen_py_code capability" % template)

    if executable:
        output.write("#! /usr/bin/python\n")

    out = six.StringIO()
    template.p_compiler.gen_py_code(template, out)

    rewrite(module, classname, out.getvalue(), output)

    if executable:
        output.write("""
if __name__ == '__main__':
    import sys
    res = {name}.p_parse(" ".join(sys.argv[1:]))
    print(res)
""".format(name=classname))


def graph(klass):
    parser = load_parser(klass)
    dot = gendot(parser.__rules__[::-1])
    return dot


# pragma: nocover
if __name__ == "__main__":
    def _generate(args):
        generate(args.classname, args.executable, args.output)

    def _graph(args):
        print(graph(args.classname))

    # Global parser
    parser = argparse.ArgumentParser(
        prog="fastidious",
        description="Fastidious utils"
    )

    def _usage(args):
        parser.print_usage()

    parser.set_defaults(func=_usage)
    subparsers = parser.add_subparsers(title="subcommands")

    # generate subparser
    parser_generate = subparsers.add_parser(
        'generate',
        help="Generate a standalone parser")
    parser_generate.add_argument("--executable", "-e",
                                 default=False,
                                 action="store_true",
                                 help="Name of the parser class to generate")
    parser_generate.add_argument("--output", "-o",
                                 metavar="OUT",
                                 type=argparse.FileType("w"),
                                 default=sys.stdout,
                                 help="Write generated code to OUT (default stdout)")
    parser_generate.add_argument("classname",
                                 help="Name of the parser class to generate")
    parser_generate.set_defaults(func=_generate)

    # graph subparser
    parser_graph = subparsers.add_parser(
        'graph',
        help="generate a .dot representation of the parsing rules")
    parser_graph.add_argument('classname')
    parser_graph.set_defaults(func=_graph)

    # run the subcommand
    args = parser.parse_args()
    args.func(args)
