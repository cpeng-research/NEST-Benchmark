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

#include "../timings/timing.h"
#include "../statistics/statistics.h"

Statistics<RealIncreaser> statistics;
Timing timing;

long fib(long n) {
	// Increment step counter
	statistics.steps.inc();
	// Record n (does not really record it, just sums it up, increments a counter and updates min/max)
	statistics.nval.record(n);
	if(n < 2) {
		return 1;
	}
	// Record avg of parameters (does not really record it, just sums it up, increments a counter and updates min/max)
	statistics.avgparamval.record((double(n-1)+double(n-2))/2);
	return fib(n - 1) + fib(n-2);
}

int main(void) {
	// Initialized Timing object
	Timing::Interval * tfib25 = timing.create_enroll("fib25");
	//start timing
	tfib25->start();
	//execute what you want to time
	long res = fib(25);
	// stop timing
	tfib25->stop();
	std::cout << "Result: " << res << std::endl;
	std::cout << statistics;
	std::cout << timing;
}
