# ******************************************************************************
#  Copyright (c) 2023 Orbbec 3D Technology, Inc
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http:# www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# ******************************************************************************

import os
import sys
import shutil
import platform
import subprocess
from pathlib import Path
from typing import List, Optional

from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext
from wheel.bdist_wheel import bdist_wheel as _bdist_wheel


class PrebuiltExtension(Extension):
    """扩展类，用于预编译的库文件"""
    def __init__(self, name: str, lib_dir: str = ''):
        super().__init__(name, sources=[])  # 没有源码需要编译
        self.lib_dir = os.path.abspath(lib_dir)


class CustomBuildExt(build_ext):
    """自定义构建扩展，复制预编译的库文件"""
    
    def run(self):
        """运行构建扩展"""
        for ext in self.extensions:
            self.build_extension(ext)
            
        # 复制完成后，确保所有文件都有正确的权限
        self._fix_file_permissions()

    def build_extension(self, ext: PrebuiltExtension):
        """构建单个扩展"""
        # 检查库目录是否存在且包含文件
        if not os.path.isdir(ext.lib_dir):
            raise FileNotFoundError(
                f"Directory '{ext.lib_dir}' does not exist. "
                "Please compile the necessary components with CMake as described in the README."
            )
        
        lib_files = list(Path(ext.lib_dir).rglob("*"))
        if not lib_files:
            raise FileNotFoundError(
                f"Directory '{ext.lib_dir}' is empty. "
                "Please run 'make install' to install the compiled libraries first."
            )
        
        print(f"Found {len(lib_files)} files in {ext.lib_dir}")
        
        # 获取目标扩展目录
        extdir = os.path.abspath(os.path.dirname(self.get_ext_fullpath(ext.name)))
        os.makedirs(extdir, exist_ok=True)
        
        # 复制所有文件
        self.copy_all_files(ext.lib_dir, extdir)
        
        # 记录复制的文件
        self._record_installed_files(extdir)
    
    def copy_all_files(self, source_dir: str, destination_dir: str):
        """递归复制所有文件，保留符号链接"""
        os.makedirs(destination_dir, exist_ok=True)
        
        for item in os.listdir(source_dir):
            source_path = os.path.join(source_dir, item)
            destination_path = os.path.join(destination_dir, item)
            
            if os.path.islink(source_path):
                # 处理符号链接
                link_target = os.readlink(source_path)
                # 如果是相对路径，转换为绝对路径
                if not os.path.isabs(link_target):
                    link_target = os.path.join(os.path.dirname(source_path), link_target)
                
                # 确保目标存在
                if os.path.exists(destination_path):
                    if os.path.islink(destination_path):
                        os.unlink(destination_path)
                    else:
                        shutil.rmtree(destination_path)
                
                # 创建符号链接
                try:
                    # 尝试创建相对路径链接
                    rel_target = os.path.relpath(link_target, os.path.dirname(destination_path))
                    os.symlink(rel_target, destination_path)
                    print(f"Created symbolic link: {destination_path} -> {rel_target}")
                except (OSError, ValueError):
                    # 回退到绝对路径
                    os.symlink(link_target, destination_path)
                    print(f"Created symbolic link: {destination_path} -> {link_target}")
                    
            elif os.path.isdir(source_path):
                # 递归复制目录
                self.copy_all_files(source_path, destination_path)
            else:
                # 复制文件
                shutil.copy2(source_path, destination_path)
                print(f"Copied: {source_path} -> {destination_path}")
    
    def _fix_file_permissions(self):
        """修复文件权限（特别是可执行文件）"""
        for ext in self.extensions:
            extdir = os.path.abspath(os.path.dirname(self.get_ext_fullpath(ext.name)))
            if os.path.exists(extdir):
                for root, dirs, files in os.walk(extdir):
                    for file in files:
                        filepath = os.path.join(root, file)
                        # 给共享库文件添加执行权限
                        if filepath.endswith(('.so', '.dylib')) or '.so.' in file:
                            os.chmod(filepath, os.stat(filepath).st_mode | 0o755)
    
    def _record_installed_files(self, extdir: str):
        """记录安装的文件（用于调试）"""
        installed_files = []
        for root, dirs, files in os.walk(extdir):
            for file in files:
                installed_files.append(os.path.relpath(os.path.join(root, file), extdir))
        
        print(f"Installed {len(installed_files)} files:")
        for file in sorted(installed_files):
            print(f"  - {file}")


class PlatformSpecificWheel(_bdist_wheel):
    """自定义 wheel 构建，设置正确的平台标签"""
    
    def get_tag(self):
        """获取 wheel 标签 (python, abi, platform)"""
        python, abi, plat = super().get_tag()
        
        # 根据操作系统设置正确的平台标签
        system = platform.system().lower()
        
        if system == "linux":
            # Linux 系统使用 manylinux 标签
            plat = self._get_linux_platform_tag(plat)
        elif system == "darwin":
            # macOS 系统
            plat = self._get_macos_platform_tag(plat)
        elif system == "windows":
            # Windows 系统
            plat = self._get_windows_platform_tag(plat)
        
        return python, abi, plat
    
    def _get_linux_platform_tag(self, plat: str) -> str:
        """获取 Linux 平台标签"""
        # 检查 glibc 版本
        try:
            # 方法1: 使用 ldd
            result = subprocess.run(
                ['ldd', '--version'],
                capture_output=True,
                text=True,
                check=False
            )
            
            if 'glibc' in result.stdout or 'GLIBC' in result.stdout:
                # 提取 glibc 版本
                import re
                match = re.search(r'(\d+\.\d+)(\.\d+)?', result.stdout)
                if match:
                    glibc_version = match.group(1)
                    print(f"Detected glibc version: {glibc_version}")
                    
                    # 根据 glibc 版本选择 manylinux 标签
                    if glibc_version >= '2.35':
                        return 'manylinux_2_35_x86_64'
                    elif glibc_version >= '2.34':
                        return 'manylinux_2_34_x86_64'
                    elif glibc_version >= '2.31':
                        return 'manylinux_2_31_x86_64'
                    elif glibc_version >= '2.17':
                        return 'manylinux_2_17_x86_64'
                    else:
                        return 'manylinux_2_12_x86_64'
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        
        # 方法2: 检查文件系统特征
        try:
            # 检查 /lib64/libc.so.6 是否存在
            libc_path = '/lib64/libc.so.6'
            if os.path.exists(libc_path):
                # 默认使用较新的 manylinux 标签以确保兼容性
                return 'manylinux_2_34_x86_64'
        except:
            pass
        
        # 默认值
        return 'manylinux_2_34_x86_64'
    
    def _get_macos_platform_tag(self, plat: str) -> str:
        """获取 macOS 平台标签"""
        # 检查架构
        arch = platform.machine().lower()
        if arch == 'arm64':
            return 'macosx_11_0_arm64'  # Apple Silicon
        else:
            return 'macosx_10_15_x86_64'  # Intel
    
    def _get_windows_platform_tag(self, plat: str) -> str:
        """获取 Windows 平台标签"""
        if 'amd64' in plat or 'x64' in plat:
            return 'win_amd64'
        else:
            return 'win32'


def read_long_description():
    """读取长描述（从 README.md）"""
    readme_path = Path(__file__).parent / "README.md"
    if readme_path.exists():
        try:
            return readme_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return readme_path.read_text(encoding="latin-1")
    return ""


def get_requirements():
    """读取依赖 requirements"""
    req_path = Path(__file__).parent / "requirements.txt"
    if req_path.exists():
        with open(req_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return []


def check_prerequisites():
    """检查前置条件"""
    errors = []
    
    # 检查 install/lib 目录
    lib_dir = Path(__file__).parent / "install" / "lib"
    if not lib_dir.exists():
        errors.append(f"Directory '{lib_dir}' does not exist.")
    elif not any(lib_dir.iterdir()):
        errors.append(f"Directory '{lib_dir}' is empty.")
    
    # 检查关键库文件
    if lib_dir.exists():
        # 查找常见的库文件扩展
        library_extensions = {'.so', '.dylib', '.dll', '.pyd', '.a', '.lib'}
        has_libs = any(
            file.suffix in library_extensions 
            for file in lib_dir.rglob('*')
        )
        if not has_libs:
            errors.append(f"No library files found in '{lib_dir}'")
    
    if errors:
        error_msg = "\n".join(errors)
        error_msg += "\n\nPlease compile the C++ SDK first:\n"
        error_msg += "1. mkdir build && cd build\n"
        error_msg += "2. cmake -Dpybind11_DIR=$(python -c 'import pybind11; print(pybind11.get_cmake_dir())') ..\n"
        error_msg += "3. make -j4\n"
        error_msg += "4. make install\n"
        raise RuntimeError(error_msg)


# 在运行 setup() 前检查前置条件
try:
    check_prerequisites()
except RuntimeError as e:
    print(f"Warning: {e}")
    print("Continuing setup, but installation may fail if libraries are missing.")


setup(
    # 基础信息
    name='sb-pyorbbecsdk',
    version='1.3.1',
    author='Joe Dong, Xiang Yang',
    author_email='mocun@orbbec.com, yangxiang@baai.ac.cn',
    maintainer='Orbbec 3D Technology',
    maintainer_email='support@orbbec.com',
    
    # 描述信息
    description='Python wrapper for the Orbbec 3D Camera SDK',
    long_description=read_long_description(),
    long_description_content_type='text/markdown',
    
    # 项目URL
    url='https://github.com/orbbec/pyorbbecsdk',
    project_urls={
        'Homepage': 'https://orbbec3d.com/',
        'Documentation': 'https://orbbec.github.io/pyorbbecsdk/',
        'Source Code': 'https://github.com/orbbec/pyorbbecsdk',
        'Issue Tracker': 'https://github.com/orbbec/pyorbbecsdk/issues',
    },
    
    # 许可证
    license='Apache License 2.0',
    license_files=['LICENSE'],
    
    # 分类器（用于 PyPI）
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: POSIX :: Linux',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: MacOS',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Multimedia :: Graphics :: 3D Modeling',
        'Topic :: Scientific/Engineering :: Image Recognition',
        'Topic :: Scientific/Engineering :: Visualization',
    ],
    
    # 关键词
    keywords=[
        'orbbec',
        '3d-camera',
        'depth-camera',
        'computer-vision',
        'point-cloud',
        'rgbd',
        'sdk',
    ],
    
    # 包配置
    packages=['pyorbbecsdk'],
    package_dir={'pyorbbecsdk': 'src/pyorbbecsdk'} if Path('src/pyorbbecsdk').exists() else {},
    include_package_data=True,
    zip_safe=False,
    
    # 扩展模块
    ext_modules=[PrebuiltExtension('pyorbbecsdk', 'install/lib')],
    
    # 自定义命令
    cmdclass={
        'build_ext': CustomBuildExt,
        'bdist_wheel': PlatformSpecificWheel,
    },
    
    # Python 要求
    python_requires='>=3.8',
    
    # 安装依赖
    install_requires=get_requirements(),
    
    # 额外依赖（开发/构建）
    extras_require={
        'dev': [
            'pytest>=7.0',
            'pytest-cov>=4.0',
            'black>=23.0',
            'flake8>=6.0',
            'mypy>=1.0',
            'sphinx>=7.0',
        ],
        'build': [
            'wheel>=0.40.0',
            'setuptools>=65.0',
            'auditwheel>=5.0',
            'twine>=4.0',
        ],
    },
    
    # 入口点（如果需要命令行工具）
    entry_points={
        'console_scripts': [
            # 'orbbec-tool=pyorbbecsdk.cli:main',
        ],
    },
    
    # 平台支持
    platforms=[
        'Linux',
        'Windows',
        'macOS',
    ],
)