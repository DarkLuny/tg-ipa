# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Reads the top-level `__id__`, `__name__`, ... assignments of a `.plugin` file
# without executing it.  The Android SDK uses `ast`; the same approach is used
# here because the embedded interpreter is CPython and `ast` is part of it.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import ast
import io
import os
import tokenize
import traceback

MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_STATEMENT_CHARS = 64 * 1024

ALLOWED_KEYS = {
    "__id__", "__name__",
    "__description__", "__author__",
    "__version__", "__icon__",
    "__min_version__", "__requirements__",
    "__app_version__", "__sdk_version__",
    "__category__",
}


def _metadata_statements(source):
    lines = source.splitlines(keepends=True)
    indent = 0
    start = None
    line_start = True
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.INDENT:
            indent += 1
            continue
        if token.type == tokenize.DEDENT:
            indent -= 1
            continue
        if token.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
            if start is not None:
                (start_row, start_col), (end_row, end_col) = start, token.end
                if end_row == start_row:
                    text = lines[start_row - 1][start_col:end_col]
                else:
                    text = (lines[start_row - 1][start_col:]
                            + "".join(lines[start_row:end_row - 1])
                            + lines[end_row - 1][:end_col])
                if len(text) <= MAX_STATEMENT_CHARS:
                    yield text
                start = None
            line_start = True
            continue
        if token.type in (tokenize.NL, tokenize.COMMENT):
            continue
        if line_start and indent == 0 and token.type == tokenize.NAME and token.string in ALLOWED_KEYS:
            start = token.start
        line_start = False


def get_metadata(file_path):
    metadata = {}
    try:
        if os.path.getsize(file_path) > MAX_SOURCE_BYTES:
            raise ValueError("file is too large")
        with open(file_path, "r", encoding="utf-8") as handle:
            source = handle.read()

        for statement in _metadata_statements(source):
            try:
                tree = ast.parse(statement, filename=file_path)
            except (SyntaxError, ValueError, MemoryError, RecursionError):
                continue
            for node in ast.iter_child_nodes(tree):
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ALLOWED_KEYS:
                        key = target.id[2:-2]
                        if isinstance(node.value, ast.Constant):
                            metadata[key] = node.value.value
                        elif isinstance(node.value, ast.List):
                            metadata[key] = ",".join(
                                str(element.value)
                                for element in node.value.elts
                                if isinstance(element, ast.Constant)
                            )
    except Exception:
        raise Exception("Failed to parse metadata: %s" % traceback.format_exc())

    if "min_version" in metadata:
        metadata.setdefault("app_version", ">=" + str(metadata.pop("min_version")))
    return metadata
