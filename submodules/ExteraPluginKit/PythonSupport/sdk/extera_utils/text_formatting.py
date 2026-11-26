# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Text parsing for `send_text(..., parse_mode="html"|"markdown")` and for
# plugins that build entities themselves.  The public API mirrors the Android
# module: `TLEntityType`, `RawEntity`, `Parser`, `HTML.parse/unparse`,
# `Markdown.parse/unparse`, `parse_text` and `replace_once`.
#
# Entities carry Telegram's UTF-16 offsets, exactly like the Android module,
# so an entity produced here can be passed to `send_message` unchanged.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import html
import re
from dataclasses import dataclass
from enum import Enum
from html.parser import HTMLParser
from struct import unpack
from typing import Any, Dict, List, Optional, Tuple, Union


__all__ = [
    "TLEntityType",
    "RawEntity",
    "Parser",
    "HTML",
    "Markdown",
    "parse_text",
    "replace_once",
    "add_surrogates",
    "remove_surrogates",
]


##############################   Markdown & HTML parsers   ##############################

_SURROGATE_RE = re.compile(r"[\U00010000-\U0010FFFF]")


def add_surrogates(text: str) -> str:
    """Replaces every astral character with its UTF-16 surrogate pair.

    The result is a string whose Python length is the UTF-16 length Telegram
    uses for entity offsets, which is what the Android parser works with.
    """
    if not text:
        return text or ""
    return _SURROGATE_RE.sub(
        lambda match: "".join(
            chr(unit) for unit in unpack("<HH", match.group().encode("utf-16le"))
        ),
        text,
    )


def remove_surrogates(text: str) -> str:
    if not text:
        return text or ""
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "surrogatepass")


class TLEntityType(Enum):
    CODE = "code"
    PRE = "pre"
    STRIKETHROUGH = "strikethrough"
    TEXT_LINK = "text_link"
    BOLD = "bold"
    ITALIC = "italic"
    UNDERLINE = "underline"
    SPOILER = "spoiler"
    CUSTOM_EMOJI = "custom_emoji"
    BLOCKQUOTE = "blockquote"

    @classmethod
    def from_(cls, entity):
        """Resolves the entity type from a RawEntity, a dict or an object.

        Android passes `TLRPC.TL_messageEntity*` instances here; on iOS the
        host serialises entities as dictionaries, so both shapes are accepted.
        """
        if entity is None:
            return None
        kind = entity.get("type") if isinstance(entity, dict) else getattr(entity, "type", None)
        if isinstance(kind, cls):
            return kind
        if isinstance(kind, str):
            try:
                return cls(kind)
            except ValueError:
                return None

        name = type(entity).__name__
        if name.startswith("TL_messageEntity"):
            suffix = name[len("TL_messageEntity"):]
            mapping = {
                "Code": cls.CODE,
                "Pre": cls.PRE,
                "Strike": cls.STRIKETHROUGH,
                "TextUrl": cls.TEXT_LINK,
                "Bold": cls.BOLD,
                "Italic": cls.ITALIC,
                "Underline": cls.UNDERLINE,
                "Spoiler": cls.SPOILER,
                "CustomEmoji": cls.CUSTOM_EMOJI,
                "Blockquote": cls.BLOCKQUOTE,
            }
            return mapping.get(suffix)
        return None


def _field(entity, key, default=None):
    if isinstance(entity, dict):
        return entity.get(key, default)
    return getattr(entity, key, default)


@dataclass
class RawEntity:
    type: TLEntityType
    offset: int
    length: int
    language: Optional[str] = None
    url: Optional[str] = None
    document_id: Optional[int] = None
    collapsed: Optional[bool] = None

    @property
    def TLRPC_ENTITIES_MAP(self):
        # Imported lazily so the module can be imported before `compat.install`
        # and on desktop Python without the Android shims.
        try:
            from org.telegram.tgnet import TLRPC

            return {
                TLEntityType.CODE: TLRPC.TL_messageEntityCode,
                TLEntityType.PRE: TLRPC.TL_messageEntityPre,
                TLEntityType.STRIKETHROUGH: TLRPC.TL_messageEntityStrike,
                TLEntityType.TEXT_LINK: TLRPC.TL_messageEntityTextUrl,
                TLEntityType.BOLD: TLRPC.TL_messageEntityBold,
                TLEntityType.ITALIC: TLRPC.TL_messageEntityItalic,
                TLEntityType.UNDERLINE: TLRPC.TL_messageEntityUnderline,
                TLEntityType.SPOILER: TLRPC.TL_messageEntitySpoiler,
                TLEntityType.CUSTOM_EMOJI: TLRPC.TL_messageEntityCustomEmoji,
                TLEntityType.BLOCKQUOTE: TLRPC.TL_messageEntityBlockquote,
            }
        except Exception:
            return {}

    def to_json(self):
        """The host-facing form: a plain dictionary with a constructor type."""
        value = {
            "type": self.type.value if isinstance(self.type, TLEntityType) else str(self.type),
            "offset": int(self.offset),
            "length": int(self.length),
        }
        if self.language is not None:
            value["language"] = self.language
        if self.url is not None:
            value["url"] = self.url
        if self.document_id is not None:
            value["document_id"] = self.document_id
        if self.collapsed is not None:
            value["collapsed"] = self.collapsed
        return value

    to_native = to_json

    def to_tlrpc_object(self):
        constructor = self.TLRPC_ENTITIES_MAP.get(self.type)
        if constructor is None:
            return self.to_json()
        entity = constructor()
        entity.offset = self.offset
        entity.length = self.length
        if self.language is not None and self.type == TLEntityType.PRE:
            entity.language = self.language
        if self.url is not None and self.type == TLEntityType.TEXT_LINK:
            entity.url = self.url
        if self.document_id is not None and self.type == TLEntityType.CUSTOM_EMOJI:
            entity.document_id = self.document_id
        if self.collapsed is not None and self.type == TLEntityType.BLOCKQUOTE:
            entity.collapsed = self.collapsed
        return entity


class Parser(HTMLParser):
    """Collects `RawEntity` objects while feeding HTML.

    The parser mirrors the Android one: a tag's entity starts at the current
    text length and grows with every data chunk inside it; the entity is
    finished by the matching end tag.
    """

    def __init__(self, convert_charrefs: bool = True):
        super().__init__(convert_charrefs=convert_charrefs)
        self.text = ""
        self.entities: List[RawEntity] = []
        self.tag_entities: Dict[str, List[RawEntity]] = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        extra: Dict[str, Any] = {}

        if tag in ("b", "strong"):
            kind = TLEntityType.BOLD
        elif tag in ("i", "em"):
            kind = TLEntityType.ITALIC
        elif tag == "u":
            kind = TLEntityType.UNDERLINE
        elif tag in ("s", "del", "strike"):
            kind = TLEntityType.STRIKETHROUGH
        elif tag == "blockquote":
            kind = TLEntityType.BLOCKQUOTE
            extra["collapsed"] = ("expandable" in attributes) or ("collapsed" in attributes)
        elif tag == "code":
            kind = TLEntityType.CODE
        elif tag == "pre":
            kind = TLEntityType.PRE
            extra["language"] = attributes.get("language", attributes.get("lang", ""))
        elif tag in ("spoiler", "tg-spoiler", "span"):
            if tag == "span" and "tg-spoiler" not in attributes:
                return
            kind = TLEntityType.SPOILER
        elif tag == "a":
            kind = TLEntityType.TEXT_LINK
            extra["url"] = attributes.get("href", "")
        elif tag == "emoji":
            raw = attributes.get("id", attributes.get("document_id", "0"))
            if not raw or not str(raw).isdigit():
                return
            kind = TLEntityType.CUSTOM_EMOJI
            extra["document_id"] = int(raw)
        else:
            return

        self.tag_entities.setdefault(tag, []).append(
            RawEntity(type=kind, offset=len(self.text), length=0, **extra)
        )

    def handle_data(self, data):
        data = html.unescape(data)
        for entities in self.tag_entities.values():
            for entity in entities:
                entity.length += len(data)
        self.text += data

    def handle_endtag(self, tag):
        try:
            self.entities.append(self.tag_entities[tag].pop())
        except (KeyError, IndexError):
            return
        if not self.tag_entities[tag]:
            self.tag_entities.pop(tag)


def _trim_html(text: str) -> str:
    text = re.sub(r"^\s*(<[\w<>=\s\"]*>)\s*", r"\1", text)
    text = re.sub(r"\s*(</[\w</>]*>)\s*$", r"\1", text)
    return text


class HTML:
    @staticmethod
    def parse(text: str) -> dict:
        parser = Parser()
        parser.feed(add_surrogates(_trim_html(text or "")))
        parser.close()
        entities = [entity for entity in parser.entities if entity.length > 0]
        return {
            "message": remove_surrogates(parser.text),
            "entities": sorted(entities, key=lambda entity: entity.offset),
        }

    @staticmethod
    def unparse(text: str, entities: list) -> str:
        def opener(entity):
            entity_type = TLEntityType.from_(entity)
            start = _field(entity, "offset", 0)
            end = start + _field(entity, "length", 0)

            if entity_type in (
                TLEntityType.BOLD,
                TLEntityType.ITALIC,
                TLEntityType.UNDERLINE,
                TLEntityType.STRIKETHROUGH,
            ):
                name = entity_type.name[0].lower()
                return f"<{name}>", start, f"</{name}>", end
            if entity_type == TLEntityType.PRE:
                language = _field(entity, "language", "") or ""
                opening = f'<pre language="{language}">' if language else "<pre>"
                return opening, start, "</pre>", end
            if entity_type == TLEntityType.BLOCKQUOTE:
                collapsed = _field(entity, "collapsed", _field(entity, "expandable", False))
                return f'<blockquote{" expandable" if collapsed else ""}>', start, "</blockquote>", end
            if entity_type in (TLEntityType.CODE, TLEntityType.SPOILER):
                name = entity_type.value
                return f"<{name}>", start, f"</{name}>", end
            if entity_type == TLEntityType.TEXT_LINK:
                return f'<a href="{_field(entity, "url", "")}">', start, "</a>", end
            if entity_type == TLEntityType.CUSTOM_EMOJI:
                return f'<emoji id={_field(entity, "document_id", 0)}>', start, "</emoji>", end
            return None

        text = add_surrogates(text or "")
        inserts: List[Tuple[int, int, str]] = []
        for entity in sorted(entities or [], key=lambda item: (_field(item, "offset", 0), -_field(item, "length", 0))):
            parts = opener(entity)
            if parts is None:
                continue
            start_tag, start, end_tag, end = parts
            inserts.append((start, 0, start_tag))
            inserts.append((end, 1, end_tag))

        # Group by offset preserving insertion order.  Android inserts the
        # whole list back to front; the resulting left-to-right order at one
        # offset is the reverse of the insertion order.
        grouped: Dict[int, List[str]] = {}
        for offset, _, markup in inserts:
            grouped.setdefault(max(0, min(offset, len(text))), []).append(markup)

        result = []
        cursor = 0
        for offset in sorted(grouped):
            if offset > cursor:
                result.append(html.escape(text[cursor:offset]))
            result.extend(reversed(grouped[offset]))
            cursor = offset
        if cursor < len(text):
            result.append(html.escape(text[cursor:]))

        return remove_surrogates("".join(result))


BOLD_DELIM = "*"
ITALIC_DELIM = "_"
UNDERLINE_DELIM = "__"
STRIKE_DELIM = "~"
SPOILER_DELIM = "||"
CODE_DELIM = "`"
PRE_DELIM = "```"
BLOCKQUOTE_DELIM = ">"
BLOCKQUOTE_EXPANDABLE_DELIM = "**>"
BLOCKQUOTE_EXPANDABLE_END_DELIM = "||"

MARKDOWN_RE = re.compile(r"({d})|(!?)\[(.+?)]\((.+?)\)".format(
    d="|".join(
        ["".join(i) for i in [
            [rf"\{j}" for j in i]
            for i in [
                PRE_DELIM,
                CODE_DELIM,
                STRIKE_DELIM,
                UNDERLINE_DELIM,
                ITALIC_DELIM,
                BOLD_DELIM,
                SPOILER_DELIM,
            ]
        ]]
    )
))

OPENING_TAG = "<{}>"
CLOSING_TAG = "</{}>"
URL_MARKUP = '<a href="{}">{}</a>'
EMOJI_MARKUP = "<emoji id={}>{}</emoji>"
FIXED_WIDTH_DELIMS = [CODE_DELIM, PRE_DELIM]
MARKDOWN_ESCAPABLE_CHARS = "\\_*[]()~`|>!"
ESCAPED_MARKDOWN_RE = re.compile(
    r"\\([{}])".format(re.escape(MARKDOWN_ESCAPABLE_CHARS))
)
_ESCAPED_RE = ESCAPED_MARKDOWN_RE


def replace_once(source: str, old: str, new: str, start: int) -> str:
    return source[:start] + source[start:].replace(old, new, 1)


class Markdown:
    @staticmethod
    def protect_escaped_chars(text: str) -> Tuple[str, Dict[str, str]]:
        escaped: Dict[str, str] = {}

        def replace(match):
            placeholder = "\uE000%d\uE001" % len(escaped)
            escaped[placeholder] = match.group(1)
            return placeholder

        return _ESCAPED_RE.sub(replace, text), escaped

    @staticmethod
    def restore_escaped_chars(text: str, escaped_chars: Dict[str, str]) -> str:
        for placeholder, value in escaped_chars.items():
            text = text.replace(placeholder, value)
        return text

    @staticmethod
    def escape_and_create_quotes(text: str, strict: bool) -> str:
        lines: List[Optional[str]] = text.splitlines()
        already_escaped: set = set()
        pending: List[Tuple[int, str]] = []

        def flush(expandable: bool = False) -> None:
            if not pending:
                return
            joined = "\n".join(line for _, line in pending)
            first_index = pending[0][0]
            lines[first_index] = (
                "<blockquote%s>%s</blockquote>" % (" expandable" if expandable else "", joined)
            )
            for index, _ in pending[1:]:
                lines[index] = None
            del pending[:]

        inside = False
        for index, line in enumerate(lines):
            if line.startswith(BLOCKQUOTE_EXPANDABLE_DELIM) and not inside:
                stripped = line[len(BLOCKQUOTE_EXPANDABLE_DELIM):]
                if stripped.startswith(" "):
                    stripped = stripped[1:]
                pending.append((index, html.escape(stripped) if strict else stripped))
                already_escaped.add(index)
                inside = True
                continue
            if line.endswith(BLOCKQUOTE_EXPANDABLE_END_DELIM) and inside:
                if line.startswith(BLOCKQUOTE_DELIM):
                    stripped = line[len(BLOCKQUOTE_DELIM):]
                    if stripped.startswith(" "):
                        stripped = stripped[1:]
                    line = stripped
                stripped = line[:-len(BLOCKQUOTE_EXPANDABLE_END_DELIM)]
                pending.append((index, html.escape(stripped) if strict else stripped))
                already_escaped.add(index)
                inside = False
                flush(expandable=True)
                continue
            if inside:
                stripped = line[len(BLOCKQUOTE_DELIM):]
                if stripped.startswith(" "):
                    stripped = stripped[1:]
                pending.append((index, html.escape(stripped) if strict else stripped))
                already_escaped.add(index)

        for index, line in enumerate(lines):
            if line is None:
                continue
            if line.startswith(BLOCKQUOTE_DELIM):
                stripped = line[len(BLOCKQUOTE_DELIM):]
                if stripped.startswith(" "):
                    stripped = stripped[1:]
                pending.append((index, html.escape(stripped) if strict else stripped))
                already_escaped.add(index)
            elif pending:
                flush()
        else:
            flush()

        if strict:
            for index, line in enumerate(lines):
                if line is not None and index not in already_escaped:
                    lines[index] = html.escape(line)

        return "\n".join(line for line in lines if line is not None)

    @classmethod
    def parse(cls, text: str, strict: bool = False) -> dict:
        text, escaped = cls.protect_escaped_chars(text or "")
        text = cls.escape_and_create_quotes(text, strict=strict)

        output: List[str] = []
        open_delims: List[str] = []
        index = 0
        length = len(text)

        def toggle(delim: str, tag: str) -> str:
            if delim in open_delims:
                open_delims.remove(delim)
                return "</%s>" % tag
            open_delims.append(delim)
            return "<%s>" % tag

        while index < length:
            char = text[index]

            if char == "[" or (char == "!" and index + 1 < length and text[index + 1] == "["):
                emoji = char == "!"
                label_start = index + (2 if emoji else 1)
                label_end = text.find("]", label_start)
                if label_end != -1 and label_end + 1 < length and text[label_end + 1] == "(":
                    url_end = text.find(")", label_end + 2)
                    if url_end != -1:
                        label = text[label_start:label_end]
                        url = text[label_end + 2:url_end]
                        if emoji:
                            emoji_id = url[len("tg://emoji?id="):] if url.startswith("tg://emoji?id=") else url
                            output.append("<emoji id=%s>%s</emoji>" % (emoji_id, label))
                        else:
                            output.append('<a href="%s">%s</a>' % (url, label))
                        index = url_end + 1
                        continue

            if char == "`":
                fence = 1
                while index + fence < length and text[index + fence] == "`":
                    fence += 1
                token = "`" * fence
                close = text.find(token, index + fence)
                if close == -1:
                    output.append(char)
                    index += 1
                    continue
                content = text[index + fence:close]
                language = ""
                if fence >= 3 and "\n" in content:
                    first_line, content = content.split("\n", 1)
                    if first_line and not first_line.startswith(" "):
                        language = first_line
                if fence >= 3:
                    output.append('<pre%s>%s</pre>' % (
                        ' language="%s"' % language if language else "", content
                    ))
                else:
                    output.append("<code>%s</code>" % content)
                index = close + fence
                continue

            if char in "*_~|":
                if char == "_" and index + 1 < length and text[index + 1] == "_":
                    delim, tag = "__", "u"
                elif char == "|" and index + 1 < length and text[index + 1] == "|":
                    delim, tag = "||", "spoiler"
                elif char == "*":
                    delim, tag = "*", "b"
                elif char == "_":
                    delim, tag = "_", "i"
                elif char == "~":
                    delim, tag = "~", "s"
                else:
                    output.append(char)
                    index += 1
                    continue
                output.append(toggle(delim, tag))
                index += len(delim)
                continue

            output.append(char)
            index += 1

        # Leave unclosed markers open: `HTML.parse` drops tags that never close,
        # which is what the Android module produces for malformed Markdown.
        result = HTML.parse("".join(output))
        result["message"] = cls.restore_escaped_chars(result["message"], escaped)
        return result

    @staticmethod
    def unparse(text: str, entities: list) -> str:
        text = add_surrogates(text or "")
        inserts: List[Tuple[int, int, str]] = []

        for entity in entities or []:
            entity_type = TLEntityType.from_(entity)
            start = _field(entity, "offset", 0)
            end = start + _field(entity, "length", 0)

            if entity_type in (
                TLEntityType.BOLD,
                TLEntityType.ITALIC,
                TLEntityType.UNDERLINE,
                TLEntityType.STRIKETHROUGH,
                TLEntityType.CODE,
                TLEntityType.SPOILER,
            ):
                delim = {
                    TLEntityType.BOLD: BOLD_DELIM,
                    TLEntityType.ITALIC: ITALIC_DELIM,
                    TLEntityType.UNDERLINE: UNDERLINE_DELIM,
                    TLEntityType.STRIKETHROUGH: STRIKE_DELIM,
                    TLEntityType.CODE: CODE_DELIM,
                    TLEntityType.SPOILER: SPOILER_DELIM,
                }[entity_type]
                inserts.append((start, 0, delim))
                inserts.append((end, 1, delim))
            elif entity_type == TLEntityType.PRE:
                language = _field(entity, "language", "") or ""
                inserts.append((start, 0, "%s%s\n" % (PRE_DELIM, language)))
                inserts.append((end, 1, "\n%s" % PRE_DELIM))
            elif entity_type == TLEntityType.TEXT_LINK:
                inserts.append((start, 0, "["))
                inserts.append((end, 1, "](%s)" % _field(entity, "url", "")))
            elif entity_type == TLEntityType.CUSTOM_EMOJI:
                inserts.append((start, 0, "!["))
                inserts.append((end, 1, "](tg://emoji?id=%s)" % _field(entity, "document_id", 0)))
            elif entity_type == TLEntityType.BLOCKQUOTE:
                block = text[start:end]
                offset = start
                for line in block.split("\n"):
                    inserts.append((offset, 0, BLOCKQUOTE_DELIM + " "))
                    offset += len(line) + 1
            else:
                continue

        # Closing markers first at the same offset (reverse order), then opens.
        for offset, order, value in sorted(inserts, key=lambda item: (item[0], item[1]), reverse=True):
            text = text[:offset] + value + text[offset:]

        return remove_surrogates(text)


##############################  END Markdown & HTML parsers   ##############################


def parse_text(text: str, parse_mode: Optional[str] = "HTML", is_caption: bool = False) -> Dict[str, Any]:
    key = "caption" if is_caption else "message"
    if not parse_mode:
        return {key: text, "entities": []}

    mode = parse_mode.lower()
    if mode == "markdown":
        result = Markdown.parse(text)
    elif mode == "html":
        result = HTML.parse(text)
    else:
        raise ValueError("Invalid parse mode: %s. Must be 'html' or 'markdown'." % parse_mode)

    return {
        key: result["message"],
        "entities": [
            entity.to_json() if isinstance(entity, RawEntity) else entity
            for entity in result["entities"]
        ],
    }


# Kept for the earlier host-side helpers.
def parse_html(text):
    result = HTML.parse(text)
    return result["message"], [entity.to_json() for entity in result["entities"]]


def parse_markdown(text):
    result = Markdown.parse(text)
    return result["message"], [entity.to_json() for entity in result["entities"]]


def escape(text):
    return html.escape(str(text), quote=False)


def unescape(text):
    return html.unescape(str(text))
