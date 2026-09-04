cmake_minimum_required(VERSION 3.16)
project(cadflow_core LANGUAGES CXX)

add_library(cadflow_core SHARED
  src/c_api.cpp
  src/core/session.cpp
  src/flexible/shell_mesh.cpp
  src/io/dxf_profile.cpp
  src/io/exchange.cpp
  src/kernel/construction.cpp
  src/kernel/advanced.cpp
  src/kernel/edge_features.cpp
  src/kernel/features.cpp
  src/kernel/operations.cpp
  src/kernel/queries.cpp
  src/kernel/surfaces.cpp
  src/physics/connections.cpp
  src/physics/surface_contact.cpp
  src/presentation/evaluator.cpp
  src/runtime/graph.cpp
)
target_compile_features(cadflow_core PRIVATE cxx_std_17)
target_compile_definitions(cadflow_core PRIVATE CADFLOW_CORE_BUILD)
target_include_directories(cadflow_core
  PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)

set(CADFLOW_OCCT_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/occt" CACHE PATH "OCCT source tree used for matching headers")
if (DEFINED ENV{CADFLOW_OCCT_LIB_DIR})
  set(_CADFLOW_DEFAULT_OCCT_LIB_DIR "$ENV{CADFLOW_OCCT_LIB_DIR}")
elseif (DEFINED ENV{VIRTUAL_ENV})
  file(GLOB _CADFLOW_VENV_OCCT_LIB_DIRS LIST_DIRECTORIES true
       "$ENV{VIRTUAL_ENV}/lib/python*/site-packages/cadquery_ocp.libs"
       "$ENV{VIRTUAL_ENV}/lib/python*/site-packages/OCP/.dylibs")
  list(LENGTH _CADFLOW_VENV_OCCT_LIB_DIRS _CADFLOW_VENV_OCCT_COUNT)
  if (_CADFLOW_VENV_OCCT_COUNT GREATER 0)
    list(GET _CADFLOW_VENV_OCCT_LIB_DIRS 0 _CADFLOW_DEFAULT_OCCT_LIB_DIR)
  endif()
else()
  set(_CADFLOW_DEFAULT_OCCT_LIB_DIR "")
endif()
if (NOT _CADFLOW_DEFAULT_OCCT_LIB_DIR)
  find_package(Python3 COMPONENTS Interpreter QUIET)
  if (Python3_Interpreter_FOUND)
    execute_process(
      COMMAND "${Python3_EXECUTABLE}" -c
              "import pathlib,sys; print(next((str(q) for p in sys.path for q in (pathlib.Path(p)/'cadquery_ocp.libs', pathlib.Path(p)/'OCP'/'.dylibs') if q.is_dir()), ''))"
      OUTPUT_VARIABLE _CADFLOW_DEFAULT_OCCT_LIB_DIR
      OUTPUT_STRIP_TRAILING_WHITESPACE
    )
  endif()
endif()
set(CADFLOW_OCCT_LIB_DIR "${_CADFLOW_DEFAULT_OCCT_LIB_DIR}" CACHE PATH "Directory containing OCCT shared libraries")
option(CADFLOW_USE_OCCT "Build the native kernel against the matching OCCT wheel" ON)
option(CADFLOW_WITH_STEP "Enable native STEP writer (requires DESTEP headers)" ON)
if (CADFLOW_USE_OCCT AND EXISTS "${CADFLOW_OCCT_SOURCE}/src/TopoDS/TopoDS_Shape.hxx" AND EXISTS "${CADFLOW_OCCT_LIB_DIR}")
  file(GLOB OCCT_PACKAGE_DIRS LIST_DIRECTORIES true "${CADFLOW_OCCT_SOURCE}/src/*")
  target_include_directories(cadflow_core SYSTEM PRIVATE ${OCCT_PACKAGE_DIRS})
  target_compile_definitions(cadflow_core PRIVATE CADFLOW_WITH_OCCT=1)
  set(OCCT_NAMES TKernel TKMath TKG2d TKG3d TKGeomBase TKBRep TKGeomAlgo TKTopAlgo TKPrim TKBO TKBool TKMesh TKOffset TKFillet TKDESTL)
  if (CADFLOW_WITH_STEP)
    list(APPEND OCCT_NAMES TKDE TKDESTEP TKXSBase)
    target_compile_definitions(cadflow_core PRIVATE CADFLOW_WITH_STEP=1)
  endif()
  foreach(OCCT_NAME ${OCCT_NAMES})
    if (APPLE)
      file(GLOB OCCT_LIBRARY "${CADFLOW_OCCT_LIB_DIR}/lib${OCCT_NAME}.7.9.3.dylib")
    else()
      file(GLOB OCCT_LIBRARY "${CADFLOW_OCCT_LIB_DIR}/lib${OCCT_NAME}-*.so.7.9.3")
    endif()
    if (NOT OCCT_LIBRARY)
      message(FATAL_ERROR "Missing OCCT library ${OCCT_NAME} in ${CADFLOW_OCCT_LIB_DIR}")
    endif()
    target_link_libraries(cadflow_core PRIVATE ${OCCT_LIBRARY})
    if (APPLE)
      execute_process(
        COMMAND otool -D "${OCCT_LIBRARY}"
        RESULT_VARIABLE _CADFLOW_OTOOL_RESULT
        OUTPUT_VARIABLE _CADFLOW_OTOOL_OUTPUT
        OUTPUT_STRIP_TRAILING_WHITESPACE
      )
      if (NOT _CADFLOW_OTOOL_RESULT EQUAL 0)
        message(FATAL_ERROR "Could not inspect OCCT library ${OCCT_LIBRARY}")
      endif()
      string(REPLACE "\n" ";" _CADFLOW_OTOOL_LINES "${_CADFLOW_OTOOL_OUTPUT}")
      list(LENGTH _CADFLOW_OTOOL_LINES _CADFLOW_OTOOL_LINE_COUNT)
      if (_CADFLOW_OTOOL_LINE_COUNT LESS 2)
        message(FATAL_ERROR "OCCT library ${OCCT_LIBRARY} has no Mach-O install name")
      endif()
      list(GET _CADFLOW_OTOOL_LINES 1 _CADFLOW_OCCT_INSTALL_NAME)
      string(STRIP "${_CADFLOW_OCCT_INSTALL_NAME}" _CADFLOW_OCCT_INSTALL_NAME)
      get_filename_component(_CADFLOW_OCCT_FILENAME "${OCCT_LIBRARY}" NAME)
      add_custom_command(TARGET cadflow_core POST_BUILD
        COMMAND "${CMAKE_INSTALL_NAME_TOOL}" -change
                "${_CADFLOW_OCCT_INSTALL_NAME}"
                "@rpath/${_CADFLOW_OCCT_FILENAME}"
                "$<TARGET_FILE:cadflow_core>"
        VERBATIM
      )
    endif()
  endforeach()
  if (APPLE)
    set_target_properties(cadflow_core PROPERTIES
        BUILD_RPATH "${CADFLOW_OCCT_LIB_DIR}"
        INSTALL_RPATH "@loader_path/../OCP/.dylibs;@loader_path/../vtkmodules/.dylibs"
    )
  else()
    set_target_properties(cadflow_core PROPERTIES
        BUILD_RPATH "${CADFLOW_OCCT_LIB_DIR}"
        INSTALL_RPATH "$ORIGIN/../cadquery_ocp.libs"
    )
  endif()
else()
  if (APPLE AND CADFLOW_USE_OCCT)
    message(FATAL_ERROR
      "A matching cadquery-ocp 7.9.3 installation is required for macOS builds. "
      "Install cadquery-ocp==7.9.3.1 or set CADFLOW_OCCT_LIB_DIR."
    )
  endif()
  message(WARNING "Matching OCCT headers/libraries not found; building the analytic fallback")
endif()
set_target_properties(cadflow_core PROPERTIES
    OUTPUT_NAME cadflow_core
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)

install(TARGETS cadflow_core
    LIBRARY DESTINATION cadflow
    RUNTIME DESTINATION cadflow
)
install(FILES include/cadflow_core.h DESTINATION cadflow/include)

option(CADFLOW_BUILD_NATIVE_TESTS "Build native CadFlow regression tests" OFF)
if (CADFLOW_BUILD_NATIVE_TESTS)
  add_executable(cadflow_presentation_evaluator_test
      tests/presentation_evaluator_test.cpp
  )
  target_compile_features(cadflow_presentation_evaluator_test PRIVATE cxx_std_17)
  target_link_libraries(cadflow_presentation_evaluator_test PRIVATE cadflow_core)
endif()

if (MSVC)
  target_compile_options(cadflow_core PRIVATE /W4 /permissive-)
else()
  target_compile_options(cadflow_core PRIVATE -Wall -Wextra -Wpedantic)
endif()
