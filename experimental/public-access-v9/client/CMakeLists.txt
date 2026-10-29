cmake_minimum_required(VERSION 3.20)
project(NebulaPublicAccessRemoteV9 LANGUAGES CXX)

set(NEBULA_REMOTE_TRANSPORT_SHA256 "" CACHE STRING
    "Reviewed lowercase SHA-256 of sibling NebulaRemoteTransport.exe")
string(LENGTH "${NEBULA_REMOTE_TRANSPORT_SHA256}" NEBULA_REMOTE_TRANSPORT_SHA256_LENGTH)
if(NOT NEBULA_REMOTE_TRANSPORT_SHA256_LENGTH EQUAL 64 OR
   NOT NEBULA_REMOTE_TRANSPORT_SHA256 MATCHES "^[0-9a-f]+$")
  message(FATAL_ERROR "NEBULA_REMOTE_TRANSPORT_SHA256 must be exactly 64 lowercase hex characters")
endif()
configure_file(RemoteTransportPin.h.in RemoteTransportPin.h @ONLY)

add_library(NebulaPublicAccess SHARED
  NebulaPublicAccess.cpp
  NebulaRemoteBootstrap.cpp)
set_target_properties(NebulaPublicAccess PROPERTIES PREFIX "")
target_include_directories(NebulaPublicAccess PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_compile_features(NebulaPublicAccess PRIVATE cxx_std_17)
target_compile_definitions(NebulaPublicAccess PRIVATE UNICODE _UNICODE)
target_link_libraries(NebulaPublicAccess PRIVATE crypt32 bcrypt)
if(MSVC)
  target_compile_options(NebulaPublicAccess PRIVATE /W4 /WX /guard:cf /sdl)
  target_link_options(NebulaPublicAccess PRIVATE /DYNAMICBASE /NXCOMPAT /GUARD:CF)
else()
  target_compile_options(NebulaPublicAccess PRIVATE -Wall -Wextra -Werror)
  target_link_options(NebulaPublicAccess PRIVATE -static -static-libgcc -static-libstdc++)
endif()
