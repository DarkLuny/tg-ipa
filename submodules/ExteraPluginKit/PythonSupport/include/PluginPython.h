/*
 * This is the iOS counterpart of the exteraGram plugins SDK.
 *
 * Thin CPython bridge.  All policy lives in Python (`_extera_runtime`) and all
 * UI/Telegram work lives in Swift (`PluginHostAPI`); this file only starts the
 * interpreter, imports the runtime, calls functions on it and converts JSON
 * strings at the boundary.
 *
 * The ABI is deliberately generic:
 *
 *     char *pl_python_call_json("load_plugin", "[\"id\", \"/path\"]", &error)
 *
 * so adding a runtime operation needs no C change.  The single host callback,
 * `pl_host_call`, is implemented by Swift and declared weak here so the module
 * can also be linked into a test harness without the app.
 *
 * Licensed under the GNU GPL v2 or later, like the rest of this repository.
 */

#ifndef EXTERA_PLUGIN_PYTHON_H
#define EXTERA_PLUGIN_PYTHON_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Returns 1 when the binary was linked with a CPython runtime. */
int pl_python_available(void);

/* Starts the interpreter and imports the runtime.  Returns 0 on success. */
int pl_python_start(const char *sdk_path,
                    const char *plugins_path,
                    const char *files_path,
                    const char *stdlib_path,
                    char **error);

/* Calls `_extera_runtime.<function>(*json.loads(args_json))`.
 * Returns a malloc'd JSON string, or NULL with `error` set. */
char *pl_python_call_json(const char *function,
                          const char *args_json,
                          char **error);

/* Invokes a callback retained by `extera_ios.retain`. */
char *pl_python_invoke(const char *handle,
                       const char *payload,
                       char **error);

/* Releases a string returned by this file. */
void pl_python_free(char *value);

/* Last interpreter error, malloc'd. */
char *pl_python_last_error(void);

/* Stops plugin instances (the interpreter itself stays alive for reuse). */
void pl_python_stop(void);

/*
 * Implemented by the Swift host.  Returns a malloc'd UTF-8 JSON string.
 * The weak definition below keeps the module linkable without the app.
 */
char *pl_host_call(const char *method, const char *payload);

#ifdef __cplusplus
}
#endif

#endif /* EXTERA_PLUGIN_PYTHON_H */
