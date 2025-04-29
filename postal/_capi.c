# postal/_capi.c
#include <Python.h>
#include <libpostal/libpostal.h>
#include "pyutils.h" // For PyObject_to_string, maybe? Or handle string directly.

#if PY_MAJOR_VERSION >= 3
#define IS_PY3K
#endif

// Function to call libpostal setup functions
static PyObject *py_setup_datadir(PyObject *self, PyObject *args) {
    PyObject *arg_path;
    if (!PyArg_ParseTuple(args, "O:setup_datadir", &arg_path)) {
        return NULL;
    }

    // Convert Python path object (likely str) to C string
    // Option 1: Use PyObject_to_string from pyutils.c (if linked)
    // char *datadir = PyObject_to_string(arg_path); 
    // Option 2: Use standard Python C API (safer, avoids linking dependency)
    char *datadir = NULL;
    PyObject *py_bytes = NULL;
    if (PyUnicode_Check(arg_path)) {
        // Use utf-8 encoding, common for paths
        py_bytes = PyUnicode_AsEncodedString(arg_path, "utf-8", "strict"); 
        if (py_bytes != NULL) {
            datadir = PyBytes_AS_STRING(py_bytes);
        }
    } else if (PyBytes_Check(arg_path)) {
        // Allow bytes directly (less common for paths)
        datadir = PyBytes_AS_STRING(arg_path);
    }

    if (datadir == NULL) {
        Py_XDECREF(py_bytes);
        PyErr_SetString(PyExc_TypeError, "Path argument must be a string or bytes");
        return NULL; // Error converting path
    }

    bool setup_ok = libpostal_setup_datadir(datadir) && 
                    libpostal_setup_language_classifier_datadir(datadir);

    // Clean up bytes object if created
    Py_XDECREF(py_bytes); 
    // free(datadir); // Only free if PyObject_to_string was used and it allocated

    if (!setup_ok) {
        // Raise a RuntimeError instead of returning False for clearer Python-side handling
        PyErr_Format(PyExc_RuntimeError, "libpostal_setup_datadir failed for path: %s", datadir);
        return NULL; 
    }

    Py_RETURN_TRUE; // Indicate success
}

// --- Boilerplate for Python C Extension ---

static PyMethodDef capi_methods[] = {
    {"setup_datadir", py_setup_datadir, METH_VARARGS, "Set libpostal data directory."},
    {NULL, NULL, 0, NULL} // Sentinel
};

#ifdef IS_PY3K
    static struct PyModuleDef module_def = {
        PyModuleDef_HEAD_INIT,
        "_capi", // Module name
        "Internal C API helpers for pypostal.", // Module docstring
        -1, // Size of per-interpreter state, -1 = no state
        capi_methods,
        NULL, NULL, NULL, NULL // Optional slots (reload, traverse, clear, free)
    };

    PyMODINIT_FUNC PyInit__capi(void) {
        return PyModule_Create(&module_def);
    }
#else // Python 2
    PyMODINIT_FUNC init_capi(void) {
        (void) Py_InitModule3("_capi", capi_methods, "Internal C API helpers for pypostal.");
    }
#endif 