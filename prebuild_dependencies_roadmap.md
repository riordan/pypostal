# Pypostal Pre-built Dependency Roadmap

**Goal:** Transform `pypostal` into a Python package installable via `pip` (`pip install pypostal`) without requiring users to pre-install the `libpostal` C library or manually manage its data models.

**Core Strategy:**

1.  **Bundle `libpostal`:** Compile `libpostal` from source during the `pypostal` wheel building process and include the compiled library within the wheel.
2.  **Implement Model Management:** Add Python code to `pypostal` to discover, download, store, and configure the `libpostal` language models at runtime.

---

## Phase 1: Project Setup & Modernization

*Objective: Prepare the `pypostal` repository, modernize its packaging, and set up a basic CI workflow.* **(COMPLETED)**

*   [x] **1.1: Fork Repository:**
    [x]   Action: Create a fork of the `openvenues/pypostal` repository.
    [x]   Action: Create a dedicated branch for this pre-building effort.
*   [x] **1.2: Integrate `libpostal` Source:**
    *   [x] Action: Add `openvenues/libpostal` as a git submodule in a `vendor/` directory (`git submodule add https://github.com/openvenues/libpostal.git vendor/libpostal`).
    *   [x] Action: Update `.gitignore` to handle the submodule correctly if needed.
    *   *Outcome:* `libpostal` source code is version-controlled within the `pypostal` repository.
*   [x] **1.3: Modernize Python Packaging:**
    *   [x] Action: Create `pyproject.toml`.
    *   [x] Action: Define build system requirements (`setuptools`, `wheel`). Check if `cython` is needed.
    *   [x] Action: Specify `build-backend = "setuptools.build_meta"`.
    *   [x] Action: Migrate all metadata (name, version, author, description, license, etc.) from `setup.py`/`setup.cfg` to `[project]` section in `pyproject.toml`.
    *   [x] Action: Define minimal Python version required (`requires-python`).
    *   [x] Action: Define runtime dependencies in `[project.dependencies]`.
    *   [x] Action: Remove `setup.cfg`. Keep `setup.py` for now as it will contain the build logic for the C extension and `libpostal`.
    *   *Outcome:* Project uses `pyproject.toml` for configuration, adhering to modern Python packaging standards.
*   [x] **1.4: Setup Basic CI/CD (GitHub Actions):**
    *   [x] Action: Remove `.travis.yml` and `appveyor.yml`.
    *   [x] Action: Create `.github/workflows/build_lint.yml` (or similar name).
    *   [x] Action: Configure the workflow to trigger on pushes/pull requests to the main/development branches.
    *   [x] Action: Add steps to:
        *   Check out the code (`actions/checkout@v4` with `submodules: true`).
        *   Set up Python.
        *   (Optional) Run linters/formatters (e.g., `black`, `flake8`).
        *   Attempt a basic package build (`python -m build --sdist`).
    *   *Outcome:* A basic CI workflow is in place, checking out submodules correctly.

---

## Phase 2: Bundling `libpostal` into Wheels

*Objective: Modify the build process to compile `libpostal` and link it into the `pypostal` C extension, then use `cibuildwheel` to generate multi-platform wheels.* **(COMPLETED)**

*   [x] **2.1: Customize Build Script (`setup.py`):**
    *   [x] Action: Define a custom build step (subclass `build_ext`).
    *   [x] Action: Implement logic within the custom step to:
        *   [x] Determine platform/architecture.
        *   [x] Clean build dir (`clean_libpostal_build_dir` - Note: Switched back from `git clean`).
        *   [x] Run `bootstrap.sh`.
        *   [x] Run `configure` with static linking, prefix, and conditional flags (`--disable-sse2`).
        *   [x] Run `make -jN` and `make install` into cache/prefix.
        *   [x] Handle build errors.
        *   [x] Set `-fPIC` flag (via `get_arch_flags`).
    *   [x] Action: Configure C extensions (`Extension` objects) to use include/lib dirs from the prefix.
    *   *Outcome:* `python -m build` successfully compiles `libpostal` and links the extension against the static library.

*   [x] **2.2: Integrate `cibuildwheel` into CI:**
    *   [x] Action: Create separate workflows for Linux (`build_wheels_linux.yml`) and macOS (`build_wheels_macos.yml`).
    *   [x] Action: Use the `cibuildwheel` action.
    *   [x] Action: Use matrix strategy for Linux (x86_64, aarch64) and macOS (x86_64, arm64).
    *   [x] Action: Install build dependencies using `dnf` / `brew` in `CIBW_BEFORE_BUILD_*`.
    *   [x] Action: Specify `manylinux_2_28` images.
    *   [x] Action: Define `CIBW_TEST_COMMAND` to use `scripts/test_wheel.py`.
    *   [x] Action: Configure artifact uploads.
    *   [x] Action: Refactored workflows to use workflow-level `env:` for common variables.
    *   [x] Action: Disabled `actions/cache` for `libpostal` builds to simplify debugging.
    *   *Outcome:* CI successfully builds binary wheels for Linux and macOS across target architectures.

*   [ ] ~~**2.3: Major Multi-Arch Build/Cache Refactor:**~~ (Superseded by separate jobs/matrix approach)
    *   *Outcome:* Robust multi-arch builds achieved via separate jobs/matrix per OS.

---

## Phase 3: Runtime Model Management

*Objective: Implement Python code within `pypostal` to handle the discovery, download, caching, and loading of `libpostal` data models.* **(COMPLETED)**

*   [x] **3.1: Design Model Hosting & Manifest:**
    *   [x] Action: Decided to use existing S3/GitHub URLs for default/Senzing models initially.
    *   [x] Action: Defined multi-component `models.json` structure (base, parser, lc) with URLs and SHA256 checksums.
    *   [x] Action: Created `metadata/models.json` with info for "default" (v1.0) and "senzing" (v1.1) models.
    *   [x] Action: Hosting `models.json` within the repository (`metadata/models.json`).
    *   *Outcome:* Clear plan and initial implementation for model metadata.
*   [x] **3.2: Implement Downloader Module (`postal/downloader.py`):**
    *   [x] Action: Created `postal/downloader.py`.
    *   [x] Action: Added runtime dependencies (`requests`, `platformdirs`, `tqdm`) to `pyproject.toml`.
    *   [x] Action: Implemented `get_cache_dir()` using `platformdirs` (using `libpostal`/`libpostal` names).
    *   [x] Action: Implemented `_fetch_manifest()`, `list_available_models()`.
    *   [x] Action: Implemented `get_downloaded_models()` and `get_data_dir()` using a helper (`_is_model_dir_complete`) to check for all 3 data components.
    *   [x] Action: Refactored `download_model(version='default', force=False)` to handle downloading/extracting multiple components (base, parser, lc) per model version.
    *   [x] Action: Added type hints to `postal/downloader.py`.
    *   *Outcome:* Python module capable of managing download/cache for multi-component models.
*   [x] **3.3: Integrate Model Loading into `pypostal`:**
    *   [x] Action: Identified C API calls (`libpostal_setup_datadir`, `libpostal_setup_language_classifier_datadir`, `libpostal_setup_parser_datadir`).
    *   [x] Action: Created new C extension `postal/_capi.c` with `setup_datadir` function wrapping the C API calls.
    *   [x] Action: Updated `setup.py` to build the `_capi` extension.
    *   [x] Action: Removed automatic initialization logic from existing C extensions (`_expand`, `_parser`, etc.).
    *   [x] Action: Created `postal.initialize(model_key='default')` function in `postal/__init__.py`.
    *   [x] Action: `initialize` checks `LIBPOSTAL_DATA_DIR` env var first, then falls back to downloader cache (`get_data_dir`).
    *   [x] Action: `initialize` calls `_capi.setup_datadir`.
    *   [x] Action: Implemented `PostalDataNotFound` exception with helpful message.
    *   [x] Action: Exposed `download_model` publicly via `postal/__init__.py`.
    *   *Outcome:* `pypostal` uses explicit `initialize()` call to configure C library via downloader cache or env var. Requires `initialize()` before use.
*   [x] **3.4: Update CI Test Command:**
    *   [x] Action: Modified `CIBW_TEST_COMMAND` to point to `scripts/test_wheel.py`.
    *   [x] Action: Updated `scripts/test_wheel.py` to call `postal.download_model()` and `postal.initialize()` before running functional tests.
    *   *Outcome:* CI tests validate the download and initialization mechanism.

---

## Phase 4: Documentation & Testing

*Objective: Update documentation for the new installation and usage patterns, and add comprehensive tests.*

*   [ ] **4.1: Update `README.md`:**
    *   [ ] Action: Replace installation instructions with `pip install pypostal`.
    *   [ ] Action: Remove prerequisites about compiling `libpostal`.
    *   [ ] Action: Add section explaining automatic model downloading/caching and the `LIBPOSTAL_DATA_DIR` precedence.
    *   [ ] Action: Document `postal.initialize()` and its mandatory nature.
    *   [ ] Action: Document `postal.download_model()` usage (including `version` and `force` args).
    *   [ ] Action: Document how to specify different model versions (`default`, `senzing`).
    *   [ ] Action: Update examples to include `postal.initialize()`.
    *   *Outcome:* README accurately reflects the new user experience.
*   [~] **4.2: Add Unit & Integration Tests:**
    *   [x] Action: Added unit tests for `postal.downloader` with mocks.
    *   [ ] Action: Add integration tests (using `pytest`?) that:
        *   Perform actual downloads (can be marked or skipped in environments without network).
        *   Verify initialization works with downloaded data for both `default` and `senzing` models.
        *   Test `expand_address` and `parse_address` with known inputs/outputs for both models.
        *   Test error handling when data is missing or invalid.
    *   [ ] Action: Integrate test execution into the CI workflow (run after wheel installation, potentially separate from `cibuildwheel` test step).
    *   *Outcome:* Basic downloader tests exist. Need comprehensive integration tests.

---

## Phase 5: Release

*Objective: Prepare and publish the new version of `pypostal`.*

*   [ ] **5.1: Version Bump:** Decide on new version number (significant change, likely `2.0.0` or similar). Update `pyproject.toml`.
*   [ ] **5.2: Final Testing:** Perform thorough testing across all supported platforms.
*   [ ] **5.3: Tag Release:** Create git tag for the release.
*   [ ] **5.4: Publish to PyPI:** Configure CI to automatically build wheels on tag and upload to PyPI using an API token.
*   [ ] **5.5: Update `pypostal` Main Repository:** Merge changes from fork/branch back into the main `openvenues/pypostal` repository (requires coordination).

---

## Maintenance & Future Considerations

*   **Submodule Updates:** Periodically update the `vendor/libpostal` git submodule to incorporate upstream bug fixes and improvements (`git submodule update --remote vendor/libpostal`), re-testing the build process afterwards.
*   **Performance Optimizations:**
    *   Investigate enabling CBLAS (`openblas-devel` on Linux, Accelerate on macOS?) via `./configure` flags and benchmark impact.
    *   Explore native NEON intrinsics for ARM performance if `sse2neon.h` translation is insufficient.
    *   Profile other potential bottlenecks (string handling, memory allocation).
*   **Model Management:**
    *   [x] Support for alternative models (e.g., `MODEL=senzing`): Implemented via `postal.initialize(model_key=...)` and `models.json` manifest.
    *   [x] Configuration options for cache directory location: Handled via `LIBPOSTAL_DATA_DIR` env var precedence.
    *   [x] Allowing users to provide pre-downloaded/extracted model data directories: Handled via `LIBPOSTAL_DATA_DIR` env var precedence.
*   **Build Process:**
    *   Investigate static linking vs shared library bundling trade-offs more deeply.
    *   Refine error handling and reporting in custom build steps.
    *   Revisit build cleaning (`git clean -fdx` vs `make distclean`) if macOS build stability issues reappear.
