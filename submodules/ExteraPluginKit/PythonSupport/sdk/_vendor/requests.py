"""Minimal `requests`-compatible shim for the iOS plugin SDK.

ElyxCore uses only a small part of requests (a GET with `iter_content`).
Shipping the full requests/urllib3 stack would be heavy, so this module maps
the same names onto `urllib.request`.  HTTPS works through CPython's ssl
module; a failure is reported as a `RequestException`.
"""

import json as _json
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta


class RequestException(Exception):
    pass


class HTTPError(RequestException):
    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


class Response:
    def __init__(self, status_code, content, headers=None, url="", reason=""):
        self.status_code = int(status_code or 0)
        self.content = content or b""
        self.headers = dict(headers or {})
        self.url = url
        self.reason = reason
        self.encoding = self._encoding_from_headers(self.headers)
        self.history = []
        self.elapsed = timedelta(0)
        self.cookies = {}
        self.links = {}
        self.request = None
        self.raw = None

    @staticmethod
    def _encoding_from_headers(headers):
        try:
            content_type = str(headers.get("Content-Type") or headers.get("content-type") or "")
            for part in content_type.split(";")[1:]:
                key, _, value = part.partition("=")
                if key.strip().lower() == "charset" and value.strip():
                    return value.strip().strip('"\'')
        except Exception:
            pass
        return "utf-8"

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    @property
    def text(self):
        return self.content.decode(self.encoding, errors="replace")

    @property
    def apparent_encoding(self):
        return self.encoding

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308) and "Location" in self.headers

    @property
    def is_permanent_redirect(self):
        return self.status_code in (301, 308) and "Location" in self.headers

    @property
    def next(self):
        if self.is_redirect:
            return None
        return None

    def json(self, **kwargs):
        return _json.loads(self.text, **kwargs)

    def iter_content(self, chunk_size=8192, decode_unicode=False):
        for index in range(0, len(self.content), chunk_size):
            chunk = self.content[index:index + chunk_size]
            yield chunk.decode(self.encoding, errors="replace") if decode_unicode else chunk

    def iter_lines(self, chunk_size=512, decode_unicode=False):
        for line in self.text.splitlines():
            yield line

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPError("HTTP %s" % self.status_code, response=self)

    def close(self):
        return None

    def __bool__(self):
        return self.ok

    def __repr__(self):
        return "<Response [%d]>" % self.status_code

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def request(method, url, headers=None, data=None, json=None, timeout=30,
            params=None, **kwargs):
    if params:
        separator = "&" if "?" in url else "?"
        url = url + separator + urllib.parse.urlencode(params, doseq=True)
    body = data
    request_headers = dict(headers or {})
    if json is not None:
        body = _json.dumps(json).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request_object = urllib.request.Request(
        url, data=body, headers=request_headers, method=str(method).upper()
    )
    try:
        with urllib.request.urlopen(request_object, timeout=timeout) as response:
            return Response(
                response.status,
                response.read(),
                dict(response.headers),
                response.geturl(),
            )
    except urllib.error.HTTPError as error:
        return Response(
            error.code,
            error.read(),
            dict(error.headers or {}),
            url,
            str(error.reason),
        )
    except Exception as error:
        raise RequestException(str(error))


def get(url, **kwargs):
    return request("GET", url, **kwargs)


def post(url, **kwargs):
    return request("POST", url, **kwargs)


def put(url, **kwargs):
    return request("PUT", url, **kwargs)


def patch(url, **kwargs):
    return request("PATCH", url, **kwargs)


def delete(url, **kwargs):
    return request("DELETE", url, **kwargs)


def head(url, **kwargs):
    return request("HEAD", url, **kwargs)


def options(url, **kwargs):
    return request("OPTIONS", url, **kwargs)


class _CaseInsensitiveDict(dict):
    """Small `requests.structures.CaseInsensitiveDict` equivalent."""

    @staticmethod
    def _key(key):
        return str(key).lower()

    def __getitem__(self, key):
        return super().__getitem__(self._key(key))

    def __setitem__(self, key, value):
        super().__setitem__(self._key(key), value)

    def __contains__(self, key):
        return super().__contains__(self._key(key))

    def get(self, key, default=None):
        return super().get(self._key(key), default)

    def pop(self, key, *args):
        return super().pop(self._key(key), *args)

    def update(self, *args, **kwargs):
        other = dict(*args, **kwargs)
        for key, value in other.items():
            self[key] = value

    def copy(self):
        result = _CaseInsensitiveDict()
        result.update(self)
        return result


class Session:
    """The part of `requests.Session` plugins use: defaults + connection reuse."""

    def __init__(self):
        self.headers = _CaseInsensitiveDict()
        self.params = {}
        self.cookies = {}
        self.auth = None
        self.proxies = {}
        self.verify = True
        self.timeout = 30
        self.trust_env = True
        self.max_redirects = 30
        self.adapters = {}

    def request(self, method, url, **kwargs):
        headers = _CaseInsensitiveDict()
        headers.update(self.headers)
        headers.update(kwargs.pop("headers", None) or {})

        params = dict(self.params)
        params.update(kwargs.pop("params", None) or {})
        if params:
            kwargs["params"] = params

        cookies = dict(self.cookies)
        cookies.update(kwargs.pop("cookies", None) or {})
        if cookies and "Cookie" not in headers:
            headers["Cookie"] = "; ".join(
                "%s=%s" % (key, value) for key, value in cookies.items()
            )

        auth = kwargs.pop("auth", self.auth)
        if auth is not None and "Authorization" not in headers:
            try:
                import base64

                if isinstance(auth, (tuple, list)) and len(auth) == 2:
                    token = base64.b64encode(
                        ("%s:%s" % (auth[0], auth[1])).encode("utf-8")
                    ).decode("ascii")
                    headers["Authorization"] = "Basic " + token
            except Exception:
                pass

        kwargs.pop("verify", None)
        kwargs.pop("proxies", None)
        kwargs.pop("stream", None)
        kwargs.pop("allow_redirects", None)
        kwargs.setdefault("timeout", self.timeout)
        return request(method, url, headers=dict(headers), **kwargs)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def patch(self, url, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def head(self, url, **kwargs):
        return self.request("HEAD", url, **kwargs)

    def options(self, url, **kwargs):
        return self.request("OPTIONS", url, **kwargs)

    def close(self):
        return None

    def mount(self, prefix, adapter):
        self.adapters[str(prefix)] = adapter

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def session():
    return Session()


class _ExceptionsNamespace:
    RequestException = RequestException
    HTTPError = HTTPError
    ConnectionError = RequestException
    ConnectTimeout = RequestException
    ReadTimeout = RequestException
    Timeout = RequestException
    TooManyRedirects = RequestException
    JSONDecodeError = ValueError


class _CodesNamespace:
    ok = 200
    created = 201
    accepted = 202
    no_content = 204
    moved_permanently = 301
    found = 302
    not_modified = 304
    bad_request = 400
    unauthorized = 401
    forbidden = 403
    not_found = 404
    method_not_allowed = 405
    conflict = 409
    too_many_requests = 429
    internal_server_error = 500
    bad_gateway = 502
    service_unavailable = 503
    gateway_timeout = 504


exceptions = _ExceptionsNamespace()
codes = _CodesNamespace()

__version__ = "2.31.0-ios"
