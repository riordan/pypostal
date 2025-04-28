import argparse
import os
import subprocess
import sys
import platform
import shutil
import multiprocessing
import re

from setuptools import setup, Extension, Command, find_packages
from setuptools.command.build_py import build_py
from setuptools.command.build_ext import build_ext as _build_ext
from setuptools.command.install import install
from distutils.errors import DistutilsArgError

this_dir = os.path.realpath(os.path.dirname(__file__))
vendor_dir = os.path.join(this_dir, 'vendor', 'libpostal')

# ===============================================================================
# Platform & architecture detection utilities
# ===============================================================================

def get_os_name():
    """Return a normalized OS name (macos, linux, windows)."""
    name = platform.system().lower()
    if name == 'darwin':
        return 'macos'
    return name

def normalize_arch(arch):
    """Normalize architecture names to standard values."""
    arch = arch.lower()
    if 'arm64' in arch or 'aarch64' in arch:
        return 'arm64'
    elif 'x86_64' in arch or 'amd64' in arch:
        return 'x86_64'
    elif 'x86' in arch or 'i686' in arch or 'win32' in arch:
        return 'x86'
    return arch

def get_target_arch():
    """Get the target architecture, considering CI environment variables."""
    # CIBW_ARCHS is set by cibuildwheel to the target architecture
    return normalize_arch(os.environ.get('CIBW_ARCHS', platform.machine()))

def is_universal2_build():
    """Check if this is a universal2 build."""
    return 'universal2' in os.environ.get('CIBW_ARCHS', '')

# ===============================================================================
# Version and cache management
# ===============================================================================

def get_libpostal_version():
    """Extract libpostal version from configure.ac."""
    version_file = os.path.join(vendor_dir, 'configure.ac')
    if not os.path.exists(version_file):
        return 'unknown'
    with open(version_file) as f:
        content = f.read()
    m = re.search(r'AC_INIT\(\[libpostal], ([0-9]+\.[0-9]+\.[0-9]+)\)', content)
    if m:
        return m.group(1)
    return 'unknown'

def get_libpostal_commit():
    """Get the current libpostal commit hash."""
    git_dir = os.path.join(vendor_dir, '.git')
    try:
        result = subprocess.run([
            'git', '--git-dir', git_dir, 'rev-parse', 'HEAD'
        ], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        # Fallback: try to read .git/HEAD directly
        head_file = os.path.join(git_dir, 'HEAD')
        if os.path.exists(head_file):
            with open(head_file) as f:
                ref = f.read().strip()
            if ref.startswith('ref:'):
                ref_path = os.path.join(git_dir, ref.split(' ', 1)[1])
                if os.path.exists(ref_path):
                    with open(ref_path) as rf:
                        return rf.read().strip()
            else:
                return ref
        return 'unknown'

def get_cache_dir(arch=None):
    """Get the cache directory for a specific architecture."""
    if arch is None:
        arch = get_target_arch()
    
    os_name = get_os_name()
    commit = get_libpostal_commit()
    
    base_dir = os.path.abspath(os.path.join('build', 'libpostal_install_cache'))
    return os.path.join(base_dir, f'{os_name}-{arch}-libpostal-{commit}')

# ===============================================================================
# Build environment configuration
# ===============================================================================

def get_arch_flags(arch=None):
    """Get architecture-specific compiler and linker flags."""
    if arch is None:
        arch = get_target_arch()
    
    os_name = get_os_name()
    
    cflags = []
    ldflags = []
    
    # Always add -fPIC for shared libraries
    cflags.append("-fPIC")
    
    # Architecture-specific flags
    if os_name == 'macos':
        if arch == 'arm64':
            cflags.append("-arch arm64")
            ldflags.append("-arch arm64")
        elif arch == 'x86_64':
            cflags.append("-arch x86_64")
            ldflags.append("-arch x86_64")
    
    # Special case: SSE2 flags are handled by configure.ac
    # (libpostal automatically disables SSE2 on ARM via --disable-sse2)
    
    return {
        'CFLAGS': ' '.join(cflags),
        'LDFLAGS': ' '.join(ldflags)
    }

def get_configure_options(arch=None, prefix=None):
    """Get configure options for libpostal build."""
    if arch is None:
        arch = get_target_arch()
    
    if prefix is None:
        prefix = get_cache_dir(arch)
    
    options = [
        '--disable-shared',
        '--enable-static',
        f'--prefix={prefix}'
    ]
    
    # Add --disable-sse2 flag for ARM architectures
    if 'arm' in arch:
        options.append('--disable-sse2')
    
    return options

def set_build_env(arch=None):
    """Set the environment variables for building libpostal."""
    arch_flags = get_arch_flags(arch)
    
    # Store original values
    original_cflags = os.environ.get('CFLAGS', '')
    original_ldflags = os.environ.get('LDFLAGS', '')
    
    # Set new values
    os.environ['CFLAGS'] = f"{original_cflags} {arch_flags['CFLAGS']}".strip()
    os.environ['LDFLAGS'] = f"{original_ldflags} {arch_flags['LDFLAGS']}".strip()
    
    print(f"Setting build environment: CFLAGS='{os.environ['CFLAGS']}', LDFLAGS='{os.environ['LDFLAGS']}'", flush=True)
    
    return {
        'CFLAGS': original_cflags,
        'LDFLAGS': original_ldflags
    }

def restore_build_env(original_env):
    """Restore the original environment variables."""
    os.environ['CFLAGS'] = original_env['CFLAGS']
    os.environ['LDFLAGS'] = original_env['LDFLAGS']
    print(f"Restoring environment: CFLAGS='{os.environ['CFLAGS']}', LDFLAGS='{os.environ['LDFLAGS']}'", flush=True)

# ===============================================================================
# Libpostal build functions
# ===============================================================================

def clean_libpostal_build_dir():
    """Clean the libpostal build directory."""
    print("[pypostal] Cleaning libpostal build directory", flush=True)
    makefile_path = os.path.join(vendor_dir, 'Makefile')
    if os.path.exists(makefile_path):
        try:
            subprocess.check_call(['make', 'clean'], cwd=vendor_dir)
        except Exception as e:
            print(f"[pypostal] Warning: 'make clean' failed: {e}", flush=True)
    else:
        print("[pypostal] Skipping 'make clean': Makefile not found.", flush=True)

def bootstrap_libpostal():
    """Run bootstrap.sh to set up libpostal build."""
    print("[pypostal] Running bootstrap.sh", flush=True)
    try:
        cmd = ['./bootstrap.sh']
        if get_os_name() == 'windows':
            cmd.insert(0, 'sh')
        subprocess.check_call(cmd, cwd=vendor_dir, stdout=sys.stdout, stderr=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Error running bootstrap.sh: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        if isinstance(e, FileNotFoundError):
            print(f"Error: Command '{cmd[0]}' not found. Is MSYS2/sh installed?", file=sys.stderr)
        else:
            print(f"OS error during bootstrap: {e}", file=sys.stderr)
        sys.exit(1)

def configure_libpostal(prefix, arch=None):
    """Configure libpostal with the given prefix and architecture."""
    print(f"[pypostal] Configuring libpostal for {arch if arch else get_target_arch()} with prefix {prefix}", flush=True)
    
    cmd = [
        os.path.join(vendor_dir, 'configure'),
        *get_configure_options(arch=arch, prefix=prefix)
    ]
    
    try:
        subprocess.check_call(cmd, cwd=vendor_dir, stdout=sys.stdout, stderr=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Error running ./configure: {e}", file=sys.stderr)
        # Optional: Capture and print config.log if it exists
        config_log = os.path.join(vendor_dir, 'config.log')
        if os.path.exists(config_log):
            print("--- config.log ---:")
            try:
                with open(config_log, 'r') as f:
                    print(f.read())
            except Exception as log_e:
                print(f"(Could not read config.log: {log_e})", file=sys.stderr)
            print("--- End config.log ---:")
        sys.exit(1)

def build_and_install_libpostal():
    """Build and install libpostal to the configured prefix."""
    print("[pypostal] Building and installing libpostal...", flush=True)
    try:
        num_cores = multiprocessing.cpu_count()
        subprocess.check_call(['make', '-j', str(num_cores)], cwd=vendor_dir, 
                             stdout=sys.stdout, stderr=sys.stderr)
        subprocess.check_call(['make', 'install'], cwd=vendor_dir, 
                             stdout=sys.stdout, stderr=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Error running make/make install: {e}", file=sys.stderr)
        sys.exit(1)

def verify_libpostal_arch(lib_path, expected_arch=None):
    """Verify that the built libpostal.a has the expected architecture."""
    if expected_arch is None:
        expected_arch = get_target_arch()
    
    if get_os_name() == 'macos':
        try:
            lipo_output = subprocess.check_output(['lipo', '-info', lib_path], 
                                                stderr=subprocess.STDOUT, text=True)
            print(f"Library architecture: {lipo_output.strip()}", flush=True)
            
            # Check if the expected architecture is present
            if expected_arch not in lipo_output.lower():
                print(f"WARNING: Library does not contain {expected_arch} architecture: {lipo_output}", flush=True)
                return False
            return True
        except Exception as e:
            print(f"Could not check architecture: {e}", flush=True)
    
    # For non-macOS or if lipo check fails, assume it's correct
    return True

def build_libpostal_for_arch(arch):
    """Build libpostal for a specific architecture."""
    print(f"[pypostal] Building libpostal for {arch}", flush=True)
    
    # Get the install prefix for this architecture
    install_prefix = get_cache_dir(arch)
    static_lib_path = os.path.join(install_prefix, 'lib', 'libpostal.a')
    
    # If library exists with correct architecture, no need to rebuild
    if os.path.exists(static_lib_path) and verify_libpostal_arch(static_lib_path, arch):
        print(f"[pypostal] Using cached libpostal build for {arch}", flush=True)
        return static_lib_path
    
    # Clean any previous build
    clean_libpostal_build_dir()
    
    # Ensure the install directory exists
    os.makedirs(install_prefix, exist_ok=True)
    
    # Set architecture-specific environment variables
    original_env = set_build_env(arch)
    
    try:
        # Bootstrap if needed
        if not os.path.exists(os.path.join(vendor_dir, 'configure')):
            bootstrap_libpostal()
        
        # Configure
        configure_libpostal(install_prefix, arch)
        
        # Build and install
        build_and_install_libpostal()
        
        # Verify build
        if not os.path.exists(static_lib_path):
            print(f"Error: Static library {static_lib_path} not found after build!", file=sys.stderr)
            sys.exit(1)
        
        if not verify_libpostal_arch(static_lib_path, arch):
            print(f"Error: Built library does not have the correct architecture: {arch}", file=sys.stderr)
            sys.exit(1)
        
        print(f"[pypostal] Successfully built libpostal for {arch}", flush=True)
        return static_lib_path
    
    finally:
        # Restore original environment
        restore_build_env(original_env)

def build_universal2_library():
    """Build a universal2 library by combining arm64 and x86_64 builds."""
    print("[pypostal] Building universal2 library", flush=True)
    
    # Get the cache directories for each architecture
    arm64_lib = build_libpostal_for_arch('arm64')
    x86_64_lib = build_libpostal_for_arch('x86_64')
    
    # Get the universal2 cache directory
    universal2_dir = get_cache_dir('universal2')
    universal2_lib_dir = os.path.join(universal2_dir, 'lib')
    universal2_include_dir = os.path.join(universal2_dir, 'include')
    universal2_lib_path = os.path.join(universal2_lib_dir, 'libpostal.a')
    
    # Create the universal2 directories
    os.makedirs(universal2_lib_dir, exist_ok=True)
    os.makedirs(universal2_include_dir, exist_ok=True)
    
    # Copy the include files (they should be the same from either build)
    arm64_include_dir = os.path.dirname(os.path.dirname(arm64_lib)) + '/include'
    subprocess.check_call(['cp', '-r', f"{arm64_include_dir}/", f"{universal2_include_dir}/"])
    
    # Create the universal2 library
    print(f"[pypostal] Creating universal2 library with lipo: {universal2_lib_path}", flush=True)
    lipo_cmd = ['lipo', '-create', '-output', universal2_lib_path, arm64_lib, x86_64_lib]
    subprocess.check_call(lipo_cmd)
    
    # Verify the universal2 library
    verify_libpostal_arch(universal2_lib_path, 'universal2')
    
    # Print diagnostic information
    os.system(f'lipo -info "{universal2_lib_path}"')
    os.system(f'ls -lh "{universal2_lib_path}"')
    
    return universal2_lib_path

# ===============================================================================
# Custom build_ext command
# ===============================================================================

class build_ext(_build_ext):
    def run(self):
        # Print diagnostic information
        arch = get_target_arch()
        os_name = get_os_name()
        print(f"[pypostal] Building for OS: {os_name}, Architecture: {arch}", flush=True)
        
        # Build libpostal for the current architecture or universal2
        if is_universal2_build():
            static_lib_path = build_universal2_library()
            install_prefix = os.path.dirname(os.path.dirname(static_lib_path))
        else:
            static_lib_path = build_libpostal_for_arch(arch)
            install_prefix = os.path.dirname(os.path.dirname(static_lib_path))
        
        # Get the include and lib directories
        include_dir = os.path.join(install_prefix, 'include')
        lib_dir = os.path.join(install_prefix, 'lib')
        
        # Update Extension paths
        print(f"[pypostal] Updating extension paths: include={include_dir}, lib={lib_dir}", flush=True)
        for ext in self.extensions:
            ext.include_dirs.insert(0, include_dir)
            ext.library_dirs.insert(0, lib_dir)
            
            # Clean up any redundant paths
            ext.include_dirs = [d for d in ext.include_dirs if d not in ('/usr/local/include',)]
            ext.library_dirs = [d for d in ext.library_dirs if d not in ('/usr/local/lib',)]
            ext.include_dirs = [d for d in ext.include_dirs if 'vendor/libpostal/src' not in d]
            
            print(f"[pypostal] Final paths for {ext.name}: include={ext.include_dirs}, lib={ext.library_dirs}", flush=True)
        
        # Set environment variables to help find the library
        os.environ['LIBRARY_PATH'] = lib_dir
        
        # Run the original build_ext command
        print("[pypostal] Running original build_ext command...", flush=True)
        _build_ext.run(self)
        
        # Print diagnostic information
        print("[pypostal] Extension build complete. Library details:", flush=True)
        for ext in self.extensions:
            ext_path = self.get_ext_fullpath(ext.name)
            if os.path.exists(ext_path):
                print(f"  {ext.name}: {ext_path}")
                if os_name == 'macos':
                    os.system(f'otool -L "{ext_path}"')
            else:
                print(f"  {ext.name}: NOT FOUND")

# ===============================================================================
# Main setup function
# ===============================================================================

def main():
    extensions = [
        Extension('postal._expand',
                  sources=['postal/pyexpand.c', 'postal/pyutils.c'],
                  libraries=['postal'],
                  extra_compile_args=['-std=c99'],
                  ),
        Extension('postal._parser',
                  sources=['postal/pyparser.c', 'postal/pyutils.c'],
                  libraries=['postal'],
                  extra_compile_args=['-std=c99'],
                  ),
        Extension('postal._token_types',
                  sources=['postal/pytokentypes.c'],
                  libraries=['postal'],
                  extra_compile_args=['-std=c99'],
                  ),
        Extension('postal._tokenize',
                  sources=['postal/pytokenize.c', 'postal/pyutils.c'],
                  libraries=['postal'],
                  extra_compile_args=['-std=c99'],
                  ),
        Extension('postal._normalize',
                  sources=['postal/pynormalize.c', 'postal/pyutils.c'],
                  libraries=['postal'],
                  extra_compile_args=['-std=c99'],
                  ),
        Extension('postal._near_dupe',
                  sources=['postal/pyneardupe.c', 'postal/pyutils.c'],
                  libraries=['postal'],
                  extra_compile_args=['-std=c99'],
                  ),
        Extension('postal._dedupe',
                  sources=['postal/pydedupe.c', 'postal/pyutils.c'],
                  libraries=['postal'],
                  extra_compile_args=['-std=c99'],
                  ),
    ]

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
