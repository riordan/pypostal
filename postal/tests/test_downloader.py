# postal/tests/test_downloader.py
"""Unit tests for the postal.downloader module."""

import os
import pytest
import requests
import tarfile
from unittest import mock # Or from pytest_mock import mocker
import shutil # Make sure shutil is imported

from postal import downloader

# --- Fixtures (Optional but helpful) ---

@pytest.fixture
def mock_cache_dir(tmp_path):
    """Fixture to mock the cache directory using pytest's tmp_path."""
    cache_path = tmp_path / "pypostal_cache"
    cache_path.mkdir()
    with mock.patch.object(downloader, 'user_cache_dir', return_value=str(cache_path)):
        yield str(cache_path)

@pytest.fixture
def mock_requests_get():
    """Fixture to mock requests.get."""
    with mock.patch.object(requests, 'get') as mock_get:
        yield mock_get

# --- Test Cases ---

# Tests for get_cache_dir()
def test_get_cache_dir_creates_dir(mock_cache_dir):
    """Test that get_cache_dir returns the correct path and creates it."""
    cache_dir = downloader.get_cache_dir()
    assert cache_dir == mock_cache_dir
    assert os.path.exists(cache_dir)
    # Rerun to ensure it handles existing directory
    cache_dir_again = downloader.get_cache_dir()
    assert cache_dir_again == mock_cache_dir 

# Tests for _fetch_manifest()
def test_fetch_manifest_success(mock_requests_get):
    """Test successful manifest fetching and caching."""
    # Reset cache before test
    downloader._manifest_cache = None
    
    # Sample manifest data
    sample_manifest = {
        "default": {
            "url": "http://example.com/default.tar.gz",
            "sha256": "abc",
            "version_detail": "latest_detail"
        },
        "v1.0": {
            "url": "http://example.com/v1.0.tar.gz",
            "sha256": "def",
            "version_detail": "v1.0_detail"
        }
    }
    
    # Configure the mock response
    mock_response = mock.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = sample_manifest
    mock_response.raise_for_status.return_value = None # No exception on success
    mock_requests_get.return_value = mock_response
    
    # Call the function
    manifest = downloader._fetch_manifest()
    
    # Assertions
    mock_requests_get.assert_called_once_with(downloader.MANIFEST_URL, timeout=10)
    assert manifest == sample_manifest
    assert downloader._manifest_cache == sample_manifest # Check internal cache

def test_fetch_manifest_network_error(mock_requests_get):
    """Test handling of network errors during manifest fetch."""
    # Reset cache before test
    downloader._manifest_cache = None

    # Configure mock to raise a network error
    mock_requests_get.side_effect = requests.exceptions.RequestException("Network error")

    # Assert that IOError is raised
    with pytest.raises(IOError, match="Could not fetch model manifest.*"): # Check error message too
        downloader._fetch_manifest()

    # Assert cache is still None
    assert downloader._manifest_cache is None

def test_fetch_manifest_bad_status(mock_requests_get):
    """Test handling of non-200 HTTP status codes."""
    # Reset cache before test
    downloader._manifest_cache = None

    # Configure the mock response
    mock_response = mock.Mock()
    mock_response.status_code = 404
    http_error = requests.exceptions.HTTPError("404 Client Error: Not Found")
    http_error.response = mock_response # Attach response to error as requests does
    mock_response.raise_for_status.side_effect = http_error
    mock_requests_get.return_value = mock_response

    # Assert that IOError is raised
    with pytest.raises(IOError, match="Could not fetch model manifest.*"): 
        downloader._fetch_manifest()
        
    # Assert cache is still None
    assert downloader._manifest_cache is None

def test_fetch_manifest_invalid_json(mock_requests_get):
    """Test handling of invalid JSON content."""
    # Reset cache before test
    downloader._manifest_cache = None

    # Configure the mock response
    mock_response = mock.Mock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    # Simulate JSON decode error
    mock_response.json.side_effect = requests.exceptions.JSONDecodeError("Expecting value", "", 0)
    mock_requests_get.return_value = mock_response

    # Assert that ValueError is raised
    with pytest.raises(ValueError, match="Invalid JSON received.*"): 
        downloader._fetch_manifest()
        
    # Assert cache is still None
    assert downloader._manifest_cache is None

def test_fetch_manifest_caching(mock_requests_get):
    """Test that the manifest is fetched only once."""
    # Reset cache before test
    downloader._manifest_cache = None

    # Sample manifest data
    sample_manifest = {"default": {"url": "url", "sha256": "abc"}}

    # Configure the mock response
    mock_response = mock.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = sample_manifest
    mock_response.raise_for_status.return_value = None
    mock_requests_get.return_value = mock_response

    # Call the function first time
    manifest1 = downloader._fetch_manifest()

    # Call the function second time
    manifest2 = downloader._fetch_manifest()

    # Assertions
    mock_requests_get.assert_called_once() # Crucial: Should only be called once
    assert manifest1 == sample_manifest
    assert manifest2 == sample_manifest
    assert downloader._manifest_cache == sample_manifest

# Tests for list_available_models()
def test_list_available_models_success(mock_requests_get):
    """Test listing models from a valid manifest."""
    # Reset cache before test
    downloader._manifest_cache = None

    # Sample manifest data
    sample_manifest = {
        "default": {"url": "url1", "sha256": "abc"},
        "v1.0": {"url": "url2", "sha256": "def"}
    }

    # Configure the mock response for _fetch_manifest
    mock_response = mock.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = sample_manifest
    mock_response.raise_for_status.return_value = None
    mock_requests_get.return_value = mock_response

    # Call the function
    available = downloader.list_available_models()

    # Assertions
    assert isinstance(available, list)
    assert sorted(available) == sorted(["default", "v1.0"])
    mock_requests_get.assert_called_once() # Ensure manifest fetch happened

def test_list_available_models_fetch_error(mock_requests_get):
    """Test listing when manifest fetch fails."""
    # Reset cache before test
    downloader._manifest_cache = None

    # Configure mock to raise a network error during manifest fetch
    mock_requests_get.side_effect = requests.exceptions.RequestException("Network error")

    # Call the function
    available = downloader.list_available_models()

    # Assertions
    assert available == []
    mock_requests_get.assert_called_once() # Ensure fetch was attempted

# Tests for get_downloaded_models()
def test_get_downloaded_models_empty(mock_cache_dir):
    """Test finding models when cache is empty."""
    # Ensure cache dir exists but is empty
    assert os.path.exists(mock_cache_dir)
    assert len(os.listdir(mock_cache_dir)) == 0
    
    downloaded = downloader.get_downloaded_models()
    assert downloaded == []

def test_get_downloaded_models_finds_valid(mock_cache_dir):
    """Test finding a correctly structured cached model."""
    # Create a valid-looking model directory in the mock cache
    model_version_key = "default" # Using the key as the dir name for now
    model_dir = os.path.join(mock_cache_dir, model_version_key)
    address_parser_dir = os.path.join(model_dir, 'address_parser')
    os.makedirs(address_parser_dir)
    # Optionally, add a dummy file inside
    (open(os.path.join(address_parser_dir, 'dummy.dat'), 'a')).close()

    downloaded = downloader.get_downloaded_models()
    assert downloaded == [model_version_key]

def test_get_downloaded_models_ignores_invalid(mock_cache_dir):
    """Test ignoring files or incomplete directories in cache."""
    # Create a valid model dir
    valid_version = "v1.1"
    valid_dir = os.path.join(mock_cache_dir, valid_version)
    os.makedirs(os.path.join(valid_dir, 'address_parser'))

    # Create an invalid file
    invalid_file = os.path.join(mock_cache_dir, "some_file.txt")
    (open(invalid_file, 'a')).close()

    # Create an incomplete directory (missing address_parser)
    incomplete_dir = os.path.join(mock_cache_dir, "incomplete_v1.0")
    os.makedirs(incomplete_dir)

    downloaded = downloader.get_downloaded_models()
    # Should only find the valid one
    assert downloaded == [valid_version]

# Tests for get_data_dir()
def test_get_data_dir_success(mock_cache_dir):
    """Test getting path for a valid cached model."""
    # Create a valid-looking model directory
    version = "default"
    model_dir = os.path.join(mock_cache_dir, version)
    address_parser_dir = os.path.join(model_dir, 'address_parser')
    os.makedirs(address_parser_dir)

    # Call get_data_dir for the correct version
    data_dir = downloader.get_data_dir(version=version)
    
    # Assert the correct path is returned
    assert data_dir == model_dir

def test_get_data_dir_not_found(mock_cache_dir):
    """Test getting path for a non-existent model version."""
    # Cache directory exists but is empty or doesn't contain the version
    version = "non_existent_v99"
    
    data_dir = downloader.get_data_dir(version=version)
    
    # Assert None is returned
    assert data_dir is None

def test_get_data_dir_incomplete(mock_cache_dir):
    """Test getting path when cache dir exists but is incomplete."""
    # Create a directory for the version, but WITHOUT address_parser subdir
    version = "incomplete_v1"
    model_dir = os.path.join(mock_cache_dir, version)
    os.makedirs(model_dir)
    
    data_dir = downloader.get_data_dir(version=version)
    
    # Assert None is returned because completion marker is missing
    assert data_dir is None

# Tests for download_model()
@mock.patch('tarfile.open') # Mock tarfile.open
@mock.patch('hashlib.sha256') # Mock hashlib.sha256
def test_download_model_success_first_time(mock_sha256, mock_tar_open, mock_requests_get, mock_cache_dir):
    """Test full successful download, verify, extract."""
    # Reset internal manifest cache
    downloader._manifest_cache = None
    
    version = "default"
    url = "http://example.com/default.tar.gz"
    checksum = "a" * 64 # Dummy 64-char hex string
    sample_manifest = {
        version: {"url": url, "sha256": checksum}
    }
    target_dir = os.path.join(mock_cache_dir, version)
    completion_marker = os.path.join(target_dir, 'address_parser')
    
    # Mock manifest response
    mock_manifest_response = mock.Mock()
    mock_manifest_response.status_code = 200
    mock_manifest_response.json.return_value = sample_manifest
    mock_manifest_response.raise_for_status.return_value = None

    # Mock data download response (minimal content)
    mock_data_content = b'dummy tarball content'
    mock_data_response = mock.Mock()
    mock_data_response.status_code = 200
    mock_data_response.headers = {'content-length': str(len(mock_data_content))}
    mock_data_response.iter_content.return_value = [mock_data_content]
    mock_data_response.raise_for_status.return_value = None
    
    # Setup requests.get mock to return manifest then data
    mock_requests_get.side_effect = [mock_manifest_response, mock_data_response]
    
    # Mock hashlib to return the expected checksum
    mock_hash_obj = mock.Mock()
    mock_hash_obj.hexdigest.return_value = checksum
    mock_sha256.return_value = mock_hash_obj
    
    # Mock tarfile to simulate extraction (and creation of marker)
    # We need the context manager to work
    mock_tar_context = mock.Mock()
    def side_effect_extractall(*args, **kwargs):
        # Simulate creation of the completion marker directory upon extraction
        os.makedirs(completion_marker, exist_ok=True)
    mock_tar_context.extractall = mock.Mock(side_effect=side_effect_extractall)
    mock_tar_context.extract = mock.Mock() # Mock extract too if used
    mock_tar_context.getmembers.return_value = [tarfile.TarInfo(name="dummy")] # Need members for loop
    mock_tar_open.return_value.__enter__.return_value = mock_tar_context

    # --- Action ---
    success = downloader.download_model(version=version, force=False)

    # --- Assertions ---
    assert success is True
    
    # Check requests calls
    assert mock_requests_get.call_count == 2
    calls = mock_requests_get.call_args_list
    assert calls[0][0][0] == downloader.MANIFEST_URL # First call is manifest
    assert calls[1][0][0] == url # Second call is data URL
    
    # Check checksum mock calls (optional, depends on need)
    mock_sha256.assert_called_once()
    mock_hash_obj.update.assert_called_once_with(mock_data_content)
    mock_hash_obj.hexdigest.assert_called_once()
    
    # Check tarfile mock calls
    # Note: The fileobj arg is a temp file handle, tricky to assert directly
    mock_tar_open.assert_called_once()
    assert mock_tar_open.call_args[1]['mode'] == 'r:gz'
    mock_tar_context.extract.assert_called() # Check that extract was called
    
    # Check completion marker was created (by tarfile mock side effect)
    assert os.path.exists(completion_marker)

def test_download_model_already_exists(mock_cache_dir, mock_requests_get):
    """Test skipping download if model exists and force=False."""
    # Reset internal manifest cache
    downloader._manifest_cache = None
    
    version = "default"
    url = "http://example.com/default.tar.gz"
    checksum = "a" * 64
    sample_manifest = {
        version: {"url": url, "sha256": checksum}
    }
    target_dir = os.path.join(mock_cache_dir, version)
    completion_marker = os.path.join(target_dir, 'address_parser')

    # --- Setup --- 
    # Create the directory and marker to simulate existing download
    os.makedirs(completion_marker, exist_ok=True)
    
    # Mock only the manifest response
    mock_manifest_response = mock.Mock()
    mock_manifest_response.status_code = 200
    mock_manifest_response.json.return_value = sample_manifest
    mock_manifest_response.raise_for_status.return_value = None
    mock_requests_get.return_value = mock_manifest_response

    # Mock tarfile just in case, but it shouldn't be called
    mock_tar_open = mock.MagicMock() # Use MagicMock to track calls
    with mock.patch('tarfile.open', mock_tar_open):
        # --- Action ---
        success = downloader.download_model(version=version, force=False)

    # --- Assertions ---
    assert success is True
    # Check requests was called only for manifest
    mock_requests_get.assert_called_once_with(downloader.MANIFEST_URL, timeout=10)
    # Check tarfile was NOT called
    mock_tar_open.assert_not_called()
    

@mock.patch('tarfile.open')
@mock.patch('hashlib.sha256')
@mock.patch('shutil.rmtree') # Mock shutil.rmtree
def test_download_model_force_download(mock_rmtree, mock_sha256, mock_tar_open, mock_requests_get, mock_cache_dir):
    """Test forcing download even if model exists."""
    # Reset internal manifest cache
    downloader._manifest_cache = None
    
    version = "default"
    url = "http://example.com/default.tar.gz"
    checksum = "a" * 64
    sample_manifest = {
        version: {"url": url, "sha256": checksum}
    }
    target_dir = os.path.join(mock_cache_dir, version)
    completion_marker = os.path.join(target_dir, 'address_parser')

    # --- Setup ---
    # Create the directory and marker to simulate existing download
    os.makedirs(completion_marker, exist_ok=True)
    assert os.path.exists(target_dir) # Pre-condition: dir exists

    # Mock manifest response
    mock_manifest_response = mock.Mock()
    mock_manifest_response.status_code = 200
    mock_manifest_response.json.return_value = sample_manifest
    mock_manifest_response.raise_for_status.return_value = None

    # Mock data download response
    mock_data_content = b'dummy tarball content'
    mock_data_response = mock.Mock()
    mock_data_response.status_code = 200
    mock_data_response.headers = {'content-length': str(len(mock_data_content))}
    mock_data_response.iter_content.return_value = [mock_data_content]
    mock_data_response.raise_for_status.return_value = None
    
    # Setup requests.get mock
    mock_requests_get.side_effect = [mock_manifest_response, mock_data_response]
    
    # Mock hashlib
    mock_hash_obj = mock.Mock()
    mock_hash_obj.hexdigest.return_value = checksum
    mock_sha256.return_value = mock_hash_obj
    
    # Mock tarfile
    mock_tar_context = mock.Mock()
    mock_tar_context.extract = mock.Mock()
    mock_tar_context.getmembers.return_value = [tarfile.TarInfo(name="dummy")]
    mock_tar_open.return_value.__enter__.return_value = mock_tar_context

    # --- Action ---
    success = downloader.download_model(version=version, force=True) # force=True

    # --- Assertions ---
    assert success is True
    
    # Check that existing dir was removed
    mock_rmtree.assert_called_once_with(target_dir)
    
    # Check that download and extract still happened
    assert mock_requests_get.call_count == 2
    mock_sha256.assert_called_once()
    mock_tar_open.assert_called_once()
    mock_tar_context.extract.assert_called()

@mock.patch('tarfile.open')
@mock.patch('hashlib.sha256')
@mock.patch('tempfile.NamedTemporaryFile') # Mock tempfile to check cleanup
def test_download_model_bad_checksum(mock_tempfile, mock_sha256, mock_tar_open, mock_requests_get, mock_cache_dir):
    """Test download failure due to checksum mismatch."""
    # Reset internal manifest cache
    downloader._manifest_cache = None
    
    version = "default"
    url = "http://example.com/default.tar.gz"
    expected_checksum = "a" * 64
    downloaded_checksum = "b" * 64 # Different checksum!
    sample_manifest = {
        version: {"url": url, "sha256": expected_checksum}
    }

    # --- Mocks --- 
    # Mock manifest response
    mock_manifest_response = mock.Mock()
    mock_manifest_response.status_code = 200
    mock_manifest_response.json.return_value = sample_manifest
    mock_manifest_response.raise_for_status.return_value = None

    # Mock data download response
    mock_data_content = b'dummy tarball content'
    mock_data_response = mock.Mock()
    mock_data_response.status_code = 200
    mock_data_response.headers = {'content-length': str(len(mock_data_content))}
    mock_data_response.iter_content.return_value = [mock_data_content]
    mock_data_response.raise_for_status.return_value = None
    
    mock_requests_get.side_effect = [mock_manifest_response, mock_data_response]
    
    # Mock hashlib to return the WRONG checksum
    mock_hash_obj = mock.Mock()
    mock_hash_obj.hexdigest.return_value = downloaded_checksum
    mock_sha256.return_value = mock_hash_obj
    
    # Mock tempfile 
    mock_tmp_file_obj = mock.MagicMock() # Use MagicMock for context manager
    mock_tmp_file_obj.name = os.path.join(mock_cache_dir, "temp_download_file")
    mock_tempfile.return_value.__enter__.return_value = mock_tmp_file_obj

    # --- Action ---
    success = downloader.download_model(version=version, force=False)

    # --- Assertions ---
    assert success is False
    
    # Check requests calls (manifest and data attempted)
    assert mock_requests_get.call_count == 2
    
    # Check checksum calls
    mock_sha256.assert_called_once()
    mock_hash_obj.update.assert_called_once_with(mock_data_content)
    mock_hash_obj.hexdigest.assert_called_once()
    
    # Check tarfile was NOT called
    mock_tar_open.assert_not_called()
    
    # Check temp file cleanup was attempted (mocked NamedTemporaryFile doesn't auto-delete)
    # Our finally block should try to remove mock_tmp_file_obj.name
    # We can check if os.remove was called on it, requires mocking os.remove
    with mock.patch('os.remove') as mock_os_remove:
         # Re-run the function or simulate the finally block logic more directly
         # Simpler: just check the logic flow implies cleanup would be attempted
         # if we trust the finally block structure.
         # For thoroughness, mock os.remove and check call
         pass # Actual check depends on how finally block is structured
         # Assert mock_os_remove was called with mock_tmp_file_obj.name - requires refinement

@mock.patch('tarfile.open')
@mock.patch('hashlib.sha256')
def test_download_model_download_error(mock_sha256, mock_tar_open, mock_requests_get, mock_cache_dir):
    """Test handling network errors during data download."""
    # Reset internal manifest cache
    downloader._manifest_cache = None
    
    version = "default"
    url = "http://example.com/default.tar.gz"
    checksum = "a" * 64
    sample_manifest = {
        version: {"url": url, "sha256": checksum}
    }

    # Mock manifest response (success)
    mock_manifest_response = mock.Mock()
    mock_manifest_response.status_code = 200
    mock_manifest_response.json.return_value = sample_manifest
    mock_manifest_response.raise_for_status.return_value = None

    # Mock data download response (failure)
    mock_requests_get.side_effect = [
        mock_manifest_response, 
        requests.exceptions.RequestException("Data download failed")
    ]
    
    # --- Action ---
    success = downloader.download_model(version=version, force=False)
    
    # --- Assertions ---
    assert success is False
    assert mock_requests_get.call_count == 2 # Manifest and data download attempted
    mock_sha256.assert_not_called()
    mock_tar_open.assert_not_called()

@mock.patch('tempfile.NamedTemporaryFile') # Mock tempfile for cleanup check
@mock.patch('tarfile.open')
@mock.patch('hashlib.sha256')
def test_download_model_extract_error(mock_sha256, mock_tar_open, mock_tempfile, mock_requests_get, mock_cache_dir):
    """Test handling errors during tar extraction."""
    # Reset internal manifest cache
    downloader._manifest_cache = None
    
    version = "default"
    url = "http://example.com/default.tar.gz"
    checksum = "a" * 64
    sample_manifest = {
        version: {"url": url, "sha256": checksum}
    }

    # --- Mocks --- 
    # Mock manifest response
    mock_manifest_response = mock.Mock()
    mock_manifest_response.status_code = 200
    mock_manifest_response.json.return_value = sample_manifest
    mock_manifest_response.raise_for_status.return_value = None

    # Mock data download response
    mock_data_content = b'dummy tarball content'
    mock_data_response = mock.Mock()
    mock_data_response.status_code = 200
    mock_data_response.headers = {'content-length': str(len(mock_data_content))}
    mock_data_response.iter_content.return_value = [mock_data_content]
    mock_data_response.raise_for_status.return_value = None
    
    mock_requests_get.side_effect = [mock_manifest_response, mock_data_response]
    
    # Mock hashlib to return the correct checksum
    mock_hash_obj = mock.Mock()
    mock_hash_obj.hexdigest.return_value = checksum
    mock_sha256.return_value = mock_hash_obj
    
    # Mock tempfile
    mock_tmp_file_obj = mock.MagicMock()
    mock_tmp_file_obj.name = os.path.join(mock_cache_dir, "temp_download_file")
    mock_tempfile.return_value.__enter__.return_value = mock_tmp_file_obj
    
    # Mock tarfile.open to raise an error during extraction
    mock_tar_context = mock.Mock()
    mock_tar_context.extract.side_effect = tarfile.TarError("Bad tar file")
    mock_tar_context.getmembers.return_value = [tarfile.TarInfo(name="dummy")]
    mock_tar_open.return_value.__enter__.return_value = mock_tar_context
    
    # --- Action ---
    success = downloader.download_model(version=version, force=False)
    
    # --- Assertions ---
    assert success is False
    assert mock_requests_get.call_count == 2 # Manifest and data download attempted
    mock_sha256.assert_called_once() # Checksum verified
    mock_tar_open.assert_called_once() # Extraction attempted
    mock_tar_context.extract.assert_called() # extract method was called
    
    # Check temp file cleanup was attempted (similar check as bad_checksum)
    # ... (Placeholder for os.remove mock check if needed) 