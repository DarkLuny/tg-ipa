# This is the iOS counterpart of the exteraGram plugins SDK.
#
# Android's `MediaMetadataRetriever` reads container metadata through
# MediaMetadataRetriever/FFmpeg.  iOS has AVFoundation, but the plugin host has
# no synchronous bridge to it, so this module reads the common containers
# directly (WAV, FLAC, Ogg/Opus, MP3, MP4/M4A/MOV and still images).  It is the
# same information `extractMetadata` returns on Android, without decoding a
# frame (`getFrameAtTime` still answers `None`).
#
# Licensed under the GNU GPL v2 or later, like the rest of this repository.

import mimetypes
import os
import struct


_IMAGE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".heic",
    ".heif",
)

_VIDEO_EXTENSIONS = (".mp4", ".m4v", ".mov", ".3gp", ".mkv", ".webm")
_AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus")

_MIME_TYPES = {
    ".wav": "audio/x-wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".3gp": "video/3gpp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".heic": "image/heic",
    ".heif": "image/heic",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
}


def _mime_type(path):
    extension = os.path.splitext(str(path))[1].lower()
    if extension in _MIME_TYPES:
        return _MIME_TYPES[extension]
    return mimetypes.guess_type(str(path))[0] or ""


def _empty(path):
    return {
        "path": path,
        "mime_type": _mime_type(path),
        "duration": 0.0,
        "width": 0,
        "height": 0,
        "rotation": 0,
        "title": "",
        "artist": "",
        "has_video": False,
        "has_audio": False,
    }


def _read_file(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return b""


def _syncsafe(value):
    return (
        ((value[0] & 0x7F) << 21)
        | ((value[1] & 0x7F) << 14)
        | ((value[2] & 0x7F) << 7)
        | (value[3] & 0x7F)
    )


def _decode_text(payload):
    if not payload:
        return ""
    encoding = payload[0]
    body = payload[1:]
    try:
        if encoding == 0:
            return body.decode("latin-1", "ignore").strip("\x00 ")
        if encoding == 1:
            return body.decode("utf-16", "ignore").strip("\x00 ")
        if encoding == 2:
            return body.decode("utf-16-be", "ignore").strip("\x00 ")
        if encoding == 3:
            return body.decode("utf-8", "ignore").strip("\x00 ")
    except Exception:
        pass
    return ""


# -- WAV ---------------------------------------------------------------------


def _parse_wav(data, result):
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return
    position = 12
    byte_rate = 0
    data_size = 0
    while position + 8 <= len(data):
        chunk = data[position:position + 4]
        size = struct.unpack("<I", data[position + 4:position + 8])[0]
        body = data[position + 8:position + 8 + size]
        if chunk == b"fmt " and len(body) >= 12:
            byte_rate = struct.unpack("<I", body[8:12])[0]
        elif chunk == b"data":
            data_size = size
            break
        position += 8 + size + (size & 1)
    if byte_rate > 0:
        result["duration"] = float(data_size) / float(byte_rate)
    result["has_audio"] = True


# -- FLAC --------------------------------------------------------------------


def _parse_flac(data, result):
    if data[:4] != b"fLaC":
        return
    position = 4
    while position + 4 <= len(data):
        header = data[position]
        block_type = header & 0x7F
        length = int.from_bytes(data[position + 1:position + 4], "big")
        body = data[position + 4:position + 4 + length]
        if block_type == 0 and len(body) >= 18:
            packed = int.from_bytes(body[10:18], "big")
            sample_rate = (packed >> 44) & 0xFFFFF
            total_samples = packed & 0xFFFFFFFFF
            if sample_rate:
                result["duration"] = float(total_samples) / float(sample_rate)
            result["has_audio"] = True
            break
        if header & 0x80:
            break
        position += 4 + length


# -- Ogg / Opus --------------------------------------------------------------


def _parse_ogg(data, result):
    if data[:4] != b"OggS":
        return
    sample_rate = 0
    last_granule = 0
    position = 0
    first_packet = True
    while position + 27 <= len(data):
        if data[position:position + 4] != b"OggS":
            break
        granule = int.from_bytes(data[position + 6:position + 14], "little")
        if granule > 0:
            last_granule = granule
        segments = data[position + 26]
        payload_start = position + 27 + segments
        if first_packet and payload_start < len(data):
            packet = data[payload_start:payload_start + 64]
            if packet[:7] == b"\x01vorbis" and len(packet) >= 16:
                sample_rate = int.from_bytes(packet[12:16], "little")
            elif packet[:8] == b"OpusHead" and len(packet) >= 12:
                sample_rate = 48000
            first_packet = False
        size = 27 + segments
        for index in range(segments):
            if position + 27 + index < len(data):
                size += data[position + 27 + index]
        if size <= 0:
            break
        position += size
    if sample_rate and last_granule:
        result["duration"] = float(last_granule) / float(sample_rate)
    result["has_audio"] = True


# -- MP3 ---------------------------------------------------------------------


_MP3_BITRATES = {
    (1, 1): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    (1, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    (1, 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    (2, 1): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    (2, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    (2, 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}

_MP3_SAMPLE_RATES = {
    3: [44100, 48000, 32000],
    2: [22050, 24000, 16000],
    0: [11025, 12000, 8000],
}


def _parse_id3(data, result):
    if data[:3] != b"ID3" or len(data) < 10:
        return 0
    size = _syncsafe(data[6:10])
    position = 10
    end = min(len(data), 10 + size)
    version = data[3]
    while position + 10 <= end:
        frame = data[position:position + 4]
        if not frame.strip(b"\x00"):
            break
        if version >= 4:
            frame_size = _syncsafe(data[position + 4:position + 8])
        else:
            frame_size = struct.unpack(">I", data[position + 4:position + 8])[0]
        body = data[position + 10:position + 10 + frame_size]
        if frame == b"TIT2":
            result["title"] = _decode_text(body)
        elif frame == b"TPE1":
            result["artist"] = _decode_text(body)
        position += 10 + frame_size
    return 10 + size


def _parse_mp3(data, result):
    start = _parse_id3(data, result)
    position = start
    while position + 4 <= len(data):
        if data[position] == 0xFF and (data[position + 1] & 0xE0) == 0xE0:
            break
        position += 1
    if position + 4 > len(data):
        return
    header = data[position:position + 4]
    version_bits = (header[1] >> 3) & 0x03
    layer_bits = (header[1] >> 1) & 0x03
    bitrate_index = (header[2] >> 4) & 0x0F
    sample_index = (header[2] >> 2) & 0x03
    if version_bits == 1 or layer_bits == 0 or bitrate_index == 0 or bitrate_index == 15:
        return
    version_group = 1 if version_bits == 3 else 2
    if sample_index >= len(_MP3_SAMPLE_RATES.get(version_bits, [])):
        return
    sample_rate = _MP3_SAMPLE_RATES[version_bits][sample_index]
    table = _MP3_BITRATES.get((version_group, layer_bits))
    if not table:
        return
    bitrate = table[bitrate_index] * 1000
    if sample_rate <= 0 or bitrate <= 0:
        return
    audio_size = max(0, len(data) - position)
    result["duration"] = float(audio_size) * 8.0 / float(bitrate)
    result["has_audio"] = True


# -- MP4 / M4A / MOV ---------------------------------------------------------


def _boxes(data, start=0, end=None):
    end = len(data) if end is None else end
    position = start
    while position + 8 <= end:
        size = struct.unpack(">I", data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        header = 8
        if size == 1:
            if position + 16 > end:
                break
            size = struct.unpack(">Q", data[position + 8:position + 16])[0]
            header = 16
        elif size == 0:
            size = end - position
        if size < header or position + size > end:
            break
        yield kind, data[position + header:position + size]
        position += size


def _parse_mp4(data, result):
    for kind, body in _boxes(data):
        if kind != b"moov":
            continue
        for child, payload in _boxes(body):
            if child == b"mvhd":
                _parse_mvhd(payload, result)
            elif child == b"trak":
                _parse_trak(payload, result)
            elif child == b"udta":
                _parse_udta(payload, result)
        break


def _parse_mvhd(body, result):
    if len(body) < 20:
        return
    version = body[0]
    if version == 1:
        if len(body) < 32:
            return
        timescale = struct.unpack(">I", body[20:24])[0]
        duration = struct.unpack(">Q", body[24:32])[0]
    else:
        timescale = struct.unpack(">I", body[12:16])[0]
        duration = struct.unpack(">I", body[16:20])[0]
    if timescale:
        result["duration"] = float(duration) / float(timescale)


def _parse_trak(body, result):
    for kind, payload in _boxes(body):
        if kind == b"tkhd":
            _parse_tkhd(payload, result)
        elif kind == b"mdia":
            for child, media in _boxes(payload):
                if child == b"hdlr" and len(media) >= 12:
                    handler = media[8:12]
                    if handler == b"vide":
                        result["has_video"] = True
                    elif handler == b"soun":
                        result["has_audio"] = True
                elif child == b"minf":
                    for box, content in _boxes(media):
                        if box == b"stbl":
                            _parse_stbl(content, result)


def _parse_tkhd(body, result):
    if len(body) < 84:
        return
    version = body[0]
    offset = 88 if version == 1 else 76
    if len(body) < offset + 8:
        return
    width = struct.unpack(">I", body[offset:offset + 4])[0] / 65536.0
    height = struct.unpack(">I", body[offset + 4:offset + 8])[0] / 65536.0
    if width > 0 and height > 0 and not result["width"]:
        result["width"] = int(round(width))
        result["height"] = int(round(height))
    matrix_offset = offset - 36
    try:
        a = struct.unpack(">i", body[matrix_offset:matrix_offset + 4])[0] / 65536.0
        b = struct.unpack(">i", body[matrix_offset + 4:matrix_offset + 8])[0] / 65536.0
        if a or b:
            import math

            result["rotation"] = int(round(math.degrees(math.atan2(b, a)))) % 360
    except Exception:
        pass


def _parse_stbl(body, result):
    for kind, payload in _boxes(body):
        if kind != b"stsd" or len(payload) < 16:
            continue
        position = 8
        while position + 8 <= len(payload):
            size = struct.unpack(">I", payload[position:position + 4])[0]
            if size < 8 or position + size > len(payload):
                break
            codec = payload[position + 4:position + 8]
            if codec in (b"avc1", b"avc3", b"hvc1", b"hev1", b"mp4v", b"vp09"):
                result["has_video"] = True
            elif codec in (b"mp4a", b"alac", b"ac-3", b"ec-3", b"Opus"):
                result["has_audio"] = True
            position += size


def _parse_udta(body, result):
    for kind, payload in _boxes(body):
        if kind == b"meta":
            if len(payload) < 4:
                continue
            for box, content in _boxes(payload, 4):
                if box != b"ilst":
                    continue
                for item, value in _boxes(content):
                    if item not in (b"\xa9nam", b"\xa9ART"):
                        continue
                    for data_kind, data_body in _boxes(value):
                        if data_kind != b"data" or len(data_body) < 8:
                            continue
                        text = data_body[8:].decode("utf-8", "ignore").strip("\x00 ")
                        if item == b"\xa9nam":
                            result["title"] = text
                        else:
                            result["artist"] = text


# -- Images ------------------------------------------------------------------


def _image_dimensions(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8X":
            return (
                1 + int.from_bytes(data[24:27], "little"),
                1 + int.from_bytes(data[27:30], "little"),
            )
        if chunk == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8 ":
            return (
                int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF,
            )
    if data[:2] == b"\xff\xd8":
        position = 2
        while position + 9 < len(data):
            if data[position] != 0xFF:
                position += 1
                continue
            marker = data[position + 1]
            if marker in (0xD8, 0xD9):
                position += 2
                continue
            length = struct.unpack(">H", data[position + 2:position + 4])[0]
            if marker in (
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            ):
                return (
                    struct.unpack(">H", data[position + 7:position + 9])[0],
                    struct.unpack(">H", data[position + 5:position + 7])[0],
                )
            position += 2 + length
    return 0, 0


def read_metadata(path):
    """Returns the metadata `MediaMetadataRetriever` can report for `path`."""
    result = _empty(str(path))
    extension = os.path.splitext(str(path))[1].lower()
    if extension in _IMAGE_EXTENSIONS:
        data = _read_file(path)
        width, height = _image_dimensions(data)
        result["width"] = width
        result["height"] = height
        return result
    data = _read_file(path)
    if not data:
        return result
    try:
        if extension == ".wav":
            _parse_wav(data, result)
        elif extension == ".flac":
            _parse_flac(data, result)
        elif extension in (".ogg", ".opus"):
            _parse_ogg(data, result)
        elif extension == ".mp3":
            _parse_mp3(data, result)
        elif extension in (".mp4", ".m4a", ".m4v", ".mov", ".3gp"):
            _parse_mp4(data, result)
    except Exception:
        pass
    return result
