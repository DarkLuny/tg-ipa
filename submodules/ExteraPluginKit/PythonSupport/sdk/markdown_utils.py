# This is the iOS counterpart of the exteraGram plugins SDK.
#
# `parse_markdown` mirrors the Android module: it scans Markdown into plain
# text plus Telegram entities, raises on unclosed elements, and converts the
# Python offsets to Telegram's UTF-16 offsets.  The entities are usable
# directly in `client_utils.send_message(..., entities=...)`.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


__all__ = ["parse_markdown", "ParsedMessage", "RawEntity", "TLEntityType", "TLRPC_ENTITIES_MAP"]


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


try:
    from org.telegram.tgnet import TLRPC

    TLRPC_ENTITIES_MAP = {
        TLEntityType.CODE: TLRPC.TL_messageEntityCode,
        TLEntityType.PRE: TLRPC.TL_messageEntityPre,
        TLEntityType.STRIKETHROUGH: TLRPC.TL_messageEntityStrike,
        TLEntityType.TEXT_LINK: TLRPC.TL_messageEntityTextUrl,
        TLEntityType.BOLD: TLRPC.TL_messageEntityBold,
        TLEntityType.ITALIC: TLRPC.TL_messageEntityItalic,
        TLEntityType.UNDERLINE: TLRPC.TL_messageEntityUnderline,
        TLEntityType.SPOILER: TLRPC.TL_messageEntitySpoiler,
        TLEntityType.CUSTOM_EMOJI: TLRPC.TL_messageEntityCustomEmoji,
    }
except Exception:
    TLRPC_ENTITIES_MAP = {}


@dataclass
class RawEntity:
    """A Telegram message entity described by plain Python offsets."""

    type: TLEntityType
    offset: int
    length: int
    language: Optional[str] = None
    url: Optional[str] = None
    document_id: Optional[int] = None

    def to_json(self):
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
        return value

    to_native = to_json

    def to_tlrpc_object(self):
        entity_class = TLRPC_ENTITIES_MAP.get(self.type)
        if entity_class is not None:
            try:
                entity = entity_class()
                entity.offset = self.offset
                entity.length = self.length
                if self.language is not None:
                    entity.language = self.language
                if self.url is not None:
                    entity.url = self.url
                if self.document_id is not None:
                    entity.document_id = self.document_id
                return entity
            except Exception:
                pass
        mapping = {
            TLEntityType.CODE: ("TL_messageEntityCode", None),
            TLEntityType.PRE: ("TL_messageEntityPre", "language"),
            TLEntityType.STRIKETHROUGH: ("TL_messageEntityStrike", None),
            TLEntityType.TEXT_LINK: ("TL_messageEntityTextUrl", "url"),
            TLEntityType.BOLD: ("TL_messageEntityBold", None),
            TLEntityType.ITALIC: ("TL_messageEntityItalic", None),
            TLEntityType.UNDERLINE: ("TL_messageEntityUnderline", None),
            TLEntityType.SPOILER: ("TL_messageEntitySpoiler", None),
            TLEntityType.CUSTOM_EMOJI: ("TL_messageEntityCustomEmoji", "document_id"),
        }
        try:
            from org.telegram.tgnet import TLRPC

            name, extra = mapping[self.type]
            entity = getattr(TLRPC, name)()
            entity.offset = self.offset
            entity.length = self.length
            if extra is not None:
                setattr(entity, extra, getattr(self, extra))
            return entity
        except Exception:
            return self.to_json()


@dataclass
class ParsedMessage:
    """The final text and its entities; offsets are UTF-16 units."""

    text: str
    entities: Tuple[RawEntity, ...] = field(default_factory=tuple)


def count_chars_until(string: str, stop_chars: str, start_index: int = 0) -> int:
    """Number of characters from `start_index` until one of `stop_chars`."""
    for index in range(start_index, len(string)):
        if string[index] in stop_chars:
            return index - start_index
    return len(string) - start_index


def to_utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


_STACKABLE = {
    "*": TLEntityType.BOLD,
    "_": TLEntityType.ITALIC,
    "__": TLEntityType.UNDERLINE,
    "~": TLEntityType.STRIKETHROUGH,
    "||": TLEntityType.SPOILER,
}

_STOP_CHARS = "*_~`[]|!\\"


def parse_markdown(markdown: str) -> ParsedMessage:
    """Parses Markdown into `ParsedMessage`.

    Raises `ValueError` on an unclosed code fence or an unclosed marker, as the
    Android implementation does.
    """
    markdown = (markdown or "").replace("\r\n", "\n")
    # Android leaves leading/trailing whitespace out, but a plugin that only
    # wraps text in markers expects the same trimmed message.
    markdown = markdown.strip()

    message = ""
    message_len = 0
    python_entities: List[RawEntity] = []
    offset = 0
    stack: List[Tuple[str, int]] = []

    def flush(value: str) -> None:
        nonlocal message, message_len
        message += value
        message_len += len(value)

    while offset < len(markdown):
        plain = count_chars_until(markdown, _STOP_CHARS, offset)
        flush(markdown[offset:offset + plain])
        offset += plain

        if offset >= len(markdown):
            break

        marker = markdown[offset]
        offset += 1
        following = markdown[offset] if offset < len(markdown) else ""

        if marker == "\\":
            if following:
                flush(following)
                offset += 1
            else:
                flush(marker)
            continue

        if marker == "[":
            label_start = message_len
            label = ""
            markdown_label_start = offset

            while offset < len(markdown) and markdown[offset] != "]":
                if markdown[offset] == "\\" and offset + 1 < len(markdown):
                    label += markdown[offset + 1]
                    offset += 2
                else:
                    label += markdown[offset]
                    offset += 1

            if offset >= len(markdown) or markdown[offset] != "]" or \
                    offset + 1 >= len(markdown) or markdown[offset + 1] != "(":
                flush(marker)
                offset = markdown_label_start
                continue

            offset += 2
            url = ""
            markdown_url_start = offset
            while offset < len(markdown) and markdown[offset] != ")":
                if markdown[offset] == "\\" and offset + 1 < len(markdown):
                    url += markdown[offset + 1]
                    offset += 2
                else:
                    url += markdown[offset]
                    offset += 1

            if offset >= len(markdown) or markdown[offset] != ")":
                flush(marker + label + "](")
                offset = markdown_url_start
                continue

            offset += 1
            flush(label)
            label_len = len(label)

            if url.isdigit() and label_len > 0:
                python_entities.append(RawEntity(
                    type=TLEntityType.CUSTOM_EMOJI,
                    offset=label_start,
                    length=label_len,
                    document_id=int(url),
                ))
            elif label_len > 0:
                python_entities.append(RawEntity(
                    type=TLEntityType.TEXT_LINK,
                    offset=label_start,
                    length=label_len,
                    url=url,
                ))
            continue

        if marker == "`":
            fence_start = offset - 1
            fence_len = 1
            while offset < len(markdown) and markdown[offset] == "`":
                fence_len += 1
                offset += 1

            token = "`" * fence_len
            language = None

            if fence_len >= 3:
                match = re.match(r"([^\s\n]+)", markdown[offset:])
                if match:
                    language = match.group(1)
                    offset += len(language)
                if offset < len(markdown) and markdown[offset] == "\n":
                    offset += 1

            content_start = offset
            close = markdown.find(token, content_start)
            if close == -1:
                raise ValueError("Unclosed %s opened near offset %d!" % (token, fence_start))

            content = markdown[content_start:close]
            entity_start = message_len
            flush(content)

            trimmed = len(content)
            for index in reversed(range(len(content))):
                if content[index] not in (" ", "\r", "\n"):
                    break
                trimmed -= 1

            if trimmed > 0:
                python_entities.append(RawEntity(
                    type=TLEntityType.PRE if fence_len >= 3 else TLEntityType.CODE,
                    offset=entity_start,
                    length=trimmed,
                    language=language,
                ))

            offset = close + len(token)
            continue

        marker_string = marker
        if marker == "_" and following == "_":
            marker_string = "__"
            offset += 1
        elif marker == "|" and following == "|":
            marker_string = "||"
            offset += 1

        if marker_string in _STACKABLE:
            if marker_string == "_" and re.search(r"@\w+$", message):
                flush(marker_string)
                continue

            if stack and stack[-1][0] == marker_string:
                _, entity_start = stack.pop()
                kind = _STACKABLE[marker_string]

                content = message[entity_start:message_len]
                length = len(content)
                for index in reversed(range(len(content))):
                    if content[index] not in (" ", "\r", "\n"):
                        break
                    length -= 1

                if length > 0:
                    python_entities.append(RawEntity(
                        type=kind,
                        offset=entity_start,
                        length=length,
                    ))
            else:
                stack.append((marker_string, message_len))
        else:
            flush(marker_string)

    if stack:
        details = ", ".join("'%s' at message offset %d" % item for item in stack)
        raise ValueError("Found unclosed markdown elements: %s" % details)

    python_entities.sort(key=lambda entity: entity.offset)

    final: List[RawEntity] = []
    python_offset = 0
    utf16_offset = 0
    for entity in python_entities:
        utf16_offset += to_utf16_len(message[python_offset:entity.offset])
        start = utf16_offset
        length = to_utf16_len(message[entity.offset:entity.offset + entity.length])
        final.append(RawEntity(
            type=entity.type,
            offset=start,
            length=length,
            language=entity.language,
            url=entity.url,
            document_id=entity.document_id,
        ))
        utf16_offset = start + length
        python_offset = entity.offset + entity.length

    return ParsedMessage(text=message, entities=tuple(final))


try:
    from org.telegram.tgnet import TLRPC as _TLRPC

    TLRPC_ENTITIES_MAP = {
        TLEntityType.CODE: _TLRPC.TL_messageEntityCode,
        TLEntityType.PRE: _TLRPC.TL_messageEntityPre,
        TLEntityType.STRIKETHROUGH: _TLRPC.TL_messageEntityStrike,
        TLEntityType.TEXT_LINK: _TLRPC.TL_messageEntityTextUrl,
        TLEntityType.BOLD: _TLRPC.TL_messageEntityBold,
        TLEntityType.ITALIC: _TLRPC.TL_messageEntityItalic,
        TLEntityType.UNDERLINE: _TLRPC.TL_messageEntityUnderline,
        TLEntityType.SPOILER: _TLRPC.TL_messageEntitySpoiler,
        TLEntityType.CUSTOM_EMOJI: _TLRPC.TL_messageEntityCustomEmoji,
    }
except Exception:
    TLRPC_ENTITIES_MAP = {}
