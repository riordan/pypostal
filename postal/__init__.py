# postal/__init__.py
import os # Need os for getenv and path checks
import sys # For printing to stderr
import threading # Import threading

# Custom exception for missing data
class PostalDataNotFound(Exception):
    """Exception raised when libpostal data directory cannot be found."""
    # Keep custom message for direct raises, override below if needed
    def __init__(self, message="Libpostal data directory not found. Please run `postal.download_model()`."):
        self.message = message
        super().__init__(self.message)

# Expose the download function
from .downloader import download_model
from typing import Optional # For type hints

# Internal flag and lock for thread-safe initialization
_INITIALIZED = False
_INIT_LOCK = threading.Lock()

# Helper to check if a directory looks like a valid libpostal data dir
def _is_valid_datadir(path: Optional[str]) -> bool:
    if not path or not os.path.isdir(path):
        return False
    # Check for a key subdirectory as a marker
    return os.path.exists(os.path.join(path, 'address_parser'))

def initialize(model_key: str = "default"):
    """Initializes the libpostal library with the data directory.
    
    Checks LIBPOSTAL_DATA_DIR env var first, then the default cache.
    This function MUST be called before using any parsing or expansion functions.
    
    Raises:
        PostalDataNotFound: If the data cannot be found or is invalid.
        ImportError: If the underlying C extension cannot be imported.
        RuntimeError: If the C library fails to initialize.
    """
    global _INITIALIZED
    # Quick check without lock first for performance
    if _INITIALIZED:
        return

    # Acquire lock before proceeding with initialization check/logic
    with _INIT_LOCK:
        # Double-check now that we have the lock
        if _INITIALIZED:
            return

        from . import downloader # Lazy import
        from . import _capi 

        datadir_path: Optional[str] = None
        init_source: str = ""

        # 1. Check environment variable first
        env_datadir = os.getenv("LIBPOSTAL_DATA_DIR")
        if env_datadir:
            print(f"Found LIBPOSTAL_DATA_DIR: {env_datadir}", file=sys.stderr) # Print to stderr
            if _is_valid_datadir(env_datadir):
                datadir_path = env_datadir
                init_source = "environment variable"
            else:
                # Env var set but invalid - raise an error, don't fallback silently
                raise PostalDataNotFound(
                    f"LIBPOSTAL_DATA_DIR is set to '{env_datadir}', "
                    "but it's not a valid libpostal data directory."
                )

        # 2. If env var not used, try downloader cache
        if datadir_path is None:
            print("LIBPOSTAL_DATA_DIR not set or invalid, checking cache...", file=sys.stderr)
            datadir_path = downloader.get_data_dir() # get_data_dir already validates
            if datadir_path:
                 init_source = "downloader cache"

        # 3. If neither worked, raise error with guidance
        if datadir_path is None:
            raise PostalDataNotFound(
                "Libpostal data directory not found. "
                "Set the LIBPOSTAL_DATA_DIR environment variable pointing to the data directory "
                "or run `postal.download_model()` to download it to the default cache."
            )
        
        print(f"Initializing libpostal with data directory from {init_source}: {datadir_path}", file=sys.stderr)
        
        # Call the C API wrapper function
        try:
            _capi.setup_datadir(datadir_path)
        except Exception as e:
             raise RuntimeError(f"Failed to initialize libpostal C library with datadir: {datadir_path}") from e

        # Set flag *after* successful initialization inside the lock
        _INITIALIZED = True
        print("Libpostal initialized successfully.", file=sys.stderr)

# Optional: Consider adding logic to automatically call initialize() 
# on first import of submodules, but raise if not called explicitly?
# Or add checks in each submodule function to ensure _INITIALIZED is True.
