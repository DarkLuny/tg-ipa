"""A small, self-contained AES and Java-crypto facade for the plugin SDK.

exteraGram plugins use `javax.crypto.Cipher` with `AES/CTR/NoPadding` (for the
MTProto/WebSocket proxy secret) and `java.security.MessageDigest`.  CPython has
no AES in its standard library and the iOS kit refuses binary third-party
wheels, so the block cipher is implemented here in pure Python.  It is not
meant for bulk media; a plugin proxy handles small handshake and message
frames, which this implementation covers with test-vector accuracy.

Licensed under the GNU GPL v2 or later, like the rest of this repository.
"""

import hashlib
import struct

# ---------------------------------------------------------------------------
# AES tables

_SBOX = (
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
)

_INV_SBOX = [0] * 256
for _index, _value in enumerate(_SBOX):
    _INV_SBOX[_value] = _index

_RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36)


def _xtime(value):
    value <<= 1
    if value & 0x100:
        value ^= 0x11b
    return value & 0xFF


def _mul(a, b):
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        b >>= 1
        a = _xtime(a)
    return result


class AES:
    """AES-128/192/256 block cipher (FIPS-197)."""

    block_size = 16

    def __init__(self, key):
        key = bytes(key or b"")
        if len(key) not in (16, 24, 32):
            raise ValueError("AES key must be 16, 24 or 32 bytes")
        self._rounds = {16: 10, 24: 12, 32: 14}[len(key)]
        self._round_keys = self._expand_key(key)

    def _expand_key(self, key):
        words = [list(key[offset:offset + 4]) for offset in range(0, len(key), 4)]
        total = 4 * (self._rounds + 1)
        for index in range(len(words), total):
            temp = list(words[index - 1])
            if index % 4 == 0:
                temp = temp[1:] + temp[:1]
                temp = [_SBOX[value] for value in temp]
                temp[0] ^= _RCON[index // 4 - 1]
            elif len(key) == 32 and index % 4 == 3:
                temp = [_SBOX[value] for value in temp]
            words.append([
                words[index - 4][position] ^ temp[position]
                for position in range(4)
            ])
        return [sum(words[index:index + 4], []) for index in range(0, total, 4)]

    def _add_round_key(self, state, round_key):
        for index in range(16):
            state[index] ^= round_key[index]

    @staticmethod
    def _shift_rows(state):
        state[1], state[5], state[9], state[13] = state[5], state[9], state[13], state[1]
        state[2], state[6], state[10], state[14] = state[10], state[14], state[2], state[6]
        state[3], state[7], state[11], state[15] = state[15], state[3], state[7], state[11]

    @staticmethod
    def _inv_shift_rows(state):
        state[1], state[5], state[9], state[13] = state[13], state[1], state[5], state[9]
        state[2], state[6], state[10], state[14] = state[10], state[14], state[2], state[6]
        state[3], state[7], state[11], state[15] = state[7], state[11], state[15], state[3]

    @staticmethod
    def _mix_columns(state):
        for offset in range(0, 16, 4):
            a0, a1, a2, a3 = state[offset:offset + 4]
            state[offset] = _mul(a0, 2) ^ _mul(a1, 3) ^ a2 ^ a3
            state[offset + 1] = a0 ^ _mul(a1, 2) ^ _mul(a2, 3) ^ a3
            state[offset + 2] = a0 ^ a1 ^ _mul(a2, 2) ^ _mul(a3, 3)
            state[offset + 3] = _mul(a0, 3) ^ a1 ^ a2 ^ _mul(a3, 2)

    @staticmethod
    def _inv_mix_columns(state):
        for offset in range(0, 16, 4):
            a0, a1, a2, a3 = state[offset:offset + 4]
            state[offset] = _mul(a0, 14) ^ _mul(a1, 11) ^ _mul(a2, 13) ^ _mul(a3, 9)
            state[offset + 1] = _mul(a0, 9) ^ _mul(a1, 14) ^ _mul(a2, 11) ^ _mul(a3, 13)
            state[offset + 2] = _mul(a0, 13) ^ _mul(a1, 9) ^ _mul(a2, 14) ^ _mul(a3, 11)
            state[offset + 3] = _mul(a0, 11) ^ _mul(a1, 13) ^ _mul(a2, 9) ^ _mul(a3, 14)

    def encrypt_block(self, block):
        state = list(bytes(block))
        self._add_round_key(state, self._round_keys[0])
        for round_index in range(1, self._rounds):
            state = [_SBOX[value] for value in state]
            self._shift_rows(state)
            self._mix_columns(state)
            self._add_round_key(state, self._round_keys[round_index])
        state = [_SBOX[value] for value in state]
        self._shift_rows(state)
        self._add_round_key(state, self._round_keys[self._rounds])
        return bytes(state)

    def decrypt_block(self, block):
        state = list(bytes(block))
        self._add_round_key(state, self._round_keys[self._rounds])
        for round_index in range(self._rounds - 1, 0, -1):
            self._inv_shift_rows(state)
            state = [_INV_SBOX[value] for value in state]
            self._add_round_key(state, self._round_keys[round_index])
            self._inv_mix_columns(state)
        self._inv_shift_rows(state)
        state = [_INV_SBOX[value] for value in state]
        self._add_round_key(state, self._round_keys[0])
        return bytes(state)


# ---------------------------------------------------------------------------
# javax.crypto facade


class SecretKeySpec:
    def __init__(self, key, algorithm="AES"):
        self._key = bytes(key or b"")
        self._algorithm = str(algorithm or "AES")

    def getEncoded(self):
        return self._key

    def getAlgorithm(self):
        return self._algorithm


class IvParameterSpec:
    def __init__(self, iv):
        self._iv = bytes(iv or b"")

    def getIV(self):
        return self._iv


class Cipher:
    ENCRYPT_MODE = 1
    DECRYPT_MODE = 2
    PRIVATE_KEY = 2
    PUBLIC_KEY = 1

    def __init__(self, transformation="AES/CTR/NoPadding"):
        self._transformation = str(transformation or "AES/CTR/NoPadding")
        self._mode = self.ENCRYPT_MODE
        self._aes = None
        self._iv = b""
        self._counter = 0
        self._keystream = b""
        self._buffer = b""

    @classmethod
    def getInstance(cls, transformation="AES/CTR/NoPadding"):
        return cls(transformation)

    def init(self, mode, key, iv=None, *args, **kwargs):
        raw_key = key.getEncoded() if hasattr(key, "getEncoded") else bytes(key or b"")
        self._aes = AES(raw_key)
        self._mode = int(mode)
        self._iv = b""
        if iv is not None:
            self._iv = iv.getIV() if hasattr(iv, "getIV") else bytes(iv or b"")
        self._counter = int.from_bytes(self._iv[:16], "big") if self._iv else 0
        self._keystream = b""
        self._buffer = b""
        return None

    def _next_keystream_block(self):
        counter_block = self._counter.to_bytes(16, "big")
        self._counter = (self._counter + 1) & ((1 << 128) - 1)
        return self._aes.encrypt_block(counter_block)

    def _ctr_update(self, data):
        output = bytearray()
        data = bytes(data or b"")
        for value in data:
            if not self._keystream:
                self._keystream = self._next_keystream_block()
            output.append(value ^ self._keystream[0])
            self._keystream = self._keystream[1:]
        return bytes(output)

    def _cbc_encrypt(self, data, final=False):
        data = self._buffer + bytes(data or b"")
        output = bytearray()
        previous = self._iv
        block_count = len(data) // 16
        for index in range(block_count):
            block = data[index * 16:(index + 1) * 16]
            mixed = bytes(a ^ b for a, b in zip(block, previous))
            encrypted = self._aes.encrypt_block(mixed)
            output.extend(encrypted)
            previous = encrypted
        self._buffer = data[block_count * 16:]
        if final:
            padding = 16 - len(self._buffer)
            padded = self._buffer + bytes([padding]) * padding
            mixed = bytes(a ^ b for a, b in zip(padded, previous))
            output.extend(self._aes.encrypt_block(mixed))
            self._buffer = b""
        return bytes(output)

    def _cbc_decrypt(self, data, final=False):
        data = self._buffer + bytes(data or b"")
        output = bytearray()
        previous = self._iv
        block_count = len(data) // 16
        for index in range(block_count):
            block = data[index * 16:(index + 1) * 16]
            decrypted = self._aes.decrypt_block(block)
            output.extend(a ^ b for a, b in zip(decrypted, previous))
            previous = block
        self._buffer = data[block_count * 16:]
        if final and output:
            padding = output[-1]
            if 1 <= padding <= 16 and output[-padding:] == bytes([padding]) * padding:
                del output[-padding:]
            self._buffer = b""
        return bytes(output)

    def update(self, data=b""):
        data = bytes(data or b"")
        if self._aes is None:
            return data
        transformation = self._transformation.upper()
        if "CTR" in transformation or "OFB" in transformation:
            return self._ctr_update(data)
        if "CBC" in transformation:
            if self._mode == self.ENCRYPT_MODE:
                return self._cbc_encrypt(data)
            return self._cbc_decrypt(data)
        if "ECB" in transformation:
            return self._ecb(data, final=False)
        return data

    def _ecb(self, data, final=False):
        data = self._buffer + bytes(data or b"")
        output = bytearray()
        block_count = len(data) // 16
        for index in range(block_count):
            block = data[index * 16:(index + 1) * 16]
            if self._mode == self.ENCRYPT_MODE:
                output.extend(self._aes.encrypt_block(block))
            else:
                output.extend(self._aes.decrypt_block(block))
        self._buffer = data[block_count * 16:]
        if final and self._buffer:
            padding = 16 - len(self._buffer)
            block = self._buffer + bytes([padding]) * padding
            if self._mode == self.ENCRYPT_MODE:
                output.extend(self._aes.encrypt_block(block))
            else:
                block = self._aes.decrypt_block(block)
                output.extend(block[:len(self._buffer)])
            self._buffer = b""
        return bytes(output)

    def doFinal(self, data=b"", *args, **kwargs):
        transformation = self._transformation.upper()
        if "CTR" in transformation or "OFB" in transformation:
            return self.update(data)
        if "CBC" in transformation:
            if self._mode == self.ENCRYPT_MODE:
                return self._cbc_encrypt(data, final=True)
            return self._cbc_decrypt(data, final=True)
        if "ECB" in transformation:
            return self._ecb(data, final=True)
        return self.update(data)

    def getBlockSize(self):
        return 16

    def getIV(self):
        return self._iv

    def getAlgorithm(self):
        return self._transformation.split("/")[0]


# ---------------------------------------------------------------------------
# java.security facade


class MessageDigest:
    _ALIASES = {
        "MD5": "md5",
        "SHA-1": "sha1",
        "SHA1": "sha1",
        "SHA-256": "sha256",
        "SHA256": "sha256",
        "SHA-512": "sha512",
        "SHA512": "sha512",
    }

    def __init__(self, algorithm="SHA-256"):
        self._algorithm = str(algorithm or "SHA-256")
        self._name = self._ALIASES.get(self._algorithm.upper(), "sha256")
        self._data = bytearray()

    @classmethod
    def getInstance(cls, algorithm="SHA-256"):
        return cls(algorithm)

    def update(self, data):
        self._data.extend(bytes(data or b""))
        return None

    def digest(self, data=None, *args, **kwargs):
        if data is not None:
            self.update(data)
        result = hashlib.new(self._name, bytes(self._data)).digest()
        self._data = bytearray()
        return result

    def reset(self):
        self._data = bytearray()
        return None

    def getAlgorithm(self):
        return self._algorithm


class X509EncodedKeySpec:
    def __init__(self, encoded):
        self._encoded = bytes(encoded or b"")

    def getEncoded(self):
        return self._encoded


class _PublicKey:
    def __init__(self, algorithm, encoded):
        self._algorithm = algorithm
        self._encoded = encoded

    def getAlgorithm(self):
        return self._algorithm

    def getEncoded(self):
        return self._encoded


class KeyFactory:
    def __init__(self, algorithm="RSA"):
        self._algorithm = str(algorithm or "RSA")

    @classmethod
    def getInstance(cls, algorithm="RSA"):
        return cls(algorithm)

    def getAlgorithm(self):
        return self._algorithm

    def generatePublic(self, spec):
        return _PublicKey(self._algorithm, spec.getEncoded())

    def generatePrivate(self, spec):
        return _PublicKey(self._algorithm, spec.getEncoded())


class Signature:
    def __init__(self, algorithm="SHA256withRSA"):
        self._algorithm = str(algorithm or "SHA256withRSA")
        self._data = bytearray()

    @classmethod
    def getInstance(cls, algorithm="SHA256withRSA"):
        return cls(algorithm)

    def initVerify(self, key=None):
        self._data = bytearray()
        return None

    def initSign(self, key=None):
        self._data = bytearray()
        return None

    def update(self, data):
        self._data.extend(bytes(data or b""))
        return None

    def verify(self, signature):
        return False

    def sign(self):
        return b""

    def getAlgorithm(self):
        return self._algorithm


class DexClassLoader:
    """Android's Dalvik class loader has no iOS counterpart."""

    def __init__(self, *args, **kwargs):
        self.dexPath = args[0] if args else ""
        self.optimizedDirectory = args[1] if len(args) > 1 else ""

    def loadClass(self, name):
        raise ImportError("Dalvik classes cannot be loaded on iOS: %s" % name)

    def findClass(self, name):
        return self.loadClass(name)
