#ifndef TOPKSTREAM_STATISTICS_H
#define TOPKSTREAM_STATISTICS_H

// The MIT License (MIT)
// Copyright (c) 2018 Willi Mann
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

#include<ostream>
#include<iomanip>
#include<iostream>
#include<sstream>
#include<algorithm>


#ifdef NO_STAT_COUNTERS
struct RealIncreaser {
	template<class T>
	inline static void inc(T ) {}
	template<class T>
	inline static void add(T, T) {}
	template<class T>
	inline static void set(T & val, T a) {}
};
#else
struct RealIncreaser {
	template<class T>
	inline static void inc(T & val) {
		val += 1;
	}
	template<class T>
	inline static void add(T & val, T a) {
		val += a;
	}
	template<class T>
	inline static void set(T & val, T a) {
		val = a;
	}
};
#endif

template <typename Increaser>
class Statistics {
	public:
		struct StatItem {
			unsigned long value;
			inline void inc() {
				Increaser::inc(value);
			}
			inline void add(unsigned int a) {
				Increaser::add(value, a);
			}
			StatItem() : value(0) {}
		};

		struct StatAvgItem {
			unsigned long sum;
			unsigned long count;
			unsigned long min;
			unsigned long max;
			inline void record(unsigned long a) {
				Increaser::inc(count);
				Increaser::add(sum, a);
				Increaser::set(min, std::min(min, a));
				Increaser::set(max, std::max(max, a));
			}
			StatAvgItem() : sum(0), count(0), min(INT_MAX), max(0) {}
		};

		struct StatAvgFloatItem {
			double sum;
			unsigned long count;
			double min;
			double max;
			inline void record(double a) {
				Increaser::inc(count);
				Increaser::add(sum, a);
				Increaser::set(min, std::min(min, a));
				Increaser::set(max, std::max(max, a));
			}
			StatAvgFloatItem() : sum(0), count(0), min(INT_MAX), max(0) {}
		};

		// step 1/2 ADD Items you want to count/report
		//
		// StatItem: Just a counter
		// StatAvgitem: report integer values, compute avg,min,max
		// StatAvgFloatitem: report float values, compute avg,min,max
		struct StatItem steps;

		struct StatAvgItem nval;

		struct StatAvgFloatItem avgparamval;


		template <class T>
		static inline void printitem_abstract(const std::string & descr, const T & item) {
			if(item.sum != 0) {
				std::cout << std::setw(20) << descr + "sum" << std::setw(14) << item.sum << std::endl;
			}
			if(item.count != 0) {
				std::cout << std::setw(20) << descr + "count" << std::setw(14) << item.count << std::endl;
				std::cout << std::setw(20) << descr + "avg" << std::setw(14) << (0.0 + item.sum) / item.count << std::endl;
			}
			if(item.min != INT_MAX) {
				std::cout << std::setw(20) << descr + "min" << std::setw(14) << item.min << std::endl;
			}
			if(item.max != 0) {
				std::cout << std::setw(20) << descr + "max" << std::setw(14) << item.max << std::endl;
			}
		}

		static inline void printitem(const std::string & descr, const StatAvgItem & item) {
			printitem_abstract(descr, item);
		}

		static inline void printitem(const std::string & descr, const StatAvgFloatItem & item) {
			printitem_abstract(descr, item);
		}


		static inline void printitem(const std::string & descr, const StatItem & item) {
			if(item.value != 0) {
				std::cout << std::setw(20) << descr << std::setw(14) << item.value << std::endl;
			}
		}

		//step 2/2 Add items here such that it gets printed when the statistics object is printed
		friend std::ostream & operator<<(std::ostream & os, const Statistics<Increaser> & statistics) {
			std::cout << "Statistics:" << std::endl;
			printitem("steps", statistics.steps);
			printitem("nval", statistics.nval);
			printitem("avgparamval", statistics.avgparamval);

			return os;
		}
};


#endif
