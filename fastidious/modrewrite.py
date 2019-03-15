import inspect
import fastidious


def rewrite(module, classname, classcode, output) :
    cut = []
    add = None
    for name, obj in inspect.getmembers(module, inspect.isclass) :
        if issubclass(obj, fastidious.Parser) :
            l, n = inspect.getsourcelines(obj)
            cut.append((n-1, n+len(l)))
            if name == classname :
                add = n-1
    cut.sort(reverse=True)
    src = inspect.getsource(module).splitlines(True)
    for start, stop in cut :
        if start == add :
            src[start:stop] = classcode.splitlines(True)
        else :
            del src[start:stop]
    used = False
    drop = []
    for i, s in enumerate(src) :
        if "fastidious" in s :
            s = s.strip()
            if s == "import fastidious" or s.startswith("from fastidious import") :
                drop.append(i)
            else :
                used = True
    if not used :
        drop.sort(reverse=True)
        for i in drop :
            del src[i]
    output.writelines(src)
