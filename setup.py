import argparse
import os
import subprocess
import sys
import platform
import shutil
import multiprocessing

from setuptools import setup, Extension, Command, find_packages
from setuptools.command.build_py import build_py
from setuptools.command.build_ext import build_ext as _build_ext
from setuptools.command.install import install
from distutils.errors import DistutilsArgError

this_dir = os.path.realpath(os.path.dirname(__file__))
vendor_dir = os.path.join(this_dir, 'vendor', 'libpostal')

# VERSION = '1.1.10' # Read from pyproject.toml ideally, but setup.py runs first
# For now, let setuptools handle version via pyproject.toml

# Custom build_ext command
class build_ext(_build_ext):
    def run(self):
        print("::group::Determine Target Architecture") # Start group
        # --- Determine Target Architecture from cibuildwheel --- 
        target_arch = os.environ.get('CIBW_ARCHS', platform.machine())
        # Normalize arch string for directory naming (e.g., x86_64 -> x86_64)
        # This handles potential variations like 'native' or lists in CIBW_ARCHS
        # A simple approach for now, might need refinement for universal2 etc.
        if 'arm64' in target_arch or 'aarch64' in target_arch:
            norm_arch = 'arm64' # Use a consistent name
        elif 'x86_64' in target_arch or 'AMD64' in target_arch:
             norm_arch = 'x86_64'
        elif 'x86' in target_arch or 'i686' in target_arch or 'win32' in target_arch:
             norm_arch = 'x86'
        else:
             norm_arch = target_arch # Use as-is if unknown
        print(f"Normalized target architecture for cache dir: {norm_arch}", flush=True)
        print("::endgroup::") # End group

        print("::group::Check libpostal build cache") # Start group
        # Define shared, architecture-specific paths
        # Use a directory outside the standard temp build dir to persist across python versions
        cache_base_dir = os.path.abspath(os.path.join('build', 'libpostal_install_cache'))

        # Adjust install path based on OS
        if platform.system() == 'Darwin':
            # On macOS, install directly into the base cache dir because the 
            # 'universal' matrix entry uses a single cache key, but cibuildwheel
            # builds both x86_64 and arm64 sequentially in the same job.
            # Installing into arch-specific subdirs would cause cache misses.
            print("Detected macOS, installing libpostal directly into cache base directory for universal caching.", flush=True)
            libpostal_install_prefix = cache_base_dir
        else:
            # On Linux/Windows, use architecture-specific subdirectories
            libpostal_install_prefix = os.path.join(cache_base_dir, norm_arch)
        
        libpostal_lib_dir = os.path.join(libpostal_install_prefix, 'lib')
        libpostal_include_dir = os.path.join(libpostal_install_prefix, 'include')
        libpostal_static_lib = os.path.join(libpostal_lib_dir, 'libpostal.a')

        # Check if libpostal is already built for this architecture
        needs_build = not os.path.exists(libpostal_static_lib)
        if needs_build:
            # Use notice annotation for cache miss
            print(f"::notice title=Cache Miss::No cached libpostal build found for {norm_arch} at {libpostal_static_lib}, building now...", flush=True)
            print("::endgroup::") # End group (cache check)
        else:
            # Use notice annotation for cache hit
            print(f"::notice title=Cache Hit::Found cached libpostal build for {norm_arch} at {libpostal_install_prefix}", flush=True)
            print("::endgroup::") # End group (cache check)


        if needs_build:
            print("::group::Build libpostal from source") # Start build group
            original_cflags = os.environ.get('CFLAGS', '') # Define here for use in finally block

            try:
                # Ensure install directories exist
                os.makedirs(libpostal_install_prefix, exist_ok=True)

                # --- Copy Windows-specific files (if on Windows) --- #
                if platform.system() == 'Windows':
                    print("::group::Copying Windows-specific files")
                    print("Copying files from vendor/libpostal/windows/ to vendor/libpostal/", flush=True)
                    windows_dir = os.path.join(vendor_dir, 'windows')
                    if os.path.isdir(windows_dir):
                        # Use shutil.copytree for robustness if Python version allows `dirs_exist_ok`
                        # For simplicity/compatibility, copy file by file
                        for item_name in os.listdir(windows_dir):
                            src_item = os.path.join(windows_dir, item_name)
                            dst_item = os.path.join(vendor_dir, item_name)
                            try:
                                if os.path.isfile(src_item):
                                    shutil.copy2(src_item, dst_item)
                                elif os.path.isdir(src_item):
                                    # Avoid copying subdirs for now unless needed
                                    # shutil.copytree(src_item, dst_item, dirs_exist_ok=True) 
                                    pass 
                            except Exception as e:
                                print(f"Warning: Could not copy {src_item} to {dst_item}: {e}", file=sys.stderr)
                    else:
                        print("Warning: vendor/libpostal/windows/ directory not found.", file=sys.stderr)
                    print("::endgroup::") # End Windows copy group
                # --------------------------------------------------- #

                # Check if libpostal source exists and run bootstrap.sh if needed
                configure_path = os.path.join(vendor_dir, 'configure')
                if not os.path.exists(configure_path):
                    print("::group::Running bootstrap.sh")
                    print("libpostal source not found or configure script missing, running bootstrap.sh", flush=True)
                    try:
                        cmd = ['./bootstrap.sh']
                        if platform.system() == 'Windows':
                            cmd.insert(0, 'sh') 
                        subprocess.check_call(cmd, cwd=vendor_dir, stdout=sys.stdout, stderr=sys.stderr)
                    except subprocess.CalledProcessError as e:
                        print(f"::error title=Bootstrap Failed::Error running bootstrap.sh: {e}", file=sys.stderr)
                        print("::endgroup::") # End bootstrap group
                        print("::endgroup::") # End build group
                        sys.exit(1)
                    except OSError as e:
                        if isinstance(e, FileNotFoundError):
                            print(f"::error title=Bootstrap Failed::Command '{cmd[0]}' not found. Is MSYS2/sh installed and in PATH?", file=sys.stderr)
                        else:
                            print(f"::error title=Bootstrap Failed::Error running bootstrap.sh (OS error): {e}", file=sys.stderr)
                        print("::endgroup::") # End bootstrap group
                        print("::endgroup::") # End build group
                        sys.exit(1)
                    print("--- bootstrap.sh complete ---", flush=True)
                    print("::endgroup::") # End bootstrap group

                # Configure libpostal
                print("::group::Running ./configure")
                sys.stdout.flush()
                print(f"Configuring libpostal with prefix {libpostal_install_prefix}", flush=True)
                configure_cmd = [
                    os.path.join(vendor_dir, 'configure'), # Use absolute path
                    '--disable-shared', 
                    '--enable-static', 
                    f'--prefix={libpostal_install_prefix}'
                ]
                if 'arm64' in norm_arch:
                    if '--disable-sse2' not in configure_cmd:
                         print(f"Detected ARM64 TARGET ({platform.system()}), adding --disable-sse2 flag", flush=True)
                         configure_cmd.append('--disable-sse2')
                elif platform.system() == 'Darwin':
                     print(f"Detected macOS non-ARM64 TARGET ({norm_arch}), NOT adding --disable-sse2 flag", flush=True)
                
                # Set CFLAGS for PIC (do this just before configure)
                pic_cflags = original_cflags + ' -fPIC'
                print(f"Temporarily setting CFLAGS to: {pic_cflags}", flush=True)
                os.environ['CFLAGS'] = pic_cflags

                try:
                    subprocess.check_call(configure_cmd, cwd=vendor_dir, stdout=sys.stdout, stderr=sys.stderr)
                    print("--- Configure complete ---", flush=True)
                except subprocess.CalledProcessError as e:
                    print(f"::error title=Configure Failed::Error running ./configure: {e}", file=sys.stderr)
                    config_log = os.path.join(vendor_dir, 'config.log')
                    if os.path.exists(config_log):
                        print("::group::config.log output") # Group for config.log
                        try:
                            with open(config_log, 'r') as f:
                                print(f.read())
                        except Exception as log_e:
                            print(f"(Could not read config.log: {log_e})", file=sys.stderr)
                        print("::endgroup::") # End config.log group
                    print("::endgroup::") # End configure group
                    print("::endgroup::") # End build group
                    sys.exit(1) # Exit handled within finally
                finally:
                    # Restore CFLAGS immediately after configure attempt
                    print(f"Restoring CFLAGS after configure attempt to: {original_cflags}", flush=True)
                    os.environ['CFLAGS'] = original_cflags
                print("::endgroup::") # End configure group


                # Build and install libpostal
                print("::group::Running make and make install")
                sys.stdout.flush()
                print("Building and installing libpostal...", flush=True)
                try:
                    print("--- Running make clean ---", flush=True)
                    subprocess.check_call(['make', 'clean'], cwd=vendor_dir, stdout=sys.stdout, stderr=sys.stderr)
                    
                    print("--- Running make -jN ---", flush=True)
                    num_cores = multiprocessing.cpu_count()
                    subprocess.check_call(['make', '-j', str(num_cores)], cwd=vendor_dir, stdout=sys.stdout, stderr=sys.stderr)
                    
                    print("--- Running make install ---", flush=True)
                    subprocess.check_call(['make', 'install'], cwd=vendor_dir, stdout=sys.stdout, stderr=sys.stderr)
                    print("--- Build and install complete ---", flush=True)
                except subprocess.CalledProcessError as e:
                    print(f"::error title=Make Failed::Error running make/make install: {e}", file=sys.stderr)
                    print("::endgroup::") # End make group
                    print("::endgroup::") # End build group
                    sys.exit(1)
                print("::endgroup::") # End make group


                # Check if static library was created
                if not os.path.exists(libpostal_static_lib):
                     print(f"::error title=Build Failed::Static library {libpostal_static_lib} not found after build!", file=sys.stderr)
                     print("::endgroup::") # End build group
                     sys.exit(1)
                else:
                     print(f"::notice title=Build Success::Successfully built and installed libpostal for {norm_arch} to {libpostal_install_prefix}", flush=True)

            except SystemExit as e:
                 print("::endgroup::") # Ensure build group is closed on sys.exit
                 raise e # Re-raise to exit
            except Exception as e:
                 # Catch any other unexpected errors during build
                 print(f"::error title=Build Failed::Unexpected error during build: {e}", file=sys.stderr)
                 print("::endgroup::") # Ensure build group is closed
                 sys.exit(1)
            finally:
                 # Ensure CFLAGS is restored if something went wrong after setting it
                 # (Configure's finally block already handles the configure stage)
                 # Check if pic_cflags was set before trying to restore original_cflags
                 # Note: This finally might be redundant due to try/finally around configure
                 # and explicit restore on make error, but added for safety.
                 if os.environ.get('CFLAGS') != original_cflags:
                      print(f"Restoring CFLAGS in outer finally block to: {original_cflags}", flush=True)
                      os.environ['CFLAGS'] = original_cflags

            print("::endgroup::") # End build group (successful path)

        # ----- End of Conditional Build ----- #

        print("::group::Update Python extension paths") # Start group
        # Update Extension paths *before* calling the original build_ext
        # Always point to the shared architecture-specific cache location
        print(f"Updating extension paths to use cache: include={libpostal_include_dir}, lib={libpostal_lib_dir}", flush=True)
        
        # --- Add macOS specific linker args for static linking ---
        macos_link_args = []
        if platform.system() == 'Darwin':
            # Construct the full path to the static library
            static_lib_path = os.path.join(libpostal_lib_dir, 'libpostal.a')
            if os.path.exists(static_lib_path):
                # Force load the static library. This might be needed on macOS 
                # to ensure the static lib code is included in the final extension.
                print(f"Adding force_load linker arg for: {static_lib_path}", flush=True)
                # Use separate args for -Wl, and the option itself
                macos_link_args.extend(['Wl,-force_load', static_lib_path]) 
            else:
                print(f"::warning::Static library not found at {static_lib_path} when setting link args!", flush=True)
        # --------------------------------------------------------

        for ext in self.extensions:
            # Add install path to include and library dirs
            # Ensure they are added at the beginning to take precedence
            if libpostal_include_dir not in ext.include_dirs:
                 ext.include_dirs.insert(0, libpostal_include_dir)
            if libpostal_lib_dir not in ext.library_dirs:
                 ext.library_dirs.insert(0, libpostal_lib_dir)
            
            # Remove old absolute/relative paths if they exist (optional, but cleaner)
            ext.include_dirs = [d for d in ext.include_dirs if d not in ('/usr/local/include',)]
            ext.library_dirs = [d for d in ext.library_dirs if d not in ('/usr/local/lib',)]

            # Remove vendored src include dir as headers should come from install prefix
            ext.include_dirs = [d for d in ext.include_dirs if 'vendor/libpostal/src' not in d]

            # Add macOS specific linker args if any
            if macos_link_args:
                ext.extra_link_args.extend(macos_link_args)

            print(f"Final paths for {ext.name}: include={ext.include_dirs}, lib={ext.library_dirs}, link_args={ext.extra_link_args}", flush=True)

        # --- Set environment variables to help find the library --- #
        # On macOS, LIBRARY_PATH can help the linker find libraries
        # Set it even if using cache, as linker needs it when building extension
        print(f"Setting LIBRARY_PATH to: {libpostal_lib_dir}", flush=True)
        os.environ['LIBRARY_PATH'] = libpostal_lib_dir
        print("::endgroup::") # End group

        print("::notice title=Build Step::Running original setuptools build_ext command...", flush=True)
        _build_ext.run(self)
        print("::notice title=Build Step::Finished original setuptools build_ext command.", flush=True)


def main():
    # --- Determine install paths needed for library definition ---
    # This logic is duplicated from build_ext, which isn't ideal, but needed
    # because the Extension objects are defined *before* build_ext.run() happens.
    target_arch = os.environ.get('CIBW_ARCHS', platform.machine())
    if 'arm64' in target_arch or 'aarch64' in target_arch:
        norm_arch = 'arm64'
    elif 'x86_64' in target_arch or 'AMD64' in target_arch:
         norm_arch = 'x86_64'
    else: norm_arch = 'x86' # Fallback, adjust if needed
    cache_base_dir = os.path.abspath(os.path.join('build', 'libpostal_install_cache'))
    if platform.system() == 'Darwin':
        libpostal_install_prefix = cache_base_dir
    else:
        libpostal_install_prefix = os.path.join(cache_base_dir, norm_arch)
    libpostal_lib_dir = os.path.join(libpostal_install_prefix, 'lib')
    libpostal_static_lib_path = os.path.join(libpostal_lib_dir, 'libpostal.a')
    # -------------------------------------------------------------

    # Define libraries list based on OS
    link_libraries = []
    if platform.system() == 'Darwin':
        # On macOS, try linking directly against the static library path
        print(f"macOS detected: Will attempt to link directly against {libpostal_static_lib_path}", flush=True)
        # Note: We still need the -L path set by build_ext for the linker to find dependencies if any.
        # Pass the full path to the static library directly instead of using -lpostal.
        link_libraries.append(libpostal_static_lib_path)
    else:
        # On other systems (Linux), use the standard library name
        link_libraries.append('postal')

    extensions = [
            Extension('postal._expand',
                      sources=['postal/pyexpand.c', 'postal/pyutils.c'],
                      libraries=link_libraries, # Use dynamically determined list
                      # library_dirs=[libpostal_lib_dir], # Let build_ext handle library_dirs
                      extra_compile_args=['-std=c99'],
                      # extra_link_args=macos_link_args if platform.system() == 'Darwin' else [] # Let build_ext handle link args for now
                      ),
            Extension('postal._parser',
                      sources=['postal/pyparser.c', 'postal/pyutils.c'],
                      libraries=link_libraries,
                      extra_compile_args=['-std=c99'],
                      ),
            Extension('postal._token_types',
                      sources=['postal/pytokentypes.c'],
                      libraries=link_libraries,
                      extra_compile_args=['-std=c99'],
                      ),
            Extension('postal._tokenize',
                      sources=['postal/pytokenize.c', 'postal/pyutils.c'],
                      libraries=link_libraries,
                      extra_compile_args=['-std=c99'],
                      ),
            Extension('postal._normalize',
                      sources=['postal/pynormalize.c', 'postal/pyutils.c'],
                      libraries=link_libraries,
                      extra_compile_args=['-std=c99'],
                      ),
            Extension('postal._near_dupe',
                      sources=['postal/pyneardupe.c', 'postal/pyutils.c'],
                      libraries=link_libraries,
                      extra_compile_args=['-std=c99'],
                      ),
            Extension('postal._dedupe',
                      sources=['postal/pydedupe.c', 'postal/pyutils.c'],
                      libraries=link_libraries,
                      extra_compile_args=['-std=c99'],
                      ),
        ]

    # Remove the extra_link_args logic from build_ext.run as we try a different approach
    # (Need to read build_ext.run again to apply this cleanly)
    
    # Read build_ext.run to remove the link_args logic
    # This is complex to do reliably with edit_file, might need separate steps
    # For now, just focus on adding the logic in main()

    setup(
        ext_modules=extensions,
        packages=find_packages(),
        package_data={
            'postal': ['*.h'] 
        },
        zip_safe=False, 
        cmdclass={'build_ext': build_ext}, 
    )


if __name__ == '__main__':
    main()
