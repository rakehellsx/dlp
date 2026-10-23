cmake_minimum_required(VERSION 3.16)
project(dlpcenter LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release)
endif()

find_package(Drogon CONFIG REQUIRED)
find_package(PostgreSQL REQUIRED)
find_package(OpenSSL REQUIRED)
add_library(dlp_bcrypt STATIC third_party/crypt_blowfish/crypt_blowfish.c)
set_target_properties(dlp_bcrypt PROPERTIES C_STANDARD 99 C_STANDARD_REQUIRED YES)
if(MSVC)
    add_compile_options(/utf-8 /bigobj)
    target_compile_options(dlp_bcrypt PRIVATE /utf-8)
endif()
if(WIN32)
    add_compile_definitions(NOMINMAX WIN32_LEAN_AND_MEAN _WIN32_WINNT=0x0601 _CRT_SECURE_NO_WARNINGS)
endif()

file(GLOB_RECURSE sources CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/controllers/*.cc"
    "${CMAKE_CURRENT_SOURCE_DIR}/filters/*.cc"
    "${CMAKE_CURRENT_SOURCE_DIR}/utils/*.cc"
    "${CMAKE_CURRENT_SOURCE_DIR}/services/*.cc"
    "${CMAKE_CURRENT_SOURCE_DIR}/main.cc"
)

add_executable(${PROJECT_NAME} ${sources})
target_include_directories(${PROJECT_NAME} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(${PROJECT_NAME} PRIVATE Drogon::Drogon PostgreSQL::PostgreSQL OpenSSL::Crypto dlp_bcrypt)

if(WIN32)
    target_link_libraries(${PROJECT_NAME} PRIVATE ws2_32 advapi32)
endif()
include(CTest)
if(BUILD_TESTING)
    add_executable(dlp_platform_test tests/platform_test.cc utils/Platform.cc services/Pg.cc services/ImageWorker.cc services/FileStore.cc services/Validation.cc)
    target_include_directories(dlp_platform_test PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    target_link_libraries(dlp_platform_test PRIVATE Drogon::Drogon PostgreSQL::PostgreSQL OpenSSL::Crypto dlp_bcrypt)
    if(WIN32)
        target_link_libraries(dlp_platform_test PRIVATE ws2_32 advapi32)
    endif()
    add_test(NAME platform COMMAND dlp_platform_test)
    set_tests_properties(platform PROPERTIES WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/..")
endif()
