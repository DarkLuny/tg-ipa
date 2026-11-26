/*
 * This is the iOS counterpart of the exteraGram plugins SDK.
 * See PluginPython.h for the contract.
 *
 * Licensed under the GNU GPL v2 or later, like the rest of this repository.
 */

#include "PluginPython.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#if __has_include(<Python.h>)
#define EXTERA_HAS_PYTHON 1
#include <Python.h>
#elif __has_include(<python3.11/Python.h>)
#define EXTERA_HAS_PYTHON 1
#include <python3.11/Python.h>
#elif __has_include("Python.h")
#define EXTERA_HAS_PYTHON 1
#include "Python.h"
#else
#define EXTERA_HAS_PYTHON 0
#endif

#if defined(__APPLE__)
#define EXTERA_WEAK __attribute__((weak))
#else
#define EXTERA_WEAK
#endif

static int pl_started = 0;
static int pl_verbose = 0;
static char *pl_error = NULL;

/* ------------------------------------------------------------------------- */
/* Strings                                                                   */

static char *pl_strdup(const char *value) {
    if (value == NULL) {
        return NULL;
    }
    size_t length = strlen(value);
    char *copy = (char *)malloc(length + 1);
    if (copy != NULL) {
        memcpy(copy, value, length + 1);
    }
    return copy;
}

static void pl_set_error(const char *format, ...) {
    va_list args;
    va_start(args, format);
    char buffer[2048];
    vsnprintf(buffer, sizeof(buffer), format, args);
    va_end(args);
    free(pl_error);
    pl_error = pl_strdup(buffer);
}

char *pl_python_last_error(void) {
    return pl_error != NULL ? pl_strdup(pl_error) : NULL;
}

void pl_python_free(char *value) {
    free(value);
}

int pl_python_available(void) {
#if EXTERA_HAS_PYTHON
    return 1;
#else
    return 0;
#endif
}

EXTERA_WEAK char *pl_host_call(const char *method, const char *payload) {
    (void)method;
    (void)payload;
    return pl_strdup("null");
}

#if !EXTERA_HAS_PYTHON

int pl_python_start(const char *sdk_path, const char *plugins_path,
                    const char *files_path, const char *stdlib_path,
                    char **error) {
    (void)sdk_path;
    (void)plugins_path;
    (void)files_path;
    (void)stdlib_path;
    if (error != NULL) {
        *error = pl_strdup("this build has no CPython runtime");
    }
    return -1;
}

char *pl_python_call_json(const char *function, const char *args_json, char **error) {
    (void)function;
    (void)args_json;
    if (error != NULL) {
        *error = pl_strdup("this build has no CPython runtime");
    }
    return NULL;
}

char *pl_python_invoke(const char *handle, const char *payload, char **error) {
    (void)handle;
    (void)payload;
    if (error != NULL) {
        *error = pl_strdup("this build has no CPython runtime");
    }
    return NULL;
}

void pl_python_stop(void) {
}

#else /* EXTERA_HAS_PYTHON */

/* ------------------------------------------------------------------------- */
/* Errors                                                                    */

static char *pl_traceback(void) {
    PyObject *type = NULL;
    PyObject *value = NULL;
    PyObject *traceback = NULL;
    PyErr_Fetch(&type, &value, &traceback);
    PyErr_NormalizeException(&type, &value, &traceback);

    PyObject *traceback_module = PyImport_ImportModule("traceback");
    PyObject *text = NULL;
    if (traceback_module != NULL) {
        PyObject *format = PyObject_GetAttrString(traceback_module, "format_exception");
        if (format != NULL && PyCallable_Check(format)) {
            PyObject *args = PyTuple_Pack(3,
                                          type != NULL ? type : Py_None,
                                          value != NULL ? value : Py_None,
                                          traceback != NULL ? traceback : Py_None);
            if (args != NULL) {
                PyObject *lines = PyObject_CallObject(format, args);
                Py_DECREF(args);
                if (lines != NULL) {
                    PyObject *separator = PyUnicode_FromString("");
                    if (separator != NULL) {
                        text = PyUnicode_Join(separator, lines);
                        Py_DECREF(separator);
                    }
                    Py_DECREF(lines);
                }
            }
            Py_DECREF(format);
        }
        Py_DECREF(traceback_module);
    }
    Py_XDECREF(type);
    Py_XDECREF(value);
    Py_XDECREF(traceback);

    if (text == NULL) {
        PyErr_Clear();
        return pl_strdup("unknown Python error");
    }
    const char *utf8 = PyUnicode_AsUTF8(text);
    char *result = pl_strdup(utf8 != NULL ? utf8 : "unknown Python error");
    Py_DECREF(text);
    return result;
}

/* ------------------------------------------------------------------------- */
/* The `_extera_native` module                                               */

static PyObject *pl_native_host(PyObject *self, PyObject *args) {
    (void)self;
    const char *method = NULL;
    const char *payload = NULL;
    if (!PyArg_ParseTuple(args, "ss", &method, &payload)) {
        return NULL;
    }
    char *raw = pl_host_call(method, payload);
    if (raw == NULL) {
        Py_RETURN_NONE;
    }

    PyObject *json = PyImport_ImportModule("json");
    PyObject *result = NULL;
    if (json != NULL) {
        PyObject *loads = PyObject_GetAttrString(json, "loads");
        if (loads != NULL) {
            PyObject *text = PyUnicode_FromString(raw);
            if (text != NULL) {
                result = PyObject_CallOneArg(loads, text);
                Py_DECREF(text);
            }
            Py_DECREF(loads);
        }
        Py_DECREF(json);
    }
    pl_python_free(raw);
    if (result == NULL) {
        PyErr_Clear();
        Py_RETURN_NONE;
    }
    return result;
}

static PyObject *pl_native_invoke(PyObject *self, PyObject *args) {
    (void)self;
    const char *handle = NULL;
    const char *payload = NULL;
    if (!PyArg_ParseTuple(args, "ss", &handle, &payload)) {
        return NULL;
    }
    char *error = NULL;
    char *raw = pl_python_invoke(handle, payload, &error);
    if (raw == NULL) {
        PyObject *message = PyUnicode_FromString(error != NULL ? error : "callback failed");
        pl_python_free(error);
        PyErr_SetObject(PyExc_RuntimeError, message != NULL ? message : Py_None);
        Py_XDECREF(message);
        return NULL;
    }
    PyObject *json = PyImport_ImportModule("json");
    PyObject *result = NULL;
    if (json != NULL) {
        PyObject *loads = PyObject_GetAttrString(json, "loads");
        if (loads != NULL) {
            PyObject *text = PyUnicode_FromString(raw);
            if (text != NULL) {
                result = PyObject_CallOneArg(loads, text);
                Py_DECREF(text);
            }
            Py_DECREF(loads);
        }
        Py_DECREF(json);
    }
    pl_python_free(raw);
    if (result == NULL) {
        PyErr_Clear();
        Py_RETURN_NONE;
    }
    return result;
}

static PyObject *pl_native_set_verbose(PyObject *self, PyObject *args) {
    (void)self;
    int value = 0;
    if (PyArg_ParseTuple(args, "p", &value)) {
        pl_verbose = value;
    }
    Py_RETURN_NONE;
}

static PyObject *pl_native_python_available(PyObject *self, PyObject *args) {
    (void)self;
    (void)args;
    Py_RETURN_TRUE;
}

static PyMethodDef pl_native_methods[] = {
    {"host", pl_native_host, METH_VARARGS, "Calls the Swift host with a JSON payload."},
    {"invoke", pl_native_invoke, METH_VARARGS, "Invokes a retained Python callback."},
    {"set_verbose", pl_native_set_verbose, METH_VARARGS, "Enables host-call tracing."},
    {"python_available", pl_native_python_available, METH_NOARGS, "Always true in this build."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef pl_native_module = {
    PyModuleDef_HEAD_INIT,
    "_extera_native",
    "exteraGram plugins host bridge",
    -1,
    pl_native_methods,
    NULL, NULL, NULL, NULL,
};

static PyObject *pl_create_native_module(void) {
    return PyModule_Create(&pl_native_module);
}

/* ------------------------------------------------------------------------- */
/* Startup                                                                   */

static int pl_append_sys_path(const char *path) {
    if (path == NULL || path[0] == '\0') {
        return 0;
    }
    PyObject *sys_path = PySys_GetObject("path");
    if (sys_path == NULL) {
        return -1;
    }
    PyObject *value = PyUnicode_FromString(path);
    if (value == NULL) {
        return -1;
    }
    int result = PyList_Insert(sys_path, 0, value);
    Py_DECREF(value);
    return result;
}

static PyObject *pl_call_runtime(const char *function, PyObject *args) {
    PyObject *module = PyImport_ImportModule("_extera_runtime");
    if (module == NULL) {
        return NULL;
    }
    PyObject *callable = PyObject_GetAttrString(module, function);
    Py_DECREF(module);
    if (callable == NULL) {
        return NULL;
    }
    PyObject *result = PyObject_CallObject(callable, args);
    Py_DECREF(callable);
    return result;
}

static int pl_config_append_path(PyConfig *config, const char *path) {
    if (path == NULL || path[0] == '\0') {
        return 0;
    }
    wchar_t *wide = Py_DecodeLocale(path, NULL);
    if (wide == NULL) {
        return -1;
    }
    PyStatus status = PyWideStringList_Append(&config->module_search_paths, wide);
    PyMem_RawFree(wide);
    if (PyStatus_Exception(status)) {
        return -1;
    }
    config->module_search_paths_set = 1;
    return 0;
}

int pl_python_start(const char *sdk_path, const char *plugins_path,
                    const char *files_path, const char *stdlib_path,
                    char **error) {
    if (pl_started) {
        return 0;
    }
    if (sdk_path == NULL) {
        if (error != NULL) {
            *error = pl_strdup("the SDK path is missing");
        }
        return -1;
    }
    if (stdlib_path == NULL || stdlib_path[0] == '\0') {
        if (error != NULL) {
            *error = pl_strdup("the Python standard library path is missing");
        }
        return -1;
    }

    PyStatus status;
    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.install_signal_handlers = 0;
    config.use_environment = 0;
    config.write_bytecode = 0;
    config.parse_argv = 0;
    status = PyConfig_SetBytesString(&config, &config.program_name, "extera-plugins");
    if (PyStatus_Exception(status)) {
        PyConfig_Clear(&config);
        if (error != NULL) {
            *error = pl_strdup(status.err_msg != NULL ? status.err_msg : "Python configuration failed");
        }
        return -1;
    }
    if (stdlib_path != NULL && stdlib_path[0] != '\0') {
        char dynamicPath[4096];
        snprintf(dynamicPath, sizeof(dynamicPath), "%s/lib-dynload", stdlib_path);
        if (pl_config_append_path(&config, stdlib_path) != 0 ||
            pl_config_append_path(&config, dynamicPath) != 0) {
            PyConfig_Clear(&config);
            if (error != NULL) {
                *error = pl_strdup("could not configure the Python standard library path");
            }
            return -1;
        }
    }
    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {
        if (error != NULL) {
            *error = pl_strdup(status.err_msg != NULL ? status.err_msg : "Python initialization failed");
        }
        return -1;
    }

    PyObject *native = pl_create_native_module();
    if (native == NULL) {
        if (error != NULL) {
            *error = pl_traceback();
        }
        return -1;
    }
    PyObject *modules = PyImport_GetModuleDict();
    if (modules != NULL) {
        PyDict_SetItemString(modules, "_extera_native", native);
    }
    Py_DECREF(native);

    if (pl_append_sys_path(sdk_path) < 0 ||
        pl_append_sys_path(plugins_path) < 0 ||
        pl_append_sys_path(files_path) < 0) {
        if (error != NULL) {
            *error = pl_traceback();
        }
        return -1;
    }

    PyObject *args = Py_BuildValue("(sss)",
                                   sdk_path,
                                   plugins_path != NULL ? plugins_path : "",
                                   files_path != NULL ? files_path : "");
    if (args == NULL) {
        if (error != NULL) {
            *error = pl_traceback();
        }
        return -1;
    }
    PyObject *result = pl_call_runtime("initialize", args);
    Py_DECREF(args);
    if (result == NULL) {
        if (error != NULL) {
            *error = pl_traceback();
        }
        return -1;
    }
    if (pl_verbose && PyUnicode_Check(result)) {
        fprintf(stderr, "[extera-plugins] %s\n", PyUnicode_AsUTF8(result));
    }
    Py_DECREF(result);
    pl_started = 1;
    /* The GIL stays with this thread otherwise, and every call from another
     * thread would block in PyGILState_Ensure forever. */
    (void)PyEval_SaveThread();
    return 0;
}

/* ------------------------------------------------------------------------- */
/* Calls                                                                     */

char *pl_python_call_json(const char *function, const char *args_json, char **error) {
    if (!pl_started) {
        if (error != NULL) {
            *error = pl_strdup("the plugin runtime is not started");
        }
        return NULL;
    }

    PyGILState_STATE gil = PyGILState_Ensure();
    char *result_text = NULL;

    PyObject *json = PyImport_ImportModule("json");
    PyObject *arguments = NULL;
    if (json != NULL) {
        PyObject *loads = PyObject_GetAttrString(json, "loads");
        if (loads != NULL) {
            PyObject *text = PyUnicode_FromString(args_json != NULL ? args_json : "[]");
            if (text != NULL) {
                arguments = PyObject_CallOneArg(loads, text);
                Py_DECREF(text);
            }
            Py_DECREF(loads);
        }
        Py_DECREF(json);
    }
    if (arguments == NULL) {
        PyErr_Clear();
        arguments = PyTuple_New(0);
    }
    if (!PyTuple_Check(arguments)) {
        PyObject *converted = PyTuple_Pack(1, arguments);
        Py_DECREF(arguments);
        arguments = converted;
    }

    PyObject *value = pl_call_runtime(function, arguments);
    Py_DECREF(arguments);

    if (value == NULL) {
        if (error != NULL) {
            *error = pl_traceback();
        }
        PyGILState_Release(gil);
        return NULL;
    }

    if (PyUnicode_Check(value)) {
        const char *utf8 = PyUnicode_AsUTF8(value);
        result_text = pl_strdup(utf8 != NULL ? utf8 : "null");
    } else {
        PyObject *json_module = PyImport_ImportModule("json");
        PyObject *dumps = NULL;
        if (json_module != NULL) {
            dumps = PyObject_GetAttrString(json_module, "dumps");
        }
        if (dumps != NULL) {
            PyObject *encoded = PyObject_CallOneArg(dumps, value);
            if (encoded != NULL) {
                const char *utf8 = PyUnicode_AsUTF8(encoded);
                result_text = pl_strdup(utf8 != NULL ? utf8 : "null");
                Py_DECREF(encoded);
            }
            Py_DECREF(dumps);
        }
        Py_XDECREF(json_module);
    }
    Py_DECREF(value);

    if (result_text == NULL) {
        PyErr_Clear();
        result_text = pl_strdup("null");
    }
    PyGILState_Release(gil);
    return result_text;
}

char *pl_python_invoke(const char *handle, const char *payload, char **error) {
    if (!pl_started) {
        if (error != NULL) {
            *error = pl_strdup("the plugin runtime is not started");
        }
        return NULL;
    }
    PyGILState_STATE gil = PyGILState_Ensure();
    PyObject *args = Py_BuildValue("(ss)", handle != NULL ? handle : "",
                                   payload != NULL ? payload : "[]");
    PyObject *value = pl_call_runtime("invoke_callback", args);
    Py_XDECREF(args);

    char *result_text = NULL;
    if (value == NULL) {
        if (error != NULL) {
            *error = pl_traceback();
        }
    } else {
        if (PyUnicode_Check(value)) {
            /* `_extera_runtime.invoke_callback` already returns JSON. */
            const char *utf8 = PyUnicode_AsUTF8(value);
            result_text = pl_strdup(utf8 != NULL ? utf8 : "null");
        } else {
            PyObject *json = PyImport_ImportModule("json");
            PyObject *dumps = NULL;
            if (json != NULL) {
                dumps = PyObject_GetAttrString(json, "dumps");
            }
            if (dumps != NULL) {
                PyObject *encoded = PyObject_CallOneArg(dumps, value);
                if (encoded != NULL) {
                    const char *utf8 = PyUnicode_AsUTF8(encoded);
                    result_text = pl_strdup(utf8 != NULL ? utf8 : "null");
                    Py_DECREF(encoded);
                }
                Py_DECREF(dumps);
            }
            Py_XDECREF(json);
        }
        Py_DECREF(value);
    }
    if (result_text == NULL && error == NULL) {
        PyErr_Clear();
        result_text = pl_strdup("null");
    }
    PyGILState_Release(gil);
    return result_text;
}

void pl_python_stop(void) {
    if (!pl_started) {
        return;
    }
    PyGILState_STATE gil = PyGILState_Ensure();
    PyObject *args = PyTuple_New(0);
    PyObject *value = args != NULL ? pl_call_runtime("shutdown", args) : NULL;
    Py_XDECREF(args);
    Py_XDECREF(value);
    PyErr_Clear();
    PyGILState_Release(gil);
    pl_started = 0;
}

#endif /* EXTERA_HAS_PYTHON */
