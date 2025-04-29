#include <Python.h>
#include <libpostal/libpostal.h>
#include "pyutils.h" // For PyObject_to_string, maybe? Or handle string directly.

// Function to call libpostal setup functions
static PyObject *py_setup_datadir(PyObject *self, PyObject *args) {
    PyObject *arg_path;
    if (!PyArg_ParseTuple(args, "O:setup_datadir", &arg_path)) {
        return NULL;
    }

    // Convert Python path object (str) to C string
    char *datadir = NULL;
    PyObject *py_bytes = NULL;
    if (PyUnicode_Check(arg_path)) {
        py_bytes = PyUnicode_AsEncodedString(arg_path, "utf-8", "strict"); 
        if (py_bytes != NULL) {
            datadir = PyBytes_AS_STRING(py_bytes);
        }
    } else if (PyBytes_Check(arg_path)) { // Allow bytes too
        datadir = PyBytes_AS_STRING(arg_path);
    }

    if (datadir == NULL) {
        Py_XDECREF(py_bytes);
        PyErr_SetString(PyExc_TypeError, "Path argument must be a string or bytes");
        return NULL; 
    }

    bool setup_ok = libpostal_setup_datadir(datadir) && 
                    libpostal_setup_language_classifier_datadir(datadir) &&
                    libpostal_setup_parser_datadir(datadir); // Setup all components

    Py_XDECREF(py_bytes); 

    if (!setup_ok) {
        PyErr_Format(PyExc_RuntimeError, "libpostal setup failed for path: %s", datadir);
        return NULL; 
    }

    Py_RETURN_TRUE; // Indicate success
}

// --- Boilerplate for Python 3 C Extension --- 

static PyMethodDef capi_methods[] = {
    {"setup_datadir", py_setup_datadir, METH_VARARGS, "Set libpostal data directory."},
    {NULL, NULL, 0, NULL} // Sentinel
};

static struct PyModuleDef module_def = {
    PyModuleDef_HEAD_INIT,
    "_capi", // Module name
    "Internal C API helpers for pypostal.", // Module docstring
    -1, 
    capi_methods,
    NULL, NULL, NULL, NULL 
};

PyMODINIT_FUNC PyInit__capi(void) { // Python 3 init function
    return PyModule_Create(&module_def);
} 