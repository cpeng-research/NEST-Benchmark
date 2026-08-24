set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++11")

include(CheckSymbolExists)

CHECK_SYMBOL_EXISTS(clock_gettime "time.h" HAVE_CLOCK_GETTIME)

if(NOT HAVE_CLOCK_GETTIME)
	add_definitions(-DGETRUSAGE)
endif()


add_executable(timings_statistics timings_statistics.cxx ../timings/timing.cxx)
