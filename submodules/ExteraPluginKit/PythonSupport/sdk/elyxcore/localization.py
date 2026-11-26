# This is the source code of the exteraGram plugins SDK.
#
# We do not and cannot prevent the use of our code,
# but be respectful and credit the original author.
#
# Copyright @exteraGram, 2022-2026
#
# Licensed under the GNU GPL v. 3 or later, with the additional terms
# in ADDITIONAL_TERMS.md at the root of the repository.

from __future__ import annotations

import warnings
from typing import Any, Dict, List, Optional, overload

import plugin_settings
from elyxcore.utils import LazyDict, gen

try:
    from android.view import View
    from java.lang import Runnable as JavaRunnable
    from org.telegram.messenger import Utilities

    OnClickListener = gen(View.OnClickListener, "onClick")
    Runnable = gen(JavaRunnable, "run")
    Callback = gen(Utilities.Callback, "run")
    Callback2 = gen(Utilities.Callback2, "run")
    Callback3 = gen(Utilities.Callback3, "run")
    CallbackReturn = gen(Utilities.CallbackReturn, "run", True)
except Exception:
    OnClickListener = None
    Runnable = None
    Callback = None
    Callback2 = None
    Callback3 = None
    CallbackReturn = None

warnings.filterwarnings("ignore", category=SyntaxWarning)

ELYX_ID = "elyxcore"
_debug_logs = False


def dlog(msg: str) -> None:
    if _debug_logs:
        try:
            from android_utils import log as logcat

            logcat(msg)
        except Exception:
            pass

############### Strings PART ################
class Strings(LazyDict):
    def __init__(self, all_strings: Dict[str, Dict]):
        super().__init__()
        self.all_strings = all_strings

    @staticmethod
    def get_current_language():
        configured = plugin_settings.get_setting(ELYX_ID, "language", "") or ""
        if configured:
            return str(configured)
        try:
            import extera_ios

            value = extera_ios.host("locale.language")
            if isinstance(value, str) and value:
                return value.split("-")[0].split("_")[0]
        except Exception:
            pass
        try:
            import os

            return (os.environ.get("LANG") or "en").split(".")[0].split("_")[0] or "en"
        except Exception:
            return "en"

    def __getitem__(self, key):
        if key == "all_strings":
            return super().__getitem__(key)

        res = self.all_strings.get(self.get_current_language(),
                                   self.all_strings.get("en", self.all_strings)).get(key, None)
        if res is None:
            res = self.all_strings.get("en", self.all_strings).get(key, None)

        if res is None:
            return key

        return res

    def __setitem__(self, key, value):
        if key != "all_strings":
            raise RuntimeError("Strings are read-only")
        super().__setitem__(key, value)

    @overload
    def get(self, key: str) -> Any:
        ...

    # noinspection PyMethodOverriding
    @overload
    def get(self, key: str, default) -> Any:
        ...

    def get(self, key: str, default=None) -> Any:
        return self.get_with_locale(key, default)

    def get_with_locale(self, key: str, default=None, locale: str = None) -> Any:
        res = self.all_strings.get(locale or self.get_current_language(),
                                   self.all_strings.get("en", self.all_strings)).get(key, default)
        if res is None:
            if default is not None:
                return default

            res = self.all_strings.get("en", self.all_strings).get(key, default)

        if res is None:
            return key

        return res

    def __call__(self, key: str, *args, default: Optional[str] = None, locale: str = None, **kwargs):
        result = self.get_with_locale(key, default, locale)
        if isinstance(result, str) and (args or kwargs):
            result = result.format(*args, **kwargs)

        return result

    @staticmethod
    def pluralization_string(number: int, words: List[str]) -> str:
        if number % 10 == 1 and number % 100 != 11:
            return f"{number} {words[0]}"
        elif 2 <= number % 10 <= 4 and (number % 100 < 10 or number % 100 >= 20):
            return f"{number} {words[1]}"
        else:
            return f"{number} {words[2]}"

    def pluralize(self, number: int, key: str) -> str:
        return self.pluralization_string(number, self(key))


# noinspection SpellCheckingInspection
strings = Strings(all_strings={
    "en": {
        "allowed_extensions": "Allowed archive extentensions",
        "allowed_extensions_desc": "Comma separated list of allowed archive extentensions. For example: elyx,cactus",
        "archive_password_title": "Archive encryption password",
        "enter_password": "Enter password",
        "decrypt": "Decrypt",
        "failed_validate": "Failed to validate plugin",
        "error_plural": ["error", "errors", "errors"],
        "copy": "Copy",
        "failed_install": "Failed to install plugin",
        "version": "Version",
        "trusted_source": "Trusted source",
        "unknown_source": "Unknown source",
        "update_plugin": "Update plugin",
        "install_plugin": "Install plugin",
        "install_required_plugins": "Required plugins are missing",
        "update_required_plugins": "Required plugins are missing",
        "install_required_desc": "This plugin needs extra plugins to work properly",
        "update_required_desc": "This plugin needs extra plugins to work properly",
        "language": "Force language for plugins locals (en/ru/...)",
        "language_desc": "Set empty to use app language",
        "debug_logs": "Debug logs",
        "debug_logs_desc": "Enable verbose logging for ElyxCore",
        "install_from_file": "Install from file",
    },
    "ru": {
        "allowed_extensions": "Разрешённые расширения архивов",
        "allowed_extensions_desc": "Список разрешённых расширений архивов. Например: elyx,cactus",
        "archive_password_title": "Пароль зашифрованного архива",
        "enter_password": "Введите пароль",
        "decrypt": "Расшифровать",
        "failed_validate": "Не удалось проверить плагин",
        "error_plural": ["ошибка", "ошибки", "ошибок"],
        "copy": "Копировать",
        "failed_install": "Не удалось установить плагин",
        "version": "Версия",
        "trusted_source": "Доверенный источник",
        "unknown_source": "Неизвестный источник",
        "update_plugin": "Обновить плагин",
        "install_plugin": "Установить плагин",
        "install_required_plugins": "Необходимо установить доп. плагины",
        "update_required_plugins": "Необходимо установить доп. плагины",
        "install_required_desc": "Для работы плагина нужны доп. плагины",
        "update_required_desc": "Для работы плагина нужны доп. плагины",
        "language": "Язык для плагинов (en/ru/...)",
        "language_desc": "Оставьте пустым, чтобы использовать язык приложения",
        "debug_logs": "Дебаг логи",
        "debug_logs_desc": "Включить подробное логирование ElyxCore",
        "install_from_file": "Установить из файла",
    }
})


############### END Strings PART ################
