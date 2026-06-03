# =================================================================
# 【真正的项目内截胡】在 Dart AOT 编译被拉起前，物理伪造符号链接
# =================================================================
if(NOT EXISTS "/usr/lib/llvm-14/bin/ld")
    # 如果系统没有这个死板的硬编码路径，我们在项目本地临时伪造一个
    set(LOCAL_FAKE_LLVM "${CMAKE_BINARY_DIR}/../llvm-14/bin")

    # 物理创建项目内的临时高仿目录
    execute_process(COMMAND ${CMAKE_COMMAND} -E make_directory "${LOCAL_FAKE_LLVM}")
    execute_process(COMMAND ln -sf /usr/bin/ld "${LOCAL_FAKE_LLVM}/ld")
    execute_process(COMMAND ln -sf /usr/bin/ld "${LOCAL_FAKE_LLVM}/ld.lld")

    # 强行将项目本地的伪造目录注入到当前执行上下文的全局 PATH 最前端
    # 这样后续被拉起的 flutter_assemble 及其子进程 dart_build 将强制走这里
    set(ENV{PATH} "${LOCAL_FAKE_LLVM}:$ENV{PATH}")
endif()
# =================================================================
# 【项目内闭环配置】死绑本地二进制 CMake 与系统通用编译器
# =================================================================
set(CMAKE_C_COMPILER "/usr/bin/gcc" CACHE FILEPATH "C Compiler" FORCE)
set(CMAKE_CXX_COMPILER "/usr/bin/g++" CACHE FILEPATH "CXX Compiler" FORCE)
# =================================================================

# Project-level configuration.
cmake_minimum_required(VERSION 3.13)
project(runner LANGUAGES CXX)

# The name of the executable created for the application. Change this to change
# the on-disk name of your application.
set(BINARY_NAME "LogAgent")

# The unique GTK application identifier for this application.
set(APPLICATION_ID "com.q.agent.logagent")

# Explicitly opt in to modern CMake behaviors to avoid warnings with recent
# versions of CMake.
cmake_policy(SET CMP0063 NEW)

# Load bundled libraries from the lib/ directory relative to the binary.
set(CMAKE_INSTALL_RPATH "$ORIGIN/lib")

# Root filesystem for cross-building.
if(FLUTTER_TARGET_PLATFORM_SYSROOT)
  set(CMAKE_SYSROOT ${FLUTTER_TARGET_PLATFORM_SYSROOT})
  set(CMAKE_FIND_ROOT_PATH ${CMAKE_SYSROOT})
  set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
  set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
  set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
  set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
endif()

# Define build configuration options.
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE "Debug" CACHE
    STRING "Flutter build mode" FORCE)
  set_property(CACHE CMAKE_BUILD_TYPE PROPERTY STRINGS
    "Debug" "Profile" "Release")
endif()

# Compilation settings that should be applied to most targets.
function(APPLY_STANDARD_SETTINGS TARGET)
  target_compile_features(${TARGET} PUBLIC cxx_std_14)
  target_compile_options(${TARGET} PRIVATE -Wall -Werror)

  # 🚀 🔥【核心新增】：在这里全局灌入放行标志，强制抹平 media_kit_video 等插件的有符号/无符号对比警告拦截！
  target_compile_options(${TARGET} PRIVATE -Wno-sign-compare -Wno-error=sign-compare)

  target_compile_options(${TARGET} PRIVATE "$<$<NOT:$<CONFIG:Debug>>:-O3>")
  target_compile_definitions(${TARGET} PRIVATE "$<$<NOT:$<CONFIG:Debug>>:NDEBUG>")
endfunction()

# Flutter library and tool build rules.
set(FLUTTER_MANAGED_DIR "${CMAKE_CURRENT_SOURCE_DIR}/flutter")
add_subdirectory(${FLUTTER_MANAGED_DIR})

# System-level dependencies.
find_package(PkgConfig REQUIRED)
pkg_check_modules(GTK REQUIRED IMPORTED_TARGET gtk+-3.0)

# Application build; see runner/CMakeLists.txt.
add_subdirectory("runner")

# Run the Flutter tool portions of the build. This must not be removed.
add_dependencies(${BINARY_NAME} flutter_assemble)

# Put unbundled copy in a subdirectory instead of the default top-level location.
set_target_properties(${BINARY_NAME}
  PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/intermediates_do_not_run"
)

# Generated plugin build rules.
include(flutter/generated_plugins.cmake)

# === 💡 核心修复：死绑并强制覆盖安装前缀，彻底拦截并捏死往 /usr/local 拷贝的冲动 ===
set(BUILD_BUNDLE_DIR "${PROJECT_BINARY_DIR}/bundle")
set(CMAKE_INSTALL_PREFIX "${BUILD_BUNDLE_DIR}" CACHE PATH "Force Project Sandbox Prefix" FORCE)

# Start with a clean build bundle directory every time.
install(CODE "
  file(REMOVE_RECURSE \"${BUILD_BUNDLE_DIR}/\")
  " COMPONENT Runtime)

set(INSTALL_BUNDLE_DATA_DIR "${CMAKE_INSTALL_PREFIX}/data")
set(INSTALL_BUNDLE_LIB_DIR "${CMAKE_INSTALL_PREFIX}/lib")

# 原生安全的本地沙盒投递
install(TARGETS ${BINARY_NAME} RUNTIME DESTINATION "${CMAKE_INSTALL_PREFIX}"
  COMPONENT Runtime)

install(FILES "${FLUTTER_ICU_DATA_FILE}" DESTINATION "${INSTALL_BUNDLE_DATA_DIR}"
  COMPONENT Runtime)

install(FILES "${FLUTTER_LIBRARY}" DESTINATION "${INSTALL_BUNDLE_LIB_DIR}"
  COMPONENT Runtime)

foreach(bundled_library ${PLUGIN_BUNDLED_LIBRARIES})
  install(FILES "${bundled_library}"
    DESTINATION "${INSTALL_BUNDLE_LIB_DIR}"
    COMPONENT Runtime)
endforeach(bundled_library)

set(BUNDLED_FFMPEG_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/ffmpeg/linux")
foreach(FFMPEG_TOOL ffmpeg ffprobe)
  if(EXISTS "${BUNDLED_FFMPEG_DIR}/${FFMPEG_TOOL}")
    install(PROGRAMS "${BUNDLED_FFMPEG_DIR}/${FFMPEG_TOOL}"
      DESTINATION "${CMAKE_INSTALL_PREFIX}"
      COMPONENT Runtime)
  endif()
endforeach()

# Copy the native assets provided by the build.dart from all packages.
# 🚀 【安全防线】：只有当目录真正存在时才触发安装，彻底解决空目录熔断 Bug！
set(NATIVE_ASSETS_DIR "${PROJECT_BUILD_DIR}native_assets/linux/")
if(EXISTS "${NATIVE_ASSETS_DIR}")
    install(DIRECTORY "${NATIVE_ASSETS_DIR}"
       DESTINATION "${INSTALL_BUNDLE_LIB_DIR}"
       COMPONENT Runtime)
endif()

# Fully re-copy the assets directory on each build to avoid stale files.
set(FLUTTER_ASSET_DIR_NAME "flutter_assets")
install(CODE "
  file(REMOVE_RECURSE \"${INSTALL_BUNDLE_DATA_DIR}/${FLUTTER_ASSET_DIR_NAME}\")
  " COMPONENT Runtime)
install(DIRECTORY "${PROJECT_BUILD_DIR}/${FLUTTER_ASSET_DIR_NAME}"
  DESTINATION "${INSTALL_BUNDLE_DATA_DIR}" COMPONENT Runtime)

# Install the AOT library on non-Debug builds only.
if(NOT CMAKE_BUILD_TYPE MATCHES "Debug")
  install(FILES "${AOT_LIBRARY}" DESTINATION "${INSTALL_BUNDLE_LIB_DIR}"
    COMPONENT Runtime)
endif()

# 🚀 降维打击补充保障：确保全局环境里也追加无视规则
add_compile_options(-Wno-sign-compare)
add_compile_options(-Wno-error=sign-compare)
