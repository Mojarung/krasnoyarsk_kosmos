# Как подключить свою модель

Пакет `fire_ml` связывает модели с `inference.py` и с сервисом. Модель реализует один метод `predict`, всё остальное (чтение чипов, параллельный инференс, RLE, сборка `submission.csv`, векторизация в сервисе) уже написано и менять не нужно.

## Модель гарей за четыре шага

1. Создайте файл `ml/src/fire_ml/bs_model.py`:

```python
import numpy as np

from fire_ml.contract import BsChip, BsPrediction


class MyBurnSeverity:
    name = "my-bs-v1"  # попадёт в карточку сцены в сервисе

    def __init__(self) -> None:
        ...  # загрузка весов один раз на процесс

    def predict(self, chip: BsChip) -> BsPrediction:
        severity = np.zeros(chip.s2_post.shape[1:], dtype=np.uint8)
        ...  # 0 - нет гари, 1 - слабая, 2 - средняя, 3 - сильная
        return BsPrediction(severity=severity)
```

Что лежит в `BsChip` (все растры одного чипа совмещены попиксельно, 512×512):

| Поле | Форма и тип | Каналы |
|---|---|---|
| `s2_pre`, `s2_post` | (10, H, W) uint16, отражение ×10000 | B2, B3, B4, B5, B6, B7, B8A, B11, B12, SCL |
| `s1_pre`, `s1_post` | (2, H, W) int16, σ⁰ в дБ ×100 | VV, VH |
| `aux` | (3, H, W) int16 | dem, slope, landcover (ESA WorldCover) |

2. Веса положите в `ml/src/fire_ml/weights/` и читайте через `importlib.resources`, как в `af_gbm.py`. Абсолютных путей быть не должно: критерий воспроизводимости это проверяет. Если файл больше 50 МБ, в git его не кладите, опишите в корневом README, откуда его взять.

3. Сделайте модель моделью по умолчанию в трёх местах:
   - `ml/src/fire_ml/registry.py`: `DEFAULT_BS = "fire_ml.bs_model:MyBurnSeverity"`
   - `docker-compose.yml`: дефолт переменной `FIRE_ML_BS`
   - `.env.example`: строка `FIRE_ML_BS=...`

4. Новые зависимости добавляйте в пакет, а не в корень: `uv add --package fire-ml <пакет>`. Они попадут и в образ сервиса.

## Проверка

```bash
uv run python inference.py --data-dir DATA/fire-test-renamed/test --output submission.csv
uv run python validate_submission.py --submission submission.csv --template DATA/fire-test-renamed/test/sample_submission.csv
uv run pytest
```

Валидатор должен напечатать `ошибок 0`. Посмотреть модель на карте: `docker compose up --build`, затем в интерфейсе «Конвейер» - «Прогнать готовую сцену», или переобработать всё через `POST /api/v1/scenes/{id}/reprocess`. Вкладка «Метрики» покажет IoU_burn и mIoU_sev по сценам с эталоном.

## Ограничения, о которые легко споткнуться

- **Скорость.** За инференс всего теста быстрее 30 с дают 8 баллов. Сейчас 9,5 с на 12 ядрах при индексном baseline гарей, на 89 BS-чипов остаётся около 20 с. `inference.py` запускает до 8 процессов, модель создаётся один раз на процесс. С PyTorch ограничьте потоки внутри процесса (`torch.set_num_threads(1)`), иначе процессы задушат друг друга.
- **Классы не пересекаются** по построению: `inference.py` кодирует `severity == 1`, `== 2`, `== 3` из одной маски.
- **Облачные чипы** должны обрабатываться без падения. Исключение в `predict` не роняет скрипт, но даёт пустую маску по чипу и запись в лог.
- **Детерминизм.** Зафиксируйте сиды: повторный запуск должен давать метрику с точностью 0,005.

## Что уже есть по активному горению

`af_features.py` - признаки, `af_gbm.py` - модель, `research/af/REPORT.md` - исследование. Подход (предфильтр кандидатов, попиксельный бустинг, территориальная кросс-валидация по следам чипов) переносится на гари почти без изменений: эталон степеней построен порогами dNBR внутри типа покрова, так что признаки dNBR, RdNBR, NBR до и после, разности VV и VH, SCL и landcover должны восстанавливать его хорошо.
