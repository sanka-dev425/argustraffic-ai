# 🤝 Contributing to ArgusTraffic AI

Thank you for your interest in contributing to **ArgusTraffic AI**! We welcome contributions from computer vision engineers, ITS researchers, distributed systems architects, and open-source enthusiasts.

---

## 🛠️ Development Setup

1. **Fork and Clone**:
   ```bash
   git clone https://github.com/argustraffic/argustraffic-ai.git
   cd argustraffic-ai
   ```
2. **Setup Virtual Environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   pip install -e .
   ```
3. **Run Automated Test Suite**:
   ```bash
   pytest tests/
   ```

---

## 📐 Engineering & Architecture Standards

1. **Protocol Adherence**: Any new detector, tracker, or risk evaluator must implement the domain protocols defined in [`src/core/interfaces.py`](file:///c:/Users/rampa/Downloads/New%20folder%20(19)/src/core/interfaces.py).
2. **Zero Magic Numbers**: All operational thresholds and constants must be declared and validated in [`src/core/config_schema.py`](file:///c:/Users/rampa/Downloads/New%20folder%20(19)/src/core/config_schema.py).
3. **Test Coverage**: All bug fixes and new features must be accompanied by unit and/or integration tests in `tests/`.
4. **Architecture Decision Records**: Any substantial architectural modification requires an ADR in `docs/adr/`.
