// The MIT License (MIT)
// Copyright (c) 2017 Mateusz Pawlik, Nikolaus Augsten, Daniel Kocher, and 
// Thomas Huetter.
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

#pragma once
template <class Label>
int UnitCostModel<Label>::ren(const node::Node<Label>& node1,
                              const node::Node<Label>& node2) const {
  if (node1.label() == node2.label()) {
    return 0;
  }
  return 1;
}

template <class Label>
int UnitCostModel<Label>::del(const node::Node<Label>& node) const {
  return 1;
}

template <class Label>
int UnitCostModel<Label>::ins(const node::Node<Label>& node) const {
  return 1;
}


template <class Label>
UnitCostModelLD<Label>::UnitCostModelLD(label::LabelDictionary<Label>& ld) :
    ld_(ld) {}

template <typename Label>
double UnitCostModelLD<Label>::ren(const int label_id_1,
    const int label_id_2) const {
  if (label_id_1 == label_id_2) {
    return 0.0;
  }
  return 1.0;
}

// Argument's name deleted because not used.
template <typename Label>
double UnitCostModelLD<Label>::del(const int) const {
  return 1.0;
}

// Argument's name deleted because not used.
template <typename Label>
double UnitCostModelLD<Label>::ins(const int) const {
  return 1.0;
}


template <class Label>
UnitCostModelJSON<Label>::UnitCostModelJSON(label::LabelDictionary<Label>& ld) :
    ld_(ld) {}

template <typename Label>
double UnitCostModelJSON<Label>::ren(const int label_id_1,
    const int label_id_2) const {
  if (ld_.get(label_id_1).get_type() != ld_.get(label_id_2).get_type())
    return std::numeric_limits<double>::infinity();

  const std::string& lhs = ld_.get(label_id_1).get_label();
  const std::string& rhs = ld_.get(label_id_2).get_label();

  // --- modified: use normalized Levenshtein cost for label differences
  if (lhs == rhs) {
    return 0.0;
  }

  // Normalize labels for content cost: drop trailing colon, then strip paired quotes.
  auto normalize_label = [](const std::string& s) -> std::string {
    std::string t = s;
    if (!t.empty() && t.back() == ':') {
      t.pop_back();
    }
    if (t.size() >= 2) {
      const char first = t.front();
      const char last = t.back();
      if ((first == '"' && last == '"') || (first == '\'' && last == '\'')) {
        t = t.substr(1, t.size() - 2);
      }
    }
    return t;
  };

  auto levenshtein = [](const std::string& a, const std::string& b) -> double {
    const size_t n = a.size();
    const size_t m = b.size();
    if (n == 0) return static_cast<double>(m);
    if (m == 0) return static_cast<double>(n);
    std::vector<double> prev(m + 1), cur(m + 1);
    for (size_t j = 0; j <= m; ++j) prev[j] = static_cast<double>(j);
    for (size_t i = 1; i <= n; ++i) {
      cur[0] = static_cast<double>(i);
      for (size_t j = 1; j <= m; ++j) {
        double cost = (a[i - 1] == b[j - 1]) ? 0.0 : 1.0;
        cur[j] = std::min({prev[j] + 1.0,           // deletion
                           cur[j - 1] + 1.0,        // insertion
                           prev[j - 1] + cost});    // substitution
      }
      std::swap(prev, cur);
    }
    return prev[m];
  };

  // Apply normalization (drop trailing colon, then strip quotes) before Levenshtein.
  const std::string lhs_stripped = normalize_label(lhs);
  const std::string rhs_stripped = normalize_label(rhs);

  const double max_len = static_cast<double>(
      std::max(lhs_stripped.size(), rhs_stripped.size()));
  if (max_len == 0.0) {
    return 0.0;
  }
  return levenshtein(lhs_stripped, rhs_stripped) / max_len;
}

// Argument's name deleted because not used.
template <typename Label>
double UnitCostModelJSON<Label>::del(const int) const {
  return 1.0;
}

// Argument's name deleted because not used.
template <typename Label>
double UnitCostModelJSON<Label>::ins(const int) const {
  return 1.0;
}
