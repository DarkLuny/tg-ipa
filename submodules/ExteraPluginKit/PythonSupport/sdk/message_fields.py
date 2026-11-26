# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Shared interpretation of the message dictionaries the host passes to plugins
# and of `MessageObject` instances.  Telegram payloads use the API constructor
# names (`"_": "messageMediaDocument"`), snake_case fields and a list of
# document attributes, so both `MessageObject.isVoice()` and the hook payload's
# `message.isVoice()` answer from the same rules instead of guessing.
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.


def _data(value):
    if isinstance(value, dict):
        return value
    inner = getattr(value, "_value", None)
    return inner if isinstance(inner, dict) else None


def message_media(value):
    data = _data(value)
    if not isinstance(data, dict):
        return None
    media = data.get("media")
    return media if isinstance(media, dict) else None


def message_document(value):
    data = _data(value)
    if not isinstance(data, dict):
        return None
    document = data.get("document")
    if isinstance(document, dict):
        return document
    media = data.get("media")
    if isinstance(media, dict):
        document = media.get("document")
        if isinstance(document, dict):
            return document
    return None


def message_photo(value):
    data = _data(value)
    if not isinstance(data, dict):
        return None
    photo = data.get("photo")
    if isinstance(photo, dict):
        return photo
    media = data.get("media")
    if isinstance(media, dict):
        photo = media.get("photo")
        if isinstance(photo, dict):
            return photo
    return None


def document_attributes(document):
    if not isinstance(document, dict):
        return []
    attributes = document.get("attributes")
    if not isinstance(attributes, list):
        return []
    return [attribute for attribute in attributes if isinstance(attribute, dict)]


def document_attribute(document, name):
    for attribute in document_attributes(document):
        if attribute.get("_") == name:
            return attribute
    return None


def media_kind(value):
    media = message_media(value)
    if media is None:
        if message_photo(value) is not None:
            return "photo"
        if message_document(value) is not None:
            return _document_kind(message_document(value))
        return None
    constructor = media.get("_")
    if constructor == "messageMediaPhoto":
        return "photo"
    if constructor in ("messageMediaDocument", "messageMediaFile"):
        document = message_document(value)
        return _document_kind(document) if document is not None else "document"
    if constructor in ("messageMediaGeo", "messageMediaGeoLive"):
        return "geo"
    if constructor == "messageMediaContact":
        return "contact"
    if constructor == "messageMediaPoll":
        return "poll"
    if constructor == "messageMediaWebPage":
        return "webpage"
    if constructor == "messageMediaGame":
        return "game"
    if constructor == "messageMediaUnsupported":
        return "unsupported"
    if message_document(value) is not None:
        return _document_kind(message_document(value))
    if message_photo(value) is not None:
        return "photo"
    return "document" if constructor else None


def _document_kind(document):
    if document is None:
        return None
    if document_attribute(document, "documentAttributeSticker") is not None:
        return "sticker"
    if document_attribute(document, "documentAttributeAnimated") is not None:
        return "gif"
    audio = document_attribute(document, "documentAttributeAudio")
    if audio is not None:
        return "voice" if audio.get("voice") else "music"
    video = document_attribute(document, "documentAttributeVideo")
    if video is not None:
        return "round_video" if video.get("round_message") else "video"
    return "document"


def media_duration(value):
    document = message_document(value)
    if document is None:
        return 0
    for name in ("documentAttributeAudio", "documentAttributeVideo"):
        attribute = document_attribute(document, name)
        if attribute is not None and attribute.get("duration") is not None:
            return attribute.get("duration")
    return 0


def file_name(value):
    document = message_document(value)
    if isinstance(document, dict):
        name = document.get("file_name") or document.get("name")
        if name:
            return name
    data = _data(value)
    if isinstance(data, dict):
        return data.get("file_name")
    return None


def file_size(value):
    document = message_document(value)
    if isinstance(document, dict):
        size = document.get("size")
        if size is None:
            size = document.get("file_size")
        if size is not None:
            return size
    data = _data(value)
    if isinstance(data, dict):
        return data.get("file_size")
    return 0


def is_voice(value):
    return media_kind(value) == "voice"


def is_music(value):
    return media_kind(value) == "music"


def is_video(value):
    return media_kind(value) == "video"


def is_round_video(value):
    return media_kind(value) == "round_video"


def is_gif(value):
    return media_kind(value) == "gif"


def is_sticker(value):
    return media_kind(value) == "sticker"


def is_photo(value):
    return media_kind(value) == "photo"


def is_document(value):
    return media_kind(value) in (
        "document",
        "voice",
        "music",
        "video",
        "round_video",
        "gif",
        "sticker",
    )


def has_photo(value):
    return message_photo(value) is not None


def has_document(value):
    return message_document(value) is not None
