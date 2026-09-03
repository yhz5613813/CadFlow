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
       "$ENV{VIRTUAL_ENV}/lib/python*/site-packages/cadquery_ocp.libs")
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
              "import pathlib,sys; print(next((str(pathlib.Path(p)/'cadquery_ocp.libs') for p in sys.path if (pathlib.Path(p)/'cadquery_ocp.libs').is_dir()), ''))"
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
  set(OCCT_NAMES TKernel TKMath TKG2d TKG3d TKGeomBase TKBRep TKGeomAlgo TKTopAlgo TKPrim TKBO TKMesh TKOffset TKFillet TKDESTL)
  if (CADFLOW_WITH_STEP)
    list(APPEND OCCT_NAMES TKDE TKDESTEP TKXSBase)
    target_compile_definitions(cadflow_core PRIVATE CADFLOW_WITH_STEP=1)
  endif()
  foreach(OCCT_NAME ${OCCT_NAMES})
    file(GLOB OCCT_LIBRARY "${CADFLOW_OCCT_LIB_DIR}/lib${OCCT_NAME}-*.so.7.9.3")
    if (NOT OCCT_LIBRARY)
      message(FATAL_ERROR "Missing OCCT library ${OCCT_NAME} in ${CADFLOW_OCCT_LIB_DIR}")
    endif()
    target_link_libraries(cadflow_core PRIVATE ${OCCT_LIBRARY})
  endforeach()
  set_target_properties(cadflow_core PROPERTIES
      BUILD_RPATH "${CADFLOW_OCCT_LIB_DIR}"
      INSTALL_RPATH "$ORIGIN/../cadquery_ocp.libs"
  )
else()
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

if (MSVC)
  target_compile_options(cadflow_core PRIVATE /W4 /permissive-)
else()
  target_compile_options(cadflow_core PRIVATE -Wall -Wextra -Wpedantic)
endif()
