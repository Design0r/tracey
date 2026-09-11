cmake_minimum_required(VERSION 3.24)
project(luma LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(${PROJECT_NAME} src/main.cpp
        src/Application.cpp
        src/Application.h
        src/Store.cpp
        src/Store.h
        src/db.cpp
        src/db.h
        src/ui.cpp
        src/ui.h
        src/theme.cpp
        src/theme.h)

find_package(glfw3 CONFIG REQUIRED)
find_package(glad CONFIG REQUIRED)
find_package(imgui CONFIG REQUIRED)
find_package(unofficial-sqlite3 CONFIG REQUIRED)

target_link_libraries(${PROJECT_NAME} PRIVATE
        glfw
        glad::glad
        imgui::imgui
        unofficial::sqlite3::sqlite3
)

if (CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_link_libraries(${PROJECT_NAME} PRIVATE stdc++exp)
endif ()

if (APPLE)
    target_link_libraries(${PROJECT_NAME} "-framework IOKit")
    target_link_libraries(${PROJECT_NAME} "-framework Cocoa")
    target_link_libraries(${PROJECT_NAME} "-framework OpenGL")
    target_link_libraries(${PROJECT_NAME} "-framework QuartzCore")
endif ()
