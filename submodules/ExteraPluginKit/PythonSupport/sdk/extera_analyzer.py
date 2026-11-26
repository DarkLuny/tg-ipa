# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Static analysis of a `.plugin` file before it is installed or enabled.  The
# output is the JSON document the exteraGram analyzer produces:
#
#   {"analyzer": {"version": ...}, "max_severity": "danger",
#    "findings": [...], "statements": [...], "artifacts": [...],
#    "limits": [...], "stats": {"elapsed_ms": 12}}
#
# Rule ids, capability names and the statement shape match the Android catalog,
# so the iOS install sheet shows the same categories, severities and values.
# On Android the heavy analysis runs in a native isolation process; on iOS the
# analysis is this module, executed by the embedded interpreter before the
# plugin is imported.  A file that is too large, cannot be decoded or is not
# Python yields a report with an explicit limit rather than a silent pass.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import ast
import base64
import io
import json
import os
import re
import time
import tokenize


ANALYZER_VERSION = "ios-1.0"
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_EVIDENCE = 4

SEVERITY_NONE = -1
SEVERITY_INFO = 0
SEVERITY_CAUTION = 1
SEVERITY_DANGER = 2
SEVERITY_CRITICAL = 3

SEVERITY_NAMES = {
    SEVERITY_NONE: "none",
    SEVERITY_INFO: "info",
    SEVERITY_CAUTION: "caution",
    SEVERITY_DANGER: "danger",
    SEVERITY_CRITICAL: "critical",
}

_NETWORK_MODULES = {
    "socket": "socket", "ssl": "ssl", "http": "http", "urllib": "urllib",
    "urllib.request": "urllib", "urllib3": "urllib3", "requests": "requests",
    "aiohttp": "aiohttp", "httpx": "httpx", "websocket": "websocket",
    "websockets": "websockets", "ftplib": "ftplib", "smtplib": "smtplib",
    "telnetlib": "telnetlib", "xmlrpc": "xmlrpc", "grpc": "grpc",
}

_NATIVE_MODULES = {
    "ctypes": "ctypes", "cffi": "cffi", "subprocess": "subprocess",
    "multiprocessing": "multiprocessing", "mmap": "mmap", "fcntl": "fcntl",
}

_ENCODING_MODULES = {
    "base64": "base64", "binascii": "binascii", "codecs": "codecs",
    "marshal": "marshal", "pickle": "pickle", "zlib": "zlib", "gzip": "gzip",
    "lzma": "lzma", "bz2": "bz2",
}

_FILE_MODULES = {"os", "shutil", "pathlib", "tempfile", "glob", "io", "fileinput", "zipfile", "tarfile"}

_TELEGRAM_SYMBOLS = {
    "UserConfig", "AccountInstance", "MessagesController", "ContactsController",
    "SendMessagesHelper", "MessagesStorage", "ConnectionsManager", "TLRPC",
    "MessageObject", "MediaController", "FileLoader", "NotificationsController",
    "LaunchActivity", "AndroidUtilities", "NotificationCenter", "LocaleController",
    "ChatActivity", "ProfileActivity", "BaseFragment", "AlertDialog", "BulletinFactory",
}

_SENSITIVE_ACCOUNT = {
    "UserConfig", "AccountInstance", "UserConfig.selectedAccount", "get_user_config",
    "get_account_instance", "get_connections_manager", "get_messages_storage",
    "get_auth_key", "auth_key", "session", "session_data", "getCurrentUser",
}

_SENSITIVE_MESSAGES = {
    "get_messages_controller", "getDialogs", "getMessages", "getHistory",
    "get_contacts_controller", "getContacts", "loadMessages", "searchMessages",
    "send_text", "send_message", "send_photo", "send_document", "send_video",
    "send_audio", "edit_message", "delete_messages", "MessageObject",
}

_WALLET_SYMBOLS = {"wallet", "Wallet", "ton", "Ton", "stars", "Stars", "gram", "Gram", "crypto", "mnemonic", "seed_phrase"}

_REQUEST_HOOKS = {"pre_request_hook", "post_request_hook", "on_update_hook", "on_updates_hook"}
_MESSAGE_HOOKS = {"on_send_message_hook", "send_message_hook"}
_UI_SYMBOLS = {"create_settings", "add_menu_item", "MenuItemData", "BulletinHelper", "AlertDialogBuilder", "ui.settings", "Settings"}

_SENSITIVE_REQUEST_RE = re.compile(r"^(account|auth|messages|channels|users|contacts|payments|wallet|stars)\.[A-Za-z0-9_]+$")
_URL_RE = re.compile(r"\b(?:https?|wss?|ftp)://[^\s'\"<>)]+", re.I)
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/]{80,}={0,2}$")
_HEX_RE = re.compile(r"^[0-9a-fA-F]{120,}$")
_COMMENT_DIRECTIVE_RE = re.compile(r"#\s*(?:extera|plugin|noqa|type:\s*ignore)", re.I)


def severity_of(label):
    return {
        "info": SEVERITY_INFO,
        "caution": SEVERITY_CAUTION,
        "danger": SEVERITY_DANGER,
        "critical": SEVERITY_CRITICAL,
    }.get(label, SEVERITY_NONE)


class _Evidence:
    __slots__ = ("line", "end_line", "excerpt", "scope", "symbol", "traits", "payload", "instruction")

    def __init__(self, line, excerpt, scope=None, symbol="", traits=None, payload=None,
                 end_line=None, instruction=None):
        self.line = int(line or 0)
        self.end_line = int(end_line or 0)
        self.excerpt = excerpt
        self.scope = scope
        self.symbol = symbol
        self.traits = list(traits or [])
        self.payload = payload
        self.instruction = instruction

    def to_json(self):
        value = {
            "symbol": self.symbol,
            "location": {"artifact": "0", "line": self.line},
        }
        if self.end_line > self.line:
            value["location"]["end_line"] = self.end_line
        if self.excerpt:
            value["excerpt"] = self.excerpt
        if self.scope:
            value["location"]["scope"] = self.scope
        if self.traits:
            value["traits"] = self.traits
        detail = dict(self.payload) if self.payload else {}
        if self.instruction:
            detail["insn"] = self.instruction
        if detail:
            value["detail"] = detail
        return value


class _Finding:
    def __init__(self, rule, severity, title, capabilities=None):
        self.rule = rule
        self.severity = severity
        self.title = title
        self.capabilities = list(capabilities or [])
        self.values = []
        self.evidence = []
        self.evidence_total = 0

    def add(self, value=None, evidence=None):
        if value and value not in self.values:
            self.values.append(value)
        if evidence is not None:
            self.evidence_total += 1
            if len(self.evidence) < MAX_EVIDENCE:
                self.evidence.append(evidence)

    def to_json(self):
        return {
            "rule": self.rule,
            "severity": SEVERITY_NAMES.get(self.severity, "info"),
            "title": self.title,
            "values": self.values,
            "capabilities": self.capabilities,
            "evidence": [item.to_json() for item in self.evidence],
            "evidence_total": self.evidence_total,
        }


class _Analyzer:
    def __init__(self, source, name, path):
        self.source = source
        self.name = name
        self.path = path
        self.lines = source.splitlines()
        self.tree = None
        self.findings = {}
        self.limits = []
        self.imports = set()
        self.definitions = set()
        self.calls = []
        self.strings = []
        self.has_network = False
        self.has_exec = False
        self.has_dynamic_decode = False
        self.has_telegram = False
        self.has_messages = False
        self.has_account = False
        self.has_wallet = False
        self.has_hooks = False
        self.has_ui = False
        self.has_session = False
        self.has_tamper = False

    # -- helpers ---------------------------------------------------------

    def line_of(self, node):
        return getattr(node, "lineno", 0) or 0

    def excerpt(self, line):
        if 1 <= line <= len(self.lines):
            return self.lines[line - 1].strip()[:240]
        return None

    def finding(self, rule, severity, title, capabilities=None):
        value = self.findings.get(rule)
        if value is None:
            value = _Finding(rule, severity, title, capabilities)
            self.findings[rule] = value
        elif severity > value.severity:
            value.severity = severity
        return value

    def add(self, rule, severity, title, capabilities, value=None, node=None, symbol="",
            excerpt=None, instruction=None):
        finding = self.finding(rule, severity, title, capabilities)
        line = self.line_of(node) if node is not None else 0
        evidence = _Evidence(
            line,
            excerpt if excerpt is not None else self.excerpt(line),
            scope=getattr(node, "scope", None) if node is not None else None,
            symbol=symbol,
            payload=getattr(node, "payload", None) if node is not None else None,
            end_line=getattr(node, "end_lineno", None) if node is not None else None,
            instruction=instruction,
        )
        finding.add(value, evidence)

    # -- AST -------------------------------------------------------------

    def parse(self):
        try:
            self.tree = ast.parse(self.source, filename=self.path or self.name)
        except SyntaxError as error:
            self.add(
                "py.syntax", SEVERITY_CAUTION, "The file is not valid Python",
                ["dynamic_code"], node=None, symbol=str(error),
                excerpt="line %s: %s" % (error.lineno, error.msg),
            )
            self.limits.append("unanalyzed")
            return False
        return True

    def walk(self):
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.definitions.add(node.name)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.on_definition(node)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.on_import(alias.name, node)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.on_import(node.module, node)
                    for alias in node.names:
                        self.on_symbol(node.module + "." + alias.name, node)
            elif isinstance(node, ast.Call):
                self.on_call(node)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.strings.append((node.value, node))
            elif isinstance(node, ast.Attribute):
                self.on_attribute(node)

    def on_import(self, module, node):
        root = module.split(".")[0]
        self.imports.add(module)

        if root in _NETWORK_MODULES:
            self.has_network = True
            self.add("net.module", SEVERITY_INFO, "Network module imported",
                     ["network"], value=module, node=node, symbol=module)
        if root in _NATIVE_MODULES:
            self.add("py.native", SEVERITY_DANGER, "Native code or process execution",
                     ["native_code"], value=module, node=node, symbol=module)
        if root in _ENCODING_MODULES:
            if root in ("base64", "marshal", "pickle", "zlib", "codecs", "binascii"):
                self.has_dynamic_decode = True
                self.add("py.encoding", SEVERITY_CAUTION, "Encoded data handling",
                         ["obfuscation"], value=module, node=node, symbol=module)
        if root in ("subprocess", "multiprocessing", "ctypes", "cffi"):
            self.has_tamper = True
        if module.startswith("org.telegram") or module.startswith("com.exteragram"):
            self.has_telegram = True
            self.add("tl.import", SEVERITY_INFO, "Telegram API used",
                     ["telegram_api"], value=module, node=node, symbol=module)
        if module in ("extera_utils.classes", "de.robv.android.xposed", "com.exteragram.hook"):
            self.add("hooks.reflection", SEVERITY_CAUTION, "Runtime reflection or method hooking",
                     ["java_hooks"], value=module, node=node, symbol=module)
        if module in ("requests", "urllib3", "aiohttp", "httpx"):
            self.add("py.third_party", SEVERITY_CAUTION, "Third-party package required",
                     ["third_party_code"], value=module, node=node, symbol=module)
        if module in ("base_plugin", "client_utils", "hook_utils", "intents",
                      "file_utils", "plugin_settings", "ui.settings", "ui.alert",
                      "ui.bulletin", "extera_utils.classes", "extera_utils.lifecycle"):
            self.has_telegram = True
            self.add("sdk.import", SEVERITY_INFO, "Uses the plugin SDK",
                     ["telegram_api"], value=module, node=node, symbol=module)

    def on_definition(self, node):
        name = node.name
        if name in ("pre_request_hook", "post_request_hook"):
            self.has_hooks = True
            self.add("intercepts.requests", SEVERITY_DANGER,
                     "Observes or rewrites network requests",
                     ["intercepts_requests", "sensitive_requests"], value=name, node=node, symbol=name)
        elif name in ("on_update_hook", "on_updates_hook"):
            self.has_hooks = True
            self.add("hooks.updates", SEVERITY_CAUTION, "Observes incoming updates",
                     ["event_hooks"], value=name, node=node, symbol=name)
        elif name in ("on_send_message_hook",):
            self.has_hooks = True
            self.has_messages = True
            self.add("hooks.messages", SEVERITY_DANGER, "Rewrites outgoing messages",
                     ["messages", "event_hooks"], value=name, node=node, symbol=name)
        elif name in ("on_plugin_load", "on_plugin_unload", "on_app_event"):
            self.add("hooks.lifecycle", SEVERITY_INFO, "Runs plugin lifecycle code",
                     ["event_hooks"], value=name, node=node, symbol=name)
        elif name == "create_settings":
            self.has_ui = True
            self.add("hooks.ui", SEVERITY_INFO, "Adds interface elements",
                     ["ui_hooks"], value=name, node=node, symbol=name)

    def on_symbol(self, symbol, node):
        short = symbol.rsplit(".", 1)[-1]
        if short in _TELEGRAM_SYMBOLS:
            self.has_telegram = True
        if short in _SENSITIVE_ACCOUNT:
            self.has_account = True
        if short in _SENSITIVE_MESSAGES:
            self.has_messages = True
        if short in _WALLET_SYMBOLS:
            self.has_wallet = True
        if short in _UI_SYMBOLS:
            self.has_ui = True
        if short in _REQUEST_HOOKS or short in _MESSAGE_HOOKS:
            self.has_hooks = True

    def _call_name(self, node):
        function = node.func
        parts = []
        while isinstance(function, ast.Attribute):
            parts.append(function.attr)
            function = function.value
        if isinstance(function, ast.Name):
            parts.append(function.id)
        return ".".join(reversed(parts))

    def on_call(self, node):
        name = self._call_name(node)
        short = name.rsplit(".", 1)[-1]
        self.calls.append((name, node))
        line = self.line_of(node)

        if short in ("exec", "eval", "compile", "__import__", "execfile"):
            self.has_exec = True
            self.add("py.dynamic_exec", SEVERITY_DANGER, "Dynamic code execution",
                     ["dynamic_code"], value=name, node=node, symbol=name)

        if name in ("os.system", "os.popen", "subprocess.call", "subprocess.run",
                    "subprocess.Popen", "subprocess.check_output", "os.execv",
                    "os.execve", "os.spawnv"):
            self.has_tamper = True
            self.add("py.subprocess", SEVERITY_DANGER, "Starts an external process",
                     ["native_code"], value=name, node=node, symbol=name)

        if name.startswith("ctypes.") or name.startswith("cffi."):
            self.add("py.native", SEVERITY_DANGER, "Calls native code",
                     ["native_code"], value=name, node=node, symbol=name)

        if short in ("open", "io.open"):
            mode = self._open_mode(node)
            if any(flag in mode for flag in ("w", "a", "x", "+")):
                self.add("py.file_write", SEVERITY_CAUTION, "Writes a file",
                         ["files"], value=self._first_string(node), node=node, symbol=name)
            if any(flag in mode for flag in ("r", "b")) or not mode:
                self.add("py.file_read", SEVERITY_INFO, "Reads a file",
                         ["files"], value=self._first_string(node), node=node, symbol=name)

        if name in ("os.remove", "os.unlink", "shutil.rmtree", "os.rmdir"):
            self.add("py.file_delete", SEVERITY_DANGER, "Deletes files",
                     ["files"], value=self._first_string(node), node=node, symbol=name)

        if short in ("getattr", "setattr", "delattr", "hasattr") and len(node.args) > 1:
            attribute = self._first_string(node)
            if attribute in ("__globals__", "__subclasses__", "__bases__", "__dict__",
                             "__code__", "__builtins__", "__class__"):
                self.add("py.reflection", SEVERITY_DANGER, "Inspects the interpreter internals",
                         ["reflection", "host_tampering"], value=attribute, node=node, symbol=name)

        if short in ("b64decode", "b32decode", "b85decode", "urlsafe_b64decode",
                     "decodebytes", "decompress"):
            self.has_dynamic_decode = True

        if name.startswith("socket.") or name in ("urllib.request.urlopen", "requests.get",
                                                   "requests.post", "requests.request",
                                                   "urlopen", "http.client.HTTPConnection"):
            self.has_network = True

        if short in _SENSITIVE_ACCOUNT or name in _SENSITIVE_ACCOUNT:
            self.has_account = True
            self.add("sensitive.account", SEVERITY_CAUTION, "Reads account data",
                     ["account", "session_data"], value=short, node=node, symbol=name)
        if short in _SENSITIVE_MESSAGES or name in _SENSITIVE_MESSAGES:
            self.has_messages = True
            self.add("sensitive.messages", SEVERITY_CAUTION, "Reads or sends messages",
                     ["messages"], value=short, node=node, symbol=name)
        if short in _WALLET_SYMBOLS:
            self.has_wallet = True
            self.add("sensitive.wallet", SEVERITY_DANGER, "Touches wallet data",
                     ["wallet_access"], value=short, node=node, symbol=name)
        if short in _UI_SYMBOLS:
            self.has_ui = True
        if short in ("hook_method", "hook_all_methods", "hook_all_constructors",
                     "hook_call_site", "hook_field_read", "hook_field_write",
                     "hook_string_constant", "hook_return_value"):
            self.has_hooks = True
            self.add("hooks.java", SEVERITY_DANGER, "Hooks app code",
                     ["java_hooks"], value=name, node=node, symbol=name)
        if short in ("add_menu_item", "create_settings", "BulletinHelper"):
            self.has_ui = True
            self.add("hooks.ui", SEVERITY_INFO, "Adds interface elements",
                     ["ui_hooks"], value=name, node=node, symbol=name)
        if short == "add_hook":
            self.has_hooks = True
            hook_name = self._first_string(node)
            if hook_name:
                self.add("hooks.events", SEVERITY_CAUTION, "Subscribes to app events",
                         ["event_hooks"], value=hook_name, node=node, symbol=hook_name)
        if short in ("add_file_hook", "register"):
            self.add("hooks.files", SEVERITY_CAUTION, "Handles file types",
                     ["files"], value=name, node=node, symbol=name)

        # Requests and their hooks.
        if short in _REQUEST_HOOKS:
            self.has_hooks = True
            self.add("intercepts.requests", SEVERITY_DANGER, "Observes or rewrites network requests",
                     ["intercepts_requests", "sensitive_requests"], value=short, node=node, symbol=name)

        if short == "send_request" or name.startswith("client.request"):
            self.add("sensitive.requests", SEVERITY_CAUTION, "Calls Telegram API methods",
                     ["sensitive_requests", "telegram_api"], value=short, node=node, symbol=name)

        # Network endpoints in the call's literal arguments.
        for argument in list(node.args) + [keyword.value for keyword in node.keywords]:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                self.inspect_string(argument.value, argument)

    def _open_mode(self, node):
        mode = ""
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            mode = str(node.args[1].value or "")
        for keyword in node.keywords:
            if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                mode = str(keyword.value.value or "")
        return mode

    def _first_string(self, node):
        for argument in list(node.args) + [keyword.value for keyword in node.keywords]:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                return argument.value
        return None

    def on_attribute(self, node):
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        name = ".".join(reversed(parts))
        if name in _TELEGRAM_SYMBOLS or name.startswith("org.telegram"):
            self.has_telegram = True
        if "__globals__" in name or "__subclasses__" in name:
            self.has_tamper = True

    def _is_version_text(self, line):
        lowered = (line or "").lower()
        return any(marker in lowered for marker in (
            "__version__", "__sdk_version__", "__app_version__", "version=",
            "version =", "requires", "python_requires", "min_version",
        ))

    def inspect_string(self, value, node):
        line = self.excerpt(self.line_of(node)) or ""
        for match in _URL_RE.findall(value):
            self.has_network = True
            host = re.sub(r"^[a-z]+://", "", match, flags=re.I).split("/")[0].split("?")[0].split(":")[0]
            self.add("net.endpoints", SEVERITY_INFO, "Network endpoint", ["network"],
                     value=host, node=node, symbol=host)
        if _IP_RE.search(value) and not any(part in value for part in ("127.0.0.1", "0.0.0.0")):
            if not self._is_version_text(line):
                self.has_network = True
                self.add("net.raw_ip", SEVERITY_CAUTION, "Raw IP address", ["network"],
                         value=value[:120], node=node, symbol=value[:120])
        if _BASE64_RE.match(value) or _HEX_RE.match(value):
            self.add("artifact.blob", SEVERITY_CAUTION, "Opaque encoded payload",
                     ["obfuscation"], value="payload",
                     node=node, symbol="artifact:data",
                     payload={"length": len(value), "via": "string"})
        for marker in ("session", "auth_key", "tdata", "telegram-data", "keychain"):
            if marker in value.lower():
                self.has_session = True
                self.add("py.session_data", SEVERITY_CRITICAL, "Touches session or key material",
                         ["files", "session_data"], value=value[:120], node=node, symbol=value[:120])
                break
        if _COMMENT_DIRECTIVE_RE.search(value):
            self.add("artifact.comment", SEVERITY_CAUTION, "Directive embedded in text",
                     ["obfuscation"], value="directive", node=node, symbol="artifact:comment")

    # -- token-level checks ---------------------------------------------

    def scan_tokens(self):
        try:
            for token in tokenize.generate_tokens(io.StringIO(self.source).readline):
                if token.type == tokenize.COMMENT:
                    if _BASE64_RE.match(token.string.strip("# ")):
                        self.add("artifact.blob", SEVERITY_DANGER, "Opaque payload in a comment",
                                 ["obfuscation"], value="payload", node=None,
                                 symbol="artifact:comment",
                                 excerpt="line %s" % token.start[0])
                        self.limits.append("spec_budget")
        except Exception:
            pass

    def scan_lines(self):
        # Catch URLs and blobs with regex as well: an f-string or a concatenation
        # is not a single Constant, but the text is still visible.
        for index, line in enumerate(self.lines, start=1):
            for match in _URL_RE.findall(line):
                host = re.sub(r"^[a-z]+://", "", match, flags=re.I).split("/")[0].split("?")[0].split(":")[0]
                self.has_network = True
                finding = self.finding("net.endpoints", SEVERITY_INFO, "Network endpoint", ["network"])
                if host not in finding.values:
                    finding.add(host, _Evidence(index, line.strip()[:240], symbol=host))
            if _IP_RE.search(line):
                if not self._is_version_text(line):
                    self.has_network = True
                    finding = self.finding("net.raw_ip", SEVERITY_CAUTION, "Raw IP address", ["network"])
                    for address in _IP_RE.findall(line):
                        if address not in finding.values:
                            finding.add(address, _Evidence(index, line.strip()[:240], symbol=address))

    # -- statements ------------------------------------------------------

    def statements(self):
        result = []
        severity = {rule: finding.severity for rule, finding in self.findings.items()}

        def add(statement_id, severity_value, title, rules, capabilities, values=None):
            rules = [rule for rule in rules if rule in self.findings]
            if not rules and severity_value <= SEVERITY_INFO:
                return
            result.append({
                "id": statement_id,
                "severity": SEVERITY_NAMES.get(severity_value, "info"),
                "title": title,
                "values": [value for value in (values or []) if value],
                "rules": rules,
                "capabilities": capabilities,
            })

        if "py.dynamic_exec" in self.findings:
            add("dynamic_code", SEVERITY_DANGER, "Executes code built at runtime",
                ["py.dynamic_exec", "py.encoding"], ["dynamic_code"])

        if self.has_exec and self.has_dynamic_decode:
            add("remote_code", SEVERITY_CRITICAL,
                "Decodes and executes a payload",
                ["py.dynamic_exec", "py.encoding", "artifact.blob"],
                ["remote_code", "obfuscation"],
                values=[value for rule in ("py.dynamic_exec", "artifact.blob")
                        for value in self.findings.get(rule, _Finding("", 0, "")).values])

        if self.has_exec and self.has_network:
            add("remote_control", SEVERITY_CRITICAL,
                "Can download and run code",
                ["py.dynamic_exec", "net.endpoints", "net.module"],
                ["remote_control", "remote_code", "network"])

        if self.has_messages and self.has_network:
            add("exfiltrate_messages", SEVERITY_CRITICAL,
                "Can send messages or contacts off the device",
                ["sensitive.messages", "net.endpoints", "net.module"],
                ["exfiltrate_messages", "messages", "network"])

        if self.has_account and self.has_network:
            add("account_takeover", SEVERITY_CRITICAL,
                "Reads account data and uses the network",
                ["sensitive.account", "net.endpoints", "net.module"],
                ["account_takeover", "session_data", "network"])

        if self.has_wallet:
            add("wallet_access", SEVERITY_DANGER,
                "Touches wallet or payment data",
                ["sensitive.wallet"], ["wallet_access"])

        if self.has_hooks:
            add("java_hooks", SEVERITY_DANGER, "Hooks app code",
                ["hooks.java", "hooks.reflection", "intercepts.requests"],
                ["java_hooks"])

        if self.has_ui:
            add("ui_hooks", SEVERITY_INFO, "Adds interface elements",
                ["hooks.ui"], ["ui_hooks"])

        if any(rule in self.findings for rule in
               ("hooks.events", "hooks.updates", "hooks.messages", "hooks.lifecycle", "hooks.files")):
            add("event_hooks", SEVERITY_CAUTION, "Subscribes to app events",
                ["hooks.events", "hooks.updates", "hooks.messages", "hooks.lifecycle", "hooks.files"],
                ["event_hooks", "messages"])

        if self.has_network or "net.module" in self.findings:
            add("network_access", SEVERITY_INFO, "Uses the network",
                ["net.module", "net.endpoints", "net.raw_ip"], ["network"],
                values=self.findings.get("net.endpoints", _Finding("", 0, "")).values)

        if "py.file_write" in self.findings or "py.file_read" in self.findings or "py.file_delete" in self.findings:
            add("file_access", SEVERITY_CAUTION, "Reads or writes files",
                ["py.file_read", "py.file_write", "py.file_delete", "py.session_data"], ["files"])

        if self.has_telegram:
            add("telegram_api", SEVERITY_INFO, "Uses the Telegram API",
                ["tl.import", "sensitive.requests"], ["telegram_api"])

        if self.has_session or "py.session_data" in self.findings:
            add("session_data", SEVERITY_CRITICAL, "Can reach session data",
                ["py.session_data", "sensitive.account"], ["session_data", "files"])

        if "sensitive.requests" in self.findings or "intercepts.requests" in self.findings:
            add("sensitive_requests", SEVERITY_CAUTION, "Calls sensitive Telegram requests",
                ["sensitive.requests"], ["sensitive_requests"])

        if "intercepts.requests" in self.findings:
            add("intercepts_requests", SEVERITY_DANGER, "Intercepts network requests",
                ["intercepts.requests"], ["intercepts_requests"])

        if self.has_tamper:
            add("host_tampering", SEVERITY_DANGER, "Can change the host application",
                ["py.reflection", "py.native", "py.subprocess"], ["host_tampering"])

        if "py.native" in self.findings or "py.subprocess" in self.findings:
            add("native_code", SEVERITY_DANGER, "Runs native code",
                ["py.native", "py.subprocess"], ["native_code"])

        if self.has_dynamic_decode or "artifact.blob" in self.findings or "py.encoding" in self.findings:
            add("obfuscation", SEVERITY_CAUTION, "Contains encoded or obfuscated data",
                ["py.encoding", "artifact.blob", "artifact.comment"], ["obfuscation"])

        if "py.third_party" in self.findings:
            add("packages", SEVERITY_CAUTION, "Requires third-party packages",
                ["py.third_party"], ["third_party_code"])

        result.sort(key=lambda item: -severity_of(item["severity"]))
        return result

    def report(self, elapsed_ms):
        statements = self.statements()
        max_severity = max([severity_of(item["severity"]) for item in statements] + [SEVERITY_NONE])
        return {
            "analyzer": {"version": ANALYZER_VERSION},
            "max_severity": SEVERITY_NAMES.get(max_severity, "none"),
            "statements": statements,
            "findings": [finding.to_json() for finding in self.findings.values()],
            "limits": sorted(set(self.limits)),
            "artifacts": [{
                "id": "0",
                "name": self.name,
                "kind": "python",
            }],
            "stats": {"elapsed_ms": int(elapsed_ms)},
        }


def analyze_source(source, name="plugin", path=None):
    started = time.time()
    analyzer = _Analyzer(source, name, path)
    if analyzer.parse():
        analyzer.walk()
        analyzer.scan_tokens()
        analyzer.scan_lines()
    else:
        analyzer.scan_lines()
    return analyzer.report((time.time() - started) * 1000.0)


def analyze_file(path, name=None):
    name = name or os.path.basename(path)
    try:
        size = os.path.getsize(path)
    except OSError as error:
        return _failure(name, "file not found: %s" % error)
    if size > MAX_FILE_BYTES:
        report = _failure(name, "file is larger than %d bytes" % MAX_FILE_BYTES)
        report["limits"].append("spec_budget")
        return report
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_FILE_BYTES)
    except OSError as error:
        return _failure(name, "could not read the file: %s" % error)

    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError:
        report = _failure(name, "the file is not UTF-8 text")
        report["limits"].append("unanalyzed")
        return report

    return analyze_source(source, name, path)


def _failure(name, message):
    return {
        "analyzer": {"version": ANALYZER_VERSION},
        "max_severity": "none",
        "statements": [],
        "findings": [{
            "rule": "artifact.unreadable",
            "severity": "caution",
            "title": message,
            "values": [],
            "capabilities": [],
            "evidence": [],
            "evidence_total": 0,
        }],
        "limits": [],
        "artifacts": [{"id": "0", "name": name, "kind": "unknown"}],
        "stats": {"elapsed_ms": 0},
    }


def analyze_archive(path, name=None):
    """Analyzes the Python sources inside an `.elyx`/`.eaf` zip archive."""
    import zipfile

    name = name or os.path.basename(path)
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = [
                item for item in archive.namelist()
                if item.lower().endswith(".py") and not item.startswith("__MACOSX")
            ]
            members.sort(key=lambda item: (
                0 if item.lower() == "main.py" or item.lower().endswith("/main.py") else 1,
                item,
            ))
            parts = []
            total = 0
            for member in members:
                try:
                    data = archive.read(member)
                except Exception:
                    continue
                if total + len(data) > MAX_FILE_BYTES:
                    data = data[:max(0, MAX_FILE_BYTES - total)]
                total += len(data)
                parts.append("# " + member + "\n" + data.decode("utf-8", "replace"))
                if total >= MAX_FILE_BYTES:
                    break
    except Exception as error:
        report = _failure(name, "could not read the archive: %s" % error)
        report["limits"].append("unanalyzed")
        return report
    if not parts:
        report = _failure(name, "the archive contains no Python source")
        report["limits"].append("unanalyzed")
        return report
    return analyze_source("\n\n".join(parts), name, path)


def analyze_json(path, name=None):
    return json.dumps(analyze_file(path, name), ensure_ascii=False)


def analyze_archive_json(path, name=None):
    return json.dumps(analyze_archive(path, name), ensure_ascii=False)


def diff_reports(previous, current):
    """The iOS counterpart of Android's native `diff(old, new)`.

    The result has the `new_statements` / `new_findings` shape that
    `AnalyzerDiff.parse` reads on Android.  A statement is new when its id was
    absent; a finding is new or changed when its rule was absent, its values
    differ, or its evidence count changed.  `new_values` lists the values that
    were not present in the previous report, which is what the update sheet
    highlights.
    """
    def index(report):
        return (
            {item.get("id"): item for item in report.get("statements", [])},
            {item.get("rule"): item for item in report.get("findings", [])},
        )

    old_statements, old_findings = index(previous)
    _, new_findings = index(current)

    new_statements = [
        item for item in current.get("statements", [])
        if item.get("id") not in old_statements
    ]
    new_statements.sort(key=lambda item: -severity_of(item.get("severity")))

    changes = []
    for finding in current.get("findings", []):
        rule = finding.get("rule")
        old = old_findings.get(rule)
        if old is None:
            item = dict(finding)
            item["new_values"] = list(finding.get("values", []))
            changes.append(item)
            continue
        old_values = set(old.get("values", []))
        added = [value for value in finding.get("values", []) if value not in old_values]
        old_total = int(old.get("evidence_total", 0) or 0)
        new_total = int(finding.get("evidence_total", 0) or 0)
        if not added and old_total == new_total and old.get("evidence") == finding.get("evidence"):
            continue
        item = dict(finding)
        item["new_values"] = added
        changes.append(item)

    return {
        "new_statements": new_statements,
        "new_findings": changes,
    }


def _analyze_any(path, name=None):
    """Picks the text or archive analyzer from the file itself."""
    lower = str(path).lower()
    if lower.endswith(".elyx") or lower.endswith(".eaf"):
        return analyze_archive(path, name)
    try:
        with open(path, "rb") as handle:
            head = handle.read(4)
    except OSError:
        return analyze_file(path, name)
    if head.startswith(b"PK\x03\x04"):
        return analyze_archive(path, name)
    return analyze_file(path, name)


def analyze_diff(previous_path, current_path, name=None):
    """Analyzes two versions and returns Android's `AnalyzerDiff` JSON."""
    previous = _analyze_any(previous_path)
    current = _analyze_any(current_path, name)
    return diff_reports(previous, current)


def analyze_diff_json(previous_path, current_path, name=None):
    return json.dumps(analyze_diff(previous_path, current_path, name), ensure_ascii=False)


def analyze_compare(previous_path, current_path, name=None):
    """Analyzes both versions once and returns the report and its diff."""
    previous = _analyze_any(previous_path)
    current = _analyze_any(current_path, name)
    return {
        "report": current,
        "diff": diff_reports(previous, current),
    }


def analyze_compare_json(previous_path, current_path, name=None):
    return json.dumps(analyze_compare(previous_path, current_path, name), ensure_ascii=False)
