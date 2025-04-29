# postal/downloader.py
"""Handles discovery, download, and caching of libpostal language models."""

import os
import sys
import requests
import hashlib
import tarfile
import tempfile
import shutil
from platformdirs import user_cache_dir
from tqdm.auto import tqdm
from typing import Dict, List, Optional, Any, Union

# Define manifest URL pointing to the raw file on the master branch
MANIFEST_URL = "https://raw.githubusercontent.com/riordan/pypostal/master/metadata/models.json"

_manifest_cache: Optional[Dict[str, Any]] = None

def _is_model_dir_complete(dir_path: str) -> bool:
    """Checks if a directory contains all required libpostal subdirectories."""
    if not os.path.isdir(dir_path):
        return False
    # Based on libpostal_data script, these are the key dirs created by extracting the 3 components
    required_subdirs = ['address_expansions', 'address_parser', 'language_classifier']
    return all(os.path.exists(os.path.join(dir_path, sub)) for sub in required_subdirs)

def get_cache_dir() -> str:
    """Get the platform-specific user cache directory for libpostal models."""
    # Use 'libpostal' for appname and appauthor for potential cross-binding sharing
    cache_dir: str = user_cache_dir('libpostal', 'libpostal') 
    # Ensure the base cache directory exists
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

def _fetch_manifest() -> Dict[str, Any]:
    """Fetch the model manifest JSON from the hosted URL.
    
    Raises:
        IOError: If the manifest cannot be fetched.
        ValueError: If the fetched content is not valid JSON.
        
    Returns:
        Dict[str, Any]: The parsed manifest data.
    """
    global _manifest_cache
    if _manifest_cache is not None:
        return _manifest_cache

    try:
        print(f"Fetching model manifest from {MANIFEST_URL}...", file=sys.stderr)
        response = requests.get(MANIFEST_URL, timeout=10) # Add a timeout
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        manifest_data: Dict[str, Any] = response.json()
        _manifest_cache = manifest_data
        return manifest_data
    except requests.exceptions.RequestException as e:
        print(f"Error fetching manifest: {e}", file=sys.stderr)
        raise IOError(f"Could not fetch model manifest from {MANIFEST_URL}: {e}") from e
    except requests.exceptions.JSONDecodeError as e:
        print(f"Error parsing manifest JSON: {e}", file=sys.stderr)
        raise ValueError(f"Invalid JSON received from {MANIFEST_URL}: {e}") from e

def list_available_models() -> List[str]:
    """List model versions available according to the manifest."""
    try:
        manifest = _fetch_manifest()
        return list(manifest.keys())
    except (IOError, ValueError) as e:
        print(f"Could not list available models: {e}", file=sys.stderr)
        return []

def get_downloaded_models() -> List[str]:
    """List model versions (directory names) already present and complete in the cache."""
    cache_dir = get_cache_dir()
    downloaded: List[str] = []
    try:
        for item in os.listdir(cache_dir):
            item_path = os.path.join(cache_dir, item)
            if _is_model_dir_complete(item_path): # Use new helper
                version_key = item
                downloaded.append(version_key)
    except OSError as e:
        print(f"Error scanning cache directory {cache_dir}: {e}", file=sys.stderr)
    print(f"Found complete downloaded models: {downloaded}", file=sys.stderr)
    return downloaded

def download_model(version: str = 'default', force: bool = False) -> bool:
    """Download, verify, and extract the specified model version and all its components."""
    
    # 1. Resolve version/get details from manifest
    try:
        manifest = _fetch_manifest()
    except (IOError, ValueError) as e:
        print(f"Cannot download model: Failed to fetch or parse manifest: {e}", file=sys.stderr)
        return False

    if version not in manifest:
        print(f"Error: Model version '{version}' not found in manifest. Available: {list(manifest.keys())}", file=sys.stderr)
        return False
    
    # Check top-level structure for the specified version
    model_entry = manifest[version]
    if not isinstance(model_entry, dict):
         print(f"Error: Manifest entry for '{version}' is not a valid dictionary.", file=sys.stderr)
         return False

    # Define expected components
    components = ["base", "parser", "language_classifier"]
    if not all(comp in model_entry for comp in components):
        print(f"Error: Manifest entry for '{version}' is missing required components ({components}).", file=sys.stderr)
        return False

    # 2. Determine target cache directory based on version key
    base_cache_dir: str = get_cache_dir()
    target_dir: str = os.path.join(base_cache_dir, version)

    # 3. Check cache (use force) - Check for completeness based on components
    if not force and _is_model_dir_complete(target_dir):
        print(f"Model version '{version}' already found and complete in cache: {target_dir}", file=sys.stderr)
        return True # Success (already downloaded)
    elif force and os.path.exists(target_dir):
        print(f"Force download requested. Removing existing directory: {target_dir}", file=sys.stderr)
        try:
            shutil.rmtree(target_dir)
        except OSError as e:
            print(f"Warning: Failed to remove existing directory {target_dir}: {e}", file=sys.stderr)
    
    # Ensure target directory parent and target dir itself exist for extraction
    os.makedirs(target_dir, exist_ok=True)

    # --- Loop through components for Steps 4, 5, 6 --- 
    for component_name in components:
        print(f"\nProcessing component: {version} ({component_name})...", file=sys.stderr)
        component_info = model_entry[component_name]
        if not isinstance(component_info, dict):
             print(f"Error: Manifest entry for '{version}/{component_name}' is not a dictionary.", file=sys.stderr)
             return False # Manifest structure error

        model_url: Optional[str] = component_info.get('url')
        expected_sha256: Optional[str] = component_info.get('sha256')

        if not model_url or not expected_sha256:
            print(f"Error: Manifest entry for '{version}/{component_name}' is incomplete (missing url or sha256).", file=sys.stderr)
            return False

        print(f"Downloading {component_name} from {model_url}...", file=sys.stderr)
        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                tmp_path = tmp_file.name
                response = requests.get(model_url, stream=True, timeout=60) # Longer timeout for potentially large files
                response.raise_for_status()
                
                total_size_str: Optional[str] = response.headers.get('content-length')
                total_size: int = int(total_size_str) if total_size_str else 0
                block_size: int = 1024 * 1024 # 1 MiB block size for potentially large files
                sha256_hash = hashlib.sha256()
                
                progress_desc = f"Downloading {version} ({component_name})"
                with tqdm(total=total_size, unit='iB', unit_scale=True, desc=progress_desc, file=sys.stderr, disable=not sys.stderr.isatty()) as bar:
                    for chunk in response.iter_content(chunk_size=block_size):
                        if chunk:
                            bar.update(len(chunk))
                            sha256_hash.update(chunk)
                            tmp_file.write(chunk)
                
                downloaded_sha256: str = sha256_hash.hexdigest()
                print(f"\n{component_name} download complete. SHA256: {downloaded_sha256}", file=sys.stderr)
                
                # Verify checksum
                if downloaded_sha256 != expected_sha256:
                    raise ValueError(f"Checksum mismatch for {version}/{component_name}! Expected {expected_sha256}, got {downloaded_sha256}")
                
                print(f"Checksum verified for {component_name}. Extracting...", file=sys.stderr)
                
                # Extract tar.gz - Extracts into target_dir
                tmp_file.seek(0)
                with tarfile.open(fileobj=tmp_file, mode='r:gz') as tar:
                    members = tar.getmembers()
                    extract_desc = f"Extracting {version} ({component_name})"
                    for member in tqdm(members, desc=extract_desc, unit='file', file=sys.stderr, disable=not sys.stderr.isatty()):
                        tar.extract(member, path=target_dir, filter='data')
                
                print(f"Extraction complete for {component_name}", file=sys.stderr)
            
        except (requests.exceptions.RequestException, ValueError, tarfile.TarError, Exception) as e:
            print(f"\nError processing component {component_name}: {e}", file=sys.stderr)
            # Attempt to clean up potentially partially extracted directory if an error occurs
            if os.path.exists(target_dir):
                 try:
                     print(f"Attempting to clean up incomplete directory: {target_dir}", file=sys.stderr)
                     shutil.rmtree(target_dir)
                 except OSError as clean_e:
                      print(f"Warning: Failed to clean up directory {target_dir} after error: {clean_e}", file=sys.stderr)
            return False # Indicate overall failure
        finally:
            # Clean up the temporary file for this component
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                    print(f"Cleaned up temporary file: {tmp_path}", file=sys.stderr)
                except OSError as e:
                    print(f"Warning: Failed to remove temporary file {tmp_path}: {e}", file=sys.stderr)

    # Check for completeness one last time after attempting all components
    if _is_model_dir_complete(target_dir):
        print(f"\nSuccessfully downloaded and extracted all components for model '{version}' to {target_dir}", file=sys.stderr)
        return True
    else:
        print(f"\nModel download for '{version}' appears incomplete after processing all components.", file=sys.stderr)
        return False

def get_data_dir(version: str = 'default') -> Optional[str]:
    """Get the path to the extracted data directory for a given version.

    Returns:
        str: Path to the data directory if found and valid (contains all components).
        None: If the specified model version is not downloaded/cached or incomplete.
    """
    base_cache_dir = get_cache_dir()
    target_dir = os.path.join(base_cache_dir, version)

    if _is_model_dir_complete(target_dir): # Use new helper
        print(f"Found complete data directory for version '{version}': {target_dir}", file=sys.stderr)
        return target_dir
    else:
        print(f"Data directory for version '{version}' not found or incomplete in cache ({target_dir}).", file=sys.stderr)
        return None 