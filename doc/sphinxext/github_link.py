"""Necessary functions for sphinx.ext.linkcode to provide links to github."""

import inspect
import os
import subprocess
import sys
from operator import attrgetter
from pathlib import Path

REVISION_CMD = "git rev-parse --short HEAD"


def _get_git_revision():
    try:
        revision = subprocess.check_output(REVISION_CMD.split()).strip()
    except (subprocess.CalledProcessError, OSError):
        print("Failed to execute git to get revision")
        return None
    return revision.decode("utf-8")


def _linkcode_resolve(domain, info, package, url_fmt, revision):
    """Determine a link to online source for a class/method/function.

    This is called by sphinx.ext.linkcode

    An example with a long-untouched module that everyone has
    >>> _linkcode_resolve(
    ...     "py",
    ...     {"module": "tty", "fullname": "setraw"},
    ...     package="tty",
    ...     url_fmt="http://hg.python.org/cpython/file/{revision}/Lib/{package}/{path}#L{lineno}",
    ...     revision="xxxx",
    ... )
    'http://hg.python.org/cpython/file/xxxx/Lib/tty/tty.py#L18'
    """
    if revision is None:
        return
    if domain not in ("py", "pyx"):
        return
    if not info.get("module") or not info.get("fullname"):
        return

    class_name = info["fullname"].split(".")[0]
    module = __import__(info["module"], fromlist=[class_name])
    # For typed parameters, this will try to get uninitialized attributes
    # and fail
    try:
        obj = attrgetter(info["fullname"])(module)
    except AttributeError:
        return

    # Unwrap the object to get the correct source
    # file in case that is wrapped by a decorator
    obj = inspect.unwrap(obj)

    try:
        fn = inspect.getsourcefile(obj)
    except Exception:
        fn = None
    if not fn:
        try:
            fn = inspect.getsourcefile(sys.modules[obj.__module__])
        except Exception:
            fn = None
    if not fn:
        return

    # Don't include filenames from outside this package's tree
    if str(Path(__import__(package).__file__).parent) not in fn:
        return

    fn = os.path.relpath(fn, start=Path(__import__(package).__file__).parent)
    try:
        lineno = inspect.getsourcelines(obj)[1]
    except Exception:
        lineno = ""
    return url_fmt.format(
        revision=revision, package=package, path=fn, lineno=lineno
    )


def make_linkcode_resolve(domain, info):
    """Return a linkcode_resolve function for the given URL format.

    revision is a git commit reference (hash or name)

    package is the name of the root module of the package

    url_fmt is along the lines of ('https://github.com/USER/PROJECT/'
                                   'blob/{revision}/{package}/'
                                   '{path}#L{lineno}')

    See https://www.sphinx-doc.org/en/master/usage/extensions/linkcode.html
    """
    package = "nilearn"
    url_fmt = "https://github.com/nilearn/nilearn/blob/{revision}/{package}/{path}#L{lineno}"
    revision = _get_git_revision()
    return _linkcode_resolve(
        domain, info, revision=revision, package=package, url_fmt=url_fmt
    )
