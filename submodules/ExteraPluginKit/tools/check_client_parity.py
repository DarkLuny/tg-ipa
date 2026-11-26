#!/usr/bin/env python3
"""Static parity assertions for the exteraGram client bridge.

This does not replace an iOS build. It fails when a public ExteraSettings key
is missing from the Android -> iOS key list, when an Android ExteraConfig key
has no default in the Python facade, or when a host call has no Swift handler.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parents[2]
ANDROID_ROOT = Path(os.environ.get("EXTERAGRAM_ANDROID_ROOT", str(ROOT.parent / "exteraGram-main")))
ANDROID_CONFIG = ANDROID_ROOT / "TMessagesProj" / "src" / "main" / "java" / "com" / "exteragram" / "messenger" / "ExteraConfig.kt"
ANDROID_KEY_SNAPSHOT = TOOLS / "extera_config_keys.json"
SETTINGS = ROOT / "submodules" / "TelegramCore" / "Sources" / "ExteraSettings.swift"
COMPAT = ROOT / "submodules" / "ExteraPluginKit" / "PythonSupport" / "sdk" / "telegram_compat.py"
HOST = ROOT / "submodules" / "ExteraPluginKit" / "Sources" / "PluginHostAPI.swift"

WIRED_KEYS = {
    "disableNumberRounding",
    "formatTimeWithSeconds",
    "relativeLastSeen",
    "filterZalgo",
    "inAppVibration",
    "downloadSpeedBoost",
    "uploadSpeedBoost",
    "hidePhoneNumber",
    "showIdAndDc",
    "defaultProfileTab",
    "hideArchiveFolder",
    "disableUnarchiveSwipe",
    "hideStories",
    "hideActionBarStatus",
    "hideDialogsSearchBar",
    "avatarCorners",
    "tabIcons",
    "hideNavigationBarLabels",
    "replyBackground",
    "replyColors",
    "replyEmoji",
    "tabCounterMode",
    "hideShareButton",
    "showCopyPhotoButton",
    "showReportButton",
    "showClearButton",
    "replaceEditedWithIcon",
    "disableGreetingSticker",
    "hideSendAsPeer",
    "addCommaAfterMention",
    "hideKeyboardOnScroll",
    "stickerTimeMode",
    "stickerSize",
    "stickerShape",
    "doubleTapSeekDuration",
    "hideReactionsInPrivateChats",
    "hideReactionsInChannels",
    "hideReactionsInGroups",
    "alwaysSendInHD",
    "cameraStabilization",
    "cameraMirrorMode",
    "extendedFramesPerSecond",
    "hideCameraTile",
    "hideFloatingButton",
    "enableAdBlock",
}

# A wired key must not only exist in ExteraSettings: the client source has to
# read it at the place that changes behaviour. This catches the common
# regression where a key is added to the settings screen but never consulted.
WIRED_LOCATIONS: list[tuple[str, str, str, int]] = [
    ("disableNumberRounding", "submodules/TelegramPresentationData/Sources/NumericFormat.swift", "ExteraSettings.shared.disableNumberRounding", 1),
    ("formatTimeWithSeconds", "submodules/TextFormat/Sources/DateFormat.swift", "ExteraSettings.shared.formatTimeWithSeconds", 1),
    ("relativeLastSeen", "submodules/TelegramStringFormatting/Sources/PresenceStrings.swift", "ExteraSettings.shared.relativeLastSeen", 1),
    ("filterZalgo", "submodules/TelegramUI/Components/Chat/ChatMessageTextBubbleContentNode/Sources/ChatMessageTextBubbleContentNode.swift", "ExteraSettings.shared.filterZalgo", 1),
    ("inAppVibration", "submodules/TelegramUI/Sources/PluginBootstrap.swift", "ExteraSettings.shared.inAppVibration", 1),
    ("downloadSpeedBoost", "submodules/TelegramCore/Sources/Network/MultipartFetch.swift", "ExteraSettings.shared.downloadSpeedBoost", 1),
    ("uploadSpeedBoost", "submodules/TelegramCore/Sources/Network/MultipartUpload.swift", "ExteraSettings.shared.uploadSpeedBoost", 1),
    ("hidePhoneNumber", "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoHeaderNode.swift", "ExteraSettings.shared.hidePhoneNumber", 1),
    ("showIdAndDc", "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoHeaderNode.swift", "ExteraSettings.shared.showIdAndDc", 1),
    ("defaultProfileTab", "submodules/TelegramUI/Components/PeerInfo/PeerInfoScreen/Sources/PeerInfoData.swift", "ExteraSettings.shared.defaultProfileTab", 1),
    ("hideArchiveFolder", "submodules/ChatListUI/Sources/Node/ChatListNodeEntries.swift", "ExteraSettings.shared.hideArchiveFolder", 1),
    ("disableUnarchiveSwipe", "submodules/ChatListUI/Sources/Node/ChatListItem.swift", "ExteraSettings.shared.disableUnarchiveSwipe", 1),
    ("hideStories", "submodules/ChatListUI/Sources/ChatListControllerNode.swift", "ExteraSettings.shared.hideStories", 1),
    ("hideActionBarStatus", "submodules/TelegramUI/Components/ChatTitleView/Sources/ChatTitleComponent.swift", "ExteraSettings.shared.hideActionBarStatus", 1),
    ("hideDialogsSearchBar", "submodules/TelegramUI/Components/ChatListHeaderComponent/Sources/ChatListNavigationBar.swift", "ExteraSettings.shared.hideDialogsSearchBar", 1),
    ("avatarCorners", "submodules/AvatarNode/Sources/AvatarNode.swift", "ExteraSettings.shared.avatarCorners", 1),
    ("tabIcons", "submodules/TelegramUI/Components/TabBarComponent/Sources/TabBarComponent.swift", "ExteraSettings.shared.tabIcons", 2),
    ("hideNavigationBarLabels", "submodules/TelegramUI/Components/TabBarComponent/Sources/TabBarComponent.swift", "ExteraSettings.shared.hideNavigationBarLabels", 2),
    ("replyBackground", "submodules/TelegramUI/Components/Chat/ChatMessageReplyInfoNode/Sources/ChatMessageReplyInfoNode.swift", "ExteraSettings.shared.replyBackground", 1),
    ("replyColors", "submodules/TelegramUI/Components/Chat/ChatMessageReplyInfoNode/Sources/ChatMessageReplyInfoNode.swift", "ExteraSettings.shared.replyColors", 1),
    ("replyEmoji", "submodules/TelegramUI/Components/Chat/ChatMessageReplyInfoNode/Sources/ChatMessageReplyInfoNode.swift", "ExteraSettings.shared.replyEmoji", 1),
    ("tabCounterMode", "submodules/ChatListUI/Sources/ChatListController.swift", "ExteraSettings.shared.tabCounterMode", 2),
    ("hideShareButton", "submodules/TelegramUI/Components/Chat/ChatMessageBubbleItemNode/Sources/ChatMessageBubbleItemNode.swift", "ExteraSettings.shared.hideShareButton", 1),
    ("hideShareButton", "submodules/TelegramUI/Components/Chat/ChatMessageAnimatedStickerItemNode/Sources/ChatMessageAnimatedStickerItemNode.swift", "ExteraSettings.shared.hideShareButton", 1),
    ("hideShareButton", "submodules/TelegramUI/Components/Chat/ChatMessageStickerItemNode/Sources/ChatMessageStickerItemNode.swift", "ExteraSettings.shared.hideShareButton", 1),
    ("hideShareButton", "submodules/TelegramUI/Components/Chat/ChatMessageInstantVideoItemNode/Sources/ChatMessageInstantVideoItemNode.swift", "ExteraSettings.shared.hideShareButton", 1),
    ("showCopyPhotoButton", "submodules/TelegramUI/Sources/ChatInterfaceStateContextMenus.swift", "ExteraSettings.shared.showCopyPhotoButton", 2),
    ("showReportButton", "submodules/TelegramUI/Sources/ChatInterfaceStateContextMenus.swift", "ExteraSettings.shared.showReportButton", 2),
    ("showClearButton", "submodules/ChatListUI/Sources/ChatListController.swift", "ExteraSettings.shared.showClearButton", 1),
    ("replaceEditedWithIcon", "submodules/TelegramUI/Components/Chat/ChatMessageDateAndStatusNode/Sources/ChatMessageDateAndStatusNode.swift", "ExteraSettings.shared.replaceEditedWithIcon", 1),
    ("disableGreetingSticker", "submodules/TelegramUI/Components/Chat/ChatEmptyNode/Sources/ChatEmptyNode.swift", "ExteraSettings.shared.disableGreetingSticker", 1),
    ("hideSendAsPeer", "submodules/TelegramUI/Components/Chat/ChatTextInputPanelNode/Sources/ChatTextInputPanelNode.swift", "ExteraSettings.shared.hideSendAsPeer", 1),
    ("addCommaAfterMention", "submodules/TelegramUI/Sources/MentionChatInputContextPanelNode.swift", "ExteraSettings.shared.addCommaAfterMention", 1),
    ("hideKeyboardOnScroll", "submodules/TelegramUI/Sources/ChatControllerNode.swift", "ExteraSettings.shared.hideKeyboardOnScroll", 1),
    ("stickerTimeMode", "submodules/TelegramUI/Components/Chat/ChatMessageStickerItemNode/Sources/ChatMessageStickerItemNode.swift", "ExteraSettings.shared.stickerTimeMode", 1),
    ("stickerTimeMode", "submodules/TelegramUI/Components/Chat/ChatMessageAnimatedStickerItemNode/Sources/ChatMessageAnimatedStickerItemNode.swift", "ExteraSettings.shared.stickerTimeMode", 1),
    ("stickerSize", "submodules/TelegramUI/Components/Chat/ChatMessageStickerItemNode/Sources/ChatMessageStickerItemNode.swift", "ExteraSettings.shared.stickerSizeScale()", 1),
    ("stickerSize", "submodules/TelegramUI/Components/Chat/ChatMessageAnimatedStickerItemNode/Sources/ChatMessageAnimatedStickerItemNode.swift", "ExteraSettings.shared.stickerSizeScale()", 1),
    ("stickerShape", "submodules/TelegramUI/Components/Chat/ChatMessageStickerItemNode/Sources/ChatMessageStickerItemNode.swift", "ExteraSettings.shared.stickerShape", 1),
    ("stickerShape", "submodules/TelegramUI/Components/Chat/ChatMessageAnimatedStickerItemNode/Sources/ChatMessageAnimatedStickerItemNode.swift", "ExteraSettings.shared.stickerShape", 1),
    ("doubleTapSeekDuration", "submodules/GalleryUI/Sources/Items/UniversalVideoGalleryItem.swift", "ExteraSettings.shared.doubleTapSeekDurationSeconds()", 1),
    ("hideReactionsInPrivateChats", "submodules/TelegramCore/Sources/ApiUtils/ReactionsMessageAttribute.swift", "ExteraSettings.shared.hideReactionsInPrivateChats", 1),
    ("hideReactionsInChannels", "submodules/TelegramCore/Sources/ApiUtils/ReactionsMessageAttribute.swift", "ExteraSettings.shared.hideReactionsInChannels", 1),
    ("hideReactionsInGroups", "submodules/TelegramCore/Sources/ApiUtils/ReactionsMessageAttribute.swift", "ExteraSettings.shared.hideReactionsInGroups", 1),
    ("alwaysSendInHD", "submodules/MediaPickerUI/Sources/MediaPickerChatMediaSend.swift", "ExteraSettings.shared.alwaysSendInHD", 1),
    ("cameraStabilization", "submodules/Camera/CameraLegacy/Sources/CameraOutput.swift", "ExteraSettings.shared.cameraStabilization", 1),
    ("cameraMirrorMode", "submodules/Camera/CameraLegacy/Sources/CameraOutput.swift", "ExteraSettings.shared.cameraMirrorMode", 1),
    ("extendedFramesPerSecond", "submodules/Camera/CameraLegacy/Sources/LegacyCamera.swift", "ExteraSettings.shared.extendedFramesPerSecond", 1),
    ("hideCameraTile", "submodules/MediaPickerUI/Sources/MediaPickerScreen.swift", "ExteraSettings.shared.hideCameraTile", 1),
    ("hideFloatingButton", "submodules/ChatListUI/Sources/ChatListController.swift", "ExteraSettings.shared.hideFloatingButton", 2),
    ("enableAdBlock", "submodules/TelegramCore/Sources/TelegramEngine/Messages/AdMessages.swift", "ExteraSettings.shared.enableAdBlock", 1),
]


def android_keys() -> set[str]:
    return set(json.loads(ANDROID_KEY_SNAPSHOT.read_text(encoding="utf-8")))


def android_keys_from_source() -> set[str]:
    text = ANDROID_CONFIG.read_text(encoding="utf-8")
    keys = set(re.findall(r"^\s*var\s+([A-Za-z0-9_]+)\s+by\s+", text, re.M))
    keys |= set(re.findall(r"^\s*var\s+([A-Za-z0-9_]+)\s*=\s*", text, re.M))
    keys.discard("pluginsEngine")
    return keys


def python_defaults() -> set[str]:
    tree = ast.parse(COMPAT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ExteraConfig":
            for child in node.body:
                if isinstance(child, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "_DEFAULTS"
                    for target in child.targets
                ):
                    return {
                        key.value
                        for key in child.value.keys
                        if isinstance(key, ast.Constant)
                    }
    raise AssertionError("ExteraConfig._DEFAULTS not found")


def settings_properties() -> set[str]:
    text = SETTINGS.read_text(encoding="utf-8")
    return set(re.findall(r"public var ([A-Za-z0-9_]+)", text))


def settings_android_keys() -> set[str]:
    text = SETTINGS.read_text(encoding="utf-8")
    marker = "public static let androidKeys"
    index = text.find(marker)
    if index < 0:
        raise AssertionError("androidKeys not found")
    start = text.find("= [", index)
    if start < 0:
        raise AssertionError("androidKeys array not found")
    end = text.find("]", start)
    return set(re.findall(r'"([^"]+)"', text[start:end]))


def host_calls() -> set[str]:
    sdk = ROOT / "submodules" / "ExteraPluginKit" / "PythonSupport" / "sdk"
    calls: set[str] = set()
    for path in sdk.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        calls.update(re.findall(r"host\(\s*[\"']([^\"']+)[\"']", text))
    return calls


def host_cases() -> set[str]:
    text = HOST.read_text(encoding="utf-8")
    cases: set[str] = set()
    for match in re.finditer(r"^\s*case\s+(.+?):\s*$", text, re.M):
        cases.update(re.findall(r'"([^"]+)"', match.group(1)))
    return cases


def main() -> int:
    failures: list[str] = []

    android = android_keys()
    android_source = "snapshot"
    if ANDROID_CONFIG.exists():
        android_source = "source"
        source_android = android_keys_from_source()
        if source_android != android:
            failures.append(
                "Android key snapshot drift: "
                f"missing={sorted(android - source_android)} "
                f"extra={sorted(source_android - android)}"
            )

    defaults = python_defaults()
    missing_defaults = sorted(android - defaults)
    if missing_defaults:
        failures.append(f"Android keys without iOS defaults: {missing_defaults}")

    properties = settings_properties()
    listed = settings_android_keys()
    missing_listed = sorted(properties - listed)
    if missing_listed:
        failures.append(f"ExteraSettings properties missing from androidKeys: {missing_listed}")

    missing_wired = sorted(WIRED_KEYS - properties)
    if missing_wired:
        failures.append(f"Wired keys missing from ExteraSettings: {missing_wired}")

    location_keys = {entry[0] for entry in WIRED_LOCATIONS}
    if location_keys != WIRED_KEYS:
        failures.append(
            "Wired key location map mismatch: "
            f"unlocated={sorted(WIRED_KEYS - location_keys)} "
            f"unknown={sorted(location_keys - WIRED_KEYS)}"
        )

    located = 0
    for key, relative_path, needle, minimum in WIRED_LOCATIONS:
        path = ROOT / relative_path
        if not path.exists():
            failures.append(f"{key}: implementation file missing: {relative_path}")
            continue
        count = path.read_text(encoding="utf-8", errors="ignore").count(needle)
        if count < minimum:
            failures.append(
                f"{key}: expected >= {minimum} call site(s) of {needle!r} in "
                f"{relative_path}, found {count}"
            )
        else:
            located += count

    calls = host_calls()
    cases = host_cases()
    missing_cases = sorted(calls - cases)
    if missing_cases:
        failures.append(f"Host calls without Swift cases: {missing_cases}")

    print(f"Android ExteraConfig keys: {len(android)} ({android_source})")
    print(f"Python facade defaults:   {len(defaults)}")
    print(f"ExteraSettings properties:{len(properties)}")
    print(f"Wired keys asserted:      {len(WIRED_KEYS)}")
    print(f"Wired call sites found:   {located}")
    print(f"Host calls / cases:       {len(calls)} / {len(cases)}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1

    print("CLIENT PARITY ASSERTIONS OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
