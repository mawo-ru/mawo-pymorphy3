#!/bin/bash
# Локальный тест CI окружения для mawo-pymorphy3

set -e  # Прерывать при ошибках

echo "🐳 Запуск локального теста CI окружения..."

# Используем тот же образ Python, что и в CI
PYTHON_VERSION=${1:-3.10}

docker run --rm -v "$(pwd):/workspace" -w /workspace python:${PYTHON_VERSION}-slim bash -c '
echo "📦 Python version:"
python --version

echo -e "\n📥 Установка pip..."
python -m pip install --upgrade pip

echo -e "\n📥 Установка зависимостей (dawg-python, tqdm)..."
pip install -q dawg-python>=0.7.2 tqdm>=4.66.0

echo -e "\n📥 Установка пакета mawo-pymorphy3..."
pip install -e ".[dev]"

echo -e "\n✅ Проверка импорта dawg_python..."
python -c "import dawg_python; print(\"dawg_python module: OK\")"

echo -e "\n✅ Проверка импорта mawo_pymorphy3..."
python -c "import mawo_pymorphy3; print(\"mawo_pymorphy3: OK\")"

echo -e "\n🧪 Запуск тестов..."
pytest tests/ -v --tb=short

echo -e "\n🎉 Все проверки пройдены успешно!"
'
