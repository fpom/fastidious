import ast
import inspect
import fastidious


class GrepImports (ast.NodeVisitor):
    def __init__ (self, name="fastidious"):
        ast.NodeVisitor.__init__(self)
        self.mod = name
        self.names = set()
        self.imports = []
        self.used = False
    def visit_Import (self, node):
        for a in node.names :
            n = a.name.split(".", 1)[0]
            if n == self.mod:
                self.imports.append(node.lineno - 1)
                self.names.add(n)
                break
    def visit_ImportFrom (self, node) :
        if node.module :
            n = node.module.split(".", 1)[0]
            if n == self.mod :
                self.names.update(a.asname or a.name for a in node.names)
                self.imports.append(node.lineno - 1)
    def visit_Name (self, node):
        if node.id in self.names :
            self.used = True


def rewrite(module, classname, classcode, output):
    cls = classcode.splitlines(True)
    idx = 2 + cls.index('"""\n', 1)
    output.writelines(cls[:idx])
    del cls[:idx]
    cut = []
    add = None
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, fastidious.Parser):
            l, n = inspect.getsourcelines(obj)
            cut.append((n-1, n+len(l)))
            if name == classname:
                add = n-1
    cut.sort(reverse=True)
    src = inspect.getsource(module).splitlines(True)
    for start, stop in cut:
        if start == add:
            src[start:stop] = cls
        else:
            del src[start:stop]
    grep = GrepImports()
    grep.visit(ast.parse("".join(src)))
    if not grep.used :
        for i in reversed(grep.imports) :
            del src[i]
    output.writelines(src)
